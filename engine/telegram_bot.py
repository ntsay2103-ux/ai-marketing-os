"""
Telegram-интерфейс AI Marketing OS.

Все действия маршрутизируются через engine/controller.py.
Бизнес-логика не дублируется.

Команды:
  /start   — справка
  /status  — текущее состояние системы
  /next    — выполнить следующий автоматический шаг
  /review  — рассмотреть идеи (inline-кнопки)
  /results — внести результаты опубликованной кампании

Запуск:
  python engine/telegram_bot.py

Требуемые переменные окружения (.env):
  TELEGRAM_BOT_TOKEN  — токен бота от @BotFather
  TELEGRAM_CHAT_ID    — chat_id единственного авторизованного пользователя
"""

import asyncio
import logging
import os
import sys
from pathlib import Path

import yaml
from dotenv import load_dotenv
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ConversationHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

BASE_DIR = Path(__file__).parent.parent
load_dotenv(BASE_DIR / ".env")

sys.path.insert(0, str(BASE_DIR))

from engine.store import Store
from engine import controller
from engine import scheduler_state as sched_state
from engine import tips_research

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)s  %(name)s  %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)
logging.getLogger("httpx").setLevel(logging.WARNING)


# ---------------------------------------------------------------------------
# Конфигурация
# ---------------------------------------------------------------------------

def _load_project() -> str:
    with open(BASE_DIR / "config.yaml", encoding="utf-8") as f:
        return yaml.safe_load(f)["projects"]["active"]


PROJECT = _load_project()
BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
ALLOWED_CHAT_ID = int(os.getenv("TELEGRAM_CHAT_ID", "0"))
SCHEDULER_HOUR = int(os.getenv("SCHEDULER_HOUR", "9"))   # UTC, по умолчанию 09:00


# ---------------------------------------------------------------------------
# Авторизация
# ---------------------------------------------------------------------------

def _is_authorized(update: Update) -> bool:
    chat_id = update.effective_chat.id if update.effective_chat else None
    return chat_id == ALLOWED_CHAT_ID


async def _deny(update: Update) -> None:
    if update.message:
        await update.message.reply_text("Доступ запрещён.")
    elif update.callback_query:
        await update.callback_query.answer("Доступ запрещён.", show_alert=True)


# ---------------------------------------------------------------------------
# Форматирование
# ---------------------------------------------------------------------------

_STATE_HINTS = {
    "IDLE":                "Запустите /next — система проведёт Research и найдёт идеи.",
    "PENDING_REVIEW":      "Запустите /review — рассмотрите идеи и одобрите лучшую.",
    "PENDING_CREATE":      "Запустите /next — система создаст контент для одобренной кампании.",
    "PENDING_PUBLICATION": "Опубликуйте материал на платформах, затем запустите /next.",
    "PENDING_RESULTS":     "Внесите результаты публикации через /results.",
}


def _format_status(status: dict) -> str:
    state = status["state"]
    desc = status["description"]
    hint = _STATE_HINTS.get(state, "")

    lines = [f"*Состояние:* `{state}`", desc]
    if hint:
        lines.append(f"\n_{hint}_")
    return "\n".join(lines)


def _format_idea(idea: dict, index: int, total: int) -> str:
    potential = idea.get("potential", "—")
    rationale = idea.get("potential_rationale", "—")
    funnel = idea.get("funnel_stage", "—")
    title = idea.get("title", "—")
    trigger = idea.get("trigger", "—")
    adaptation = idea.get("adaptation", "—")

    return (
        f"Идея {index}/{total}\n"
        f"Потенциал: {potential} — {rationale}\n"
        f"Аудитория: {funnel}\n\n"
        f"{title}\n\n"
        f"Триггер: {trigger}\n\n"
        f"Адаптация: {adaptation}"
    )


def _review_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[
        InlineKeyboardButton("✅ Одобрить",  callback_data="review:approve"),
        InlineKeyboardButton("❌ Отклонить", callback_data="review:reject"),
        InlineKeyboardButton("⏭ Пропустить", callback_data="review:skip"),
    ]])


def _instagram_format_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[
        InlineKeyboardButton("🎠 Карусель", callback_data="igformat:carousel"),
        InlineKeyboardButton("🎬 Reels",    callback_data="igformat:reels"),
    ]])


def _campaign_dashboard_keyboard(
    instagram_format: str,
    ig_published: bool,
    launched: bool = False,
    pub_statuses: dict | None = None,
) -> InlineKeyboardMarkup:
    pub_statuses = pub_statuses or {}
    fmt_label = "🎠 Карусель" if instagram_format == "carousel" else "🎬 Reels"

    rows = []
    for key, label in _PUB_LABEL.items():
        status = pub_statuses.get(key, "pending" if not launched else "not_configured")
        emoji  = _PUB_EMOJI.get(status, "⚙️")
        rows.append([InlineKeyboardButton(f"{emoji} {label}", callback_data=f"view:{key}")])

    ig_status = pub_statuses.get("instagram", "pending_manual")
    ig_emoji  = _PUB_EMOJI.get(ig_status, "🟡")
    rows.append([InlineKeyboardButton(
        f"{ig_emoji} 📷 Instagram — {fmt_label}", callback_data="ig:view"
    )])

    if not launched:
        rows.append([InlineKeyboardButton("🚀 Запустить кампанию", callback_data="campaign:launch")])
    elif not ig_published:
        rows.append([InlineKeyboardButton("✅ Instagram опубликован", callback_data="ig:confirm")])

    return InlineKeyboardMarkup(rows)


def _platform_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("🎬 Reels",     callback_data="platform:reels"),
            InlineKeyboardButton("📷 Instagram", callback_data="platform:instagram"),
        ],
        [
            InlineKeyboardButton("📌 Pinterest", callback_data="platform:pinterest"),
            InlineKeyboardButton("📝 Дзен",      callback_data="platform:dzen"),
        ],
        [
            InlineKeyboardButton("🌐 Сайт",      callback_data="platform:site"),
            InlineKeyboardButton("💬 Telegram",  callback_data="platform:tg"),
        ],
    ])


_MAX_MSG = 4000  # Telegram limit is 4096; оставляем запас


def _truncate(text: str) -> str:
    if len(text) <= _MAX_MSG:
        return text
    return text[:_MAX_MSG] + "\n\n…[сообщение обрезано]"


_PLATFORM_LABELS: dict[str, str] = {
    "reels":     "🎬 Reels",
    "instagram": "📷 Instagram",
    "pinterest": "📌 Pinterest",
    "dzen":      "📝 Дзен",
    "site":      "🌐 Сайт",
    "tg":        "💬 Telegram",
}

# Разделы для каждой платформы: (label на кнопке, ключ раздела)
_PLATFORM_SECTIONS: dict[str, list[tuple[str, str]]] = {
    "reels":     [("🎬 Сценарий", "script"), ("🪝 Хуки", "hooks"), ("🎵 Музыка", "music")],
    "instagram": [("📝 Пост", "post"), ("🪝 Хуки", "hooks"), ("🎠 Карусель", "carousel"),
                  ("💬 Подпись", "caption"), ("📣 CTA", "cta"), ("🏷 Хэштеги", "hashtags")],
    "pinterest": [("📌 Название", "title"), ("💬 Описание", "caption"), ("🏷 Хэштеги", "hashtags")],
    "dzen":      [("📰 Заголовок", "title"), ("📝 Статья", "post"), ("📣 CTA", "cta")],
    "site":      [("🔤 Заголовок", "title"), ("📄 Мета", "meta"), ("📝 Статья", "post"), ("📣 CTA", "cta")],
    "tg":        [("📝 Пост", "post"), ("📣 CTA", "cta")],
}

# Ключ платформы в Telegram → ключ в JSON-данных контента
_PLATFORM_DATA_KEY: dict[str, str] = {
    "reels":     "reels",
    "instagram": "instagram",
    "pinterest": "pinterest",
    "dzen":      "dzen",
    "site":      "site",
    "tg":        "telegram",
}

# Секции, поддерживающие генерацию изображения
_IMAGE_GEN_SECTIONS: set[tuple[str, str]] = {
    ("instagram", "post"),
    ("instagram", "carousel"),
    ("pinterest", "title"),
    ("pinterest", "caption"),
    ("dzen",      "post"),
    ("site",      "post"),
}

# Размер изображения по платформе
_IMAGE_SIZE: dict[str, str] = {
    "instagram": "1:1",
    "pinterest": "2:3",
    "dzen":      "3:2",
    "site":      "3:2",
}


_PUB_EMOJI = {
    "published":      "🟢",
    "not_configured": "⚙️",
    "pending_manual": "🟡",
    "pending":        "⏳",
    "error":          "🔴",
}

_PUB_LABEL = {
    "threads": "🧵 Threads",
    "dzen":    "📰 Дзен",
    "site":    "🌐 Сайт",
}

_ROLE_LABEL = {
    "hook":        "Зацепка",
    "recognition": "Узнавание",
    "insight":     "Вывод",
    "development": "Развитие",
    "proof":       "Доказательство",
    "cta":         "CTA",
}


def _format_campaign_dashboard(spec: dict) -> str:
    """Форматирует текст дашборда кампании."""
    content_data  = spec.get("content_data", {})
    pub_statuses  = spec.get("pub_statuses", {})
    ig_fmt        = spec.get("instagram_format", "carousel")
    idea_title    = content_data.get("_idea_title", "")

    lines = ["✅ *Кампания готова*"]
    if idea_title:
        lines.append(f"_{idea_title}_\n")

    launched = bool(pub_statuses)  # pub_statuses пусто до нажатия "Запустить кампанию"
    for key, label in _PUB_LABEL.items():
        status = pub_statuses.get(key, "pending" if not launched else "not_configured")
        emoji  = _PUB_EMOJI.get(status, "⚙️")
        lines.append(f"{emoji} {label}")

    ig_status = pub_statuses.get("instagram", "pending_manual")
    ig_emoji  = _PUB_EMOJI.get(ig_status, "🟡")
    ig_label  = "Карусель" if ig_fmt == "carousel" else "Reels"
    lines.append(f"\n{ig_emoji} 📷 Instagram — {ig_label}")
    if ig_status == "pending_manual":
        lines.append("_Ожидает вашей публикации_")

    return "\n".join(lines)


def _format_ig_view(spec: dict) -> str:
    """Форматирует текстовый блок материалов Instagram."""
    content_data = spec.get("content_data", {})
    ig_fmt       = spec.get("instagram_format", "carousel")
    ig           = content_data.get("instagram", {})
    carousel_images = spec.get("carousel_images", {})

    lines = [f"📷 Instagram — {'🎠 Карусель' if ig_fmt == 'carousel' else '🎬 Reels'}\n"]

    if ig_fmt == "carousel":
        slides = ig.get("carousel", [])
        if slides:
            for s in slides:
                slide_num = s.get("slide", "?")
                role      = _ROLE_LABEL.get(s.get("role", ""), f"Слайд {slide_num}")
                text      = s.get("text", "—")
                img_path  = carousel_images.get(str(slide_num))
                img_note  = "🖼 Изображение готово" if img_path else "🖼 Изображение не создано"
                lines.append(f"*{role}*\n{text}\n{img_note}\n")
        else:
            lines.append("Слайды не найдены.\n")
    else:
        reels = ig.get("reels", {})
        if reels.get("script"):
            lines.append(f"*🎬 Сценарий*\n{reels['script']}\n")
        if reels.get("hooks"):
            hooks_str = "\n".join(f"{i+1}. {h}" for i, h in enumerate(reels["hooks"]))
            lines.append(f"*🪝 Хуки*\n{hooks_str}\n")
        if reels.get("cover_idea"):
            lines.append(f"*🖼 Обложка*\n{reels['cover_idea']}\n")
        if reels.get("music_mood"):
            lines.append(f"*🎵 Музыка*\n{reels['music_mood']}\n")

    lines.append("─" * 20)

    if ig.get("caption"):
        lines.append(f"*📝 Подпись*\n{ig['caption']}\n")
    if ig.get("cta"):
        lines.append(f"*📣 CTA*\n{ig['cta']}\n")
    if ig.get("hashtags"):
        tags = "  ".join(f"#{t.lstrip('#')}" for t in ig["hashtags"])
        lines.append(f"*🏷 Хэштеги*\n{tags}")

    return "\n".join(lines)


def _format_platform_content(platform: str, content_data: dict) -> str:
    """Форматирует материалы для платформы (кроме Instagram — для него _format_ig_view)."""

    def _hashtags(tags: list) -> str:
        return "  ".join(f"#{t.lstrip('#')}" for t in tags) if tags else "—"

    if platform == "threads":
        th = content_data.get("threads", {})
        return "\n\n".join(filter(None, [
            "🧵 *Threads*",
            f"📝 *Пост*\n{th.get('post', '—')}",
        ]))

    if platform == "dzen":
        d = content_data.get("dzen", {})
        return "\n\n".join(filter(None, [
            "📰 *Дзен*",
            f"🔤 *Заголовок*\n{d.get('title', '—')}",
            f"📝 *Статья*\n{d.get('article', '—')}",
            f"📣 *CTA*\n{d.get('cta', '—')}" if d.get("cta") else "",
        ]))

    if platform == "site":
        s = content_data.get("site", {})
        return "\n\n".join(filter(None, [
            "🌐 *Сайт*",
            f"🔤 *Заголовок*\n{s.get('title', '—')}",
            f"📄 *Meta*\n{s.get('meta_description', '—')}",
            f"📝 *Статья*\n{s.get('article', '—')}",
            f"📣 *CTA*\n{s.get('cta', '—')}" if s.get("cta") else "",
        ]))

    return "Платформа не найдена."


def _section_keyboard(platform: str) -> InlineKeyboardMarkup:
    rows = [
        [InlineKeyboardButton(label, callback_data=f"section:{platform}:{key}")]
        for label, key in _PLATFORM_SECTIONS.get(platform, [])
    ]
    # Кнопка генерации — видна сразу на уровне платформы
    if platform in _IMAGE_SIZE:
        rows.append([InlineKeyboardButton(
            "🎨 Сгенерировать изображение",
            callback_data=f"genimg:{platform}:post",
        )])
    if platform == "reels":
        rows.append([InlineKeyboardButton(
            "🎬 Сгенерировать видео (скоро)",
            callback_data="genvid:placeholder",
        )])
    rows.append([InlineKeyboardButton("⬅ Назад", callback_data="back:platforms")])
    return InlineKeyboardMarkup(rows)


def _format_section(platform: str, section: str, data: dict) -> str:
    # Новый формат: per-platform dict
    data_key = _PLATFORM_DATA_KEY.get(platform, platform)
    p = data.get(data_key) if isinstance(data.get(data_key), dict) else {}

    def _hashtags(tags: list) -> str:
        return "  ".join(f"#{t.lstrip('#')}" for t in tags) if tags else "—"

    def _carousel(slides: list) -> str:
        return "\n\n".join(
            f"Слайд {s.get('slide', '?')}: {s.get('text', '—')}"
            for s in slides
        ) if slides else "—"

    def _hooks(hooks: list) -> str:
        return "\n".join(f"{i + 1}. {h}" for i, h in enumerate(hooks)) if hooks else "—"

    if p:
        # Instagram
        if platform == "instagram":
            if section == "post":     return p.get("post", "—")
            if section == "hooks":    return _hooks(p.get("hooks", []))
            if section == "carousel": return _carousel(p.get("carousel", []))
            if section == "caption":  return p.get("caption", "—")
            if section == "cta":      return p.get("cta", "—")
            if section == "hashtags": return _hashtags(p.get("hashtags", []))
        # Reels
        if platform == "reels":
            if section == "script":   return p.get("script", "—")
            if section == "hooks":    return _hooks(p.get("hooks", []))
            if section == "music":    return p.get("music_mood", "—")
        # Telegram
        if platform == "tg":
            if section == "post":     return p.get("post", "—")
            if section == "cta":      return p.get("cta", "—")
        # Дзен
        if platform == "dzen":
            if section == "title":    return p.get("title", "—")
            if section == "post":     return p.get("article", "—")
            if section == "cta":      return p.get("cta", "—")
        # Сайт
        if platform == "site":
            if section == "title":    return p.get("title", "—")
            if section == "meta":     return p.get("meta_description", "—")
            if section == "post":     return p.get("article", "—")
            if section == "cta":      return p.get("cta", "—")
        # Pinterest
        if platform == "pinterest":
            if section == "title":    return p.get("title", "—")
            if section == "caption":  return p.get("description", "—")
            if section == "hashtags": return _hashtags(p.get("hashtags", []))

    # Fallback: старый формат (для кампаний, созданных до обновления)
    if section == "post":     return data.get("post_text", "—")
    if section == "hooks":    return _hooks(data.get("hooks", []))
    if section == "carousel": return _carousel(data.get("carousel", []))
    if section == "caption":  return data.get("caption", "—")
    if section == "cta":      return data.get("cta", "—")
    if section == "hashtags": return _hashtags(data.get("hashtags", []))
    if section == "script":   return data.get("reels_script", "—")
    if section == "visual":   return data.get("visual_idea", "—")
    if section == "music":    return data.get("music_mood", "—")
    return "—"


# ---------------------------------------------------------------------------
# Обработчики команд
# ---------------------------------------------------------------------------

async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not _is_authorized(update):
        await _deny(update)
        return

    text = (
        "*AI Marketing OS*\n\n"
        "/status — текущее состояние системы\n"
        "/next — выполнить следующий шаг\n"
        "/review — рассмотреть идеи\n"
        "/results — внести результаты кампании"
    )
    await update.message.reply_text(text, parse_mode="Markdown")


async def cmd_status(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not _is_authorized(update):
        await _deny(update)
        return

    store = Store(PROJECT)
    status = controller.get_status(store)
    await update.message.reply_text(_format_status(status), parse_mode="Markdown")


async def cmd_next(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not _is_authorized(update):
        await _deny(update)
        return

    store = Store(PROJECT)
    status = controller.get_status(store)

    from engine.workflow import PENDING_PUBLICATION, PENDING_RESULTS

    force_research = status["state"] in (PENDING_PUBLICATION, PENDING_RESULTS)

    if status["requires_user_action"] and not force_research:
        next_cmd = status.get("next_command")
        hint = f"\n\nИспользуйте: /{next_cmd}" if next_cmd else ""
        await update.message.reply_text(
            f"Ожидается действие пользователя.\n\n{status['description']}{hint}",
        )
        return

    msg = await update.message.reply_text("Выполняю следующий шаг...")

    # LLM-вызов выполняется в thread pool, не блокируя event loop
    result = await asyncio.to_thread(controller.step, store, force_research)

    error = result.get("error")
    if error:
        await msg.edit_text(f"Ошибка при выполнении шага:\n{error}")
        return

    action = result.get("action_taken")

    if action == "research":
        ideas_count = result.get("result", {}).get("ideas_count", 0)
        text = (
            f"Research завершён. Найдено идей: *{ideas_count}*\n\n"
            f"Следующий шаг → /review\n"
            f"Рассмотрите идеи и одобрите лучшую."
        )
    elif action == "create":
        content_data = result.get("result", {}).get("data", {})
        context.user_data["last_content"] = content_data
        context.bot_data["last_content"]  = content_data
        spec_id = content_data.get("_spec_id")
        store2  = Store(PROJECT)
        specs   = [s for s in store2.load_campaign_specs() if s.get("id") == spec_id] if spec_id else []
        spec    = specs[0] if specs else {}
        ig_fmt  = spec.get("instagram_format", "carousel")
        pub_statuses = spec.get("pub_statuses", {})
        ig_published = pub_statuses.get("instagram") == "published"
        await msg.edit_text(
            _format_campaign_dashboard(spec),
            parse_mode="Markdown",
            reply_markup=_campaign_dashboard_keyboard(ig_fmt, ig_published),
        )
        return
    else:
        text = result.get("description", "Шаг выполнен.")

    await msg.edit_text(text, parse_mode="Markdown")


async def cmd_review(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not _is_authorized(update):
        await _deny(update)
        return

    store = Store(PROJECT)
    ideas = controller.get_pending_ideas(store)

    if not ideas:
        await update.message.reply_text(
            "Нет идей для рассмотрения.\n\nЗапустите /next для генерации новых идей."
        )
        return

    context.user_data["review_ideas"] = ideas
    context.user_data["review_index"] = 0
    context.user_data["review_decisions"] = {}

    text = _format_idea(ideas[0], 1, len(ideas))
    await update.message.reply_text(text, reply_markup=_review_keyboard())


# ---------------------------------------------------------------------------
# Обработчик inline-кнопок Review
# ---------------------------------------------------------------------------

async def callback_review(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if not _is_authorized(update):
        await _deny(update)
        return

    await query.answer()

    decision = query.data.split(":")[1]  # "approve" | "reject" | "skip"
    ideas = context.user_data.get("review_ideas", [])
    idx = context.user_data.get("review_index", 0)

    if idx >= len(ideas):
        await query.edit_message_text("Review-сессия уже завершена.")
        return

    idea = ideas[idx]
    store = Store(PROJECT)
    controller.decide_idea(store, idea, decision)

    decisions: dict = context.user_data.setdefault("review_decisions", {})
    decisions[idx] = decision

    label = {
        "approve": "✅ Одобрена",
        "reject":  "❌ Отклонена",
        "skip":    "⏭ Пропущена",
    }[decision]
    await query.edit_message_text(
        f"{label}: *{idea.get('title', '—')}*",
        parse_mode="Markdown",
    )

    next_idx = idx + 1
    context.user_data["review_index"] = next_idx

    if next_idx >= len(ideas):
        approved = sum(1 for d in decisions.values() if d == "approve")
        rejected = sum(1 for d in decisions.values() if d == "reject")
        skipped  = sum(1 for d in decisions.values() if d == "skip")

        summary = (
            f"Review завершён.\n\n"
            f"✅ Одобрено: {approved}\n"
            f"❌ Отклонено: {rejected}\n"
            f"⏭ Пропущено: {skipped}"
        )

        if approved:
            await query.message.reply_text(
                summary + "\n\nВыберите формат для Instagram:",
                reply_markup=_instagram_format_keyboard(),
            )
        else:
            await query.message.reply_text(summary)
    else:
        next_idea = ideas[next_idx]
        text = _format_idea(next_idea, next_idx + 1, len(ideas))
        await query.message.reply_text(
            text, reply_markup=_review_keyboard()
        )


# ---------------------------------------------------------------------------
# Обработчик inline-кнопок платформ
# ---------------------------------------------------------------------------

async def callback_instagram_format(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Пользователь выбрал формат Instagram.
    Сохраняем выбор → автоматически запускаем Create → автопубликация → дашборд.
    """
    query = update.callback_query
    if not _is_authorized(update):
        await _deny(update)
        return
    await query.answer()

    fmt = query.data.split(":")[1]  # "carousel" | "reels"
    fmt_label = "🎠 Карусель" if fmt == "carousel" else "🎬 Reels"

    store = Store(PROJECT)
    spec = store.next_spec_for_create()
    if spec is None:
        await query.edit_message_text(
            "Не найдена кампания для создания. Попробуйте пройти /review снова."
        )
        return

    store.save_instagram_format(spec["id"], fmt)

    await query.edit_message_text(
        f"Формат Instagram: {fmt_label}\n\n"
        f"⏳ Создаю кампанию для всех площадок...\n"
        f"Обычно занимает 2–3 минуты."
    )

    result = await asyncio.to_thread(controller.step, store)

    if result.get("error"):
        await query.edit_message_text(f"Ошибка создания кампании:\n{result['error']}")
        return

    content_data = result.get("result", {}).get("data", {})
    context.user_data["last_content"] = content_data
    context.bot_data["last_content"]  = content_data

    # Загружаем spec и показываем дашборд — без автопубликации
    spec_id = content_data.get("_spec_id", spec["id"])
    updated_specs = [s for s in store.load_campaign_specs() if s.get("id") == spec_id]
    updated_spec  = updated_specs[0] if updated_specs else {}

    await query.edit_message_text(
        _format_campaign_dashboard(updated_spec),
        parse_mode="Markdown",
        reply_markup=_campaign_dashboard_keyboard(fmt, ig_published=False, launched=False),
    )


async def callback_view_platform(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Показывает материалы выбранной платформы (telegram / pinterest / dzen / site)."""
    query = update.callback_query
    if not _is_authorized(update):
        await _deny(update)
        return
    await query.answer()

    platform = query.data.split(":")[1]

    data = _load_content_data(context)
    if not data:
        store = Store(PROJECT)
        spec  = store.get_latest_content_spec()
        if spec:
            data = spec.get("content_data")
            if data:
                context.user_data["last_content"] = data
                context.bot_data["last_content"]  = data

    if not data:
        await query.edit_message_text("Данные кампании не найдены. Запустите /review.")
        return

    content = _truncate(_format_platform_content(platform, data))
    await query.edit_message_text(
        content,
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup([[
            InlineKeyboardButton("⬅ Назад к кампании", callback_data="ig:dashboard"),
        ]]),
    )


async def callback_campaign_action(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Запуск кампании: автопубликация на всех площадках кроме Instagram."""
    query = update.callback_query
    if not _is_authorized(update):
        await _deny(update)
        return
    await query.answer()

    store = Store(PROJECT)
    spec  = store.get_latest_content_spec()
    if spec is None:
        await query.edit_message_text("Активная кампания не найдена.")
        return

    content_data = spec.get("content_data") or context.user_data.get("last_content") or {}
    ig_fmt = spec.get("instagram_format", "carousel")

    await query.edit_message_text("🚀 Запускаю публикацию на площадках...")

    from engine import publisher
    pub_results   = await publisher.run_auto_publish(content_data, context.bot, ALLOWED_CHAT_ID)
    flat_statuses = {p: d["status"] for p, d in pub_results.items()}

    spec_id = spec.get("id", "")
    store.save_pub_statuses(spec_id, flat_statuses)

    # Перезагружаем spec с актуальными данными
    updated_specs = [s for s in store.load_campaign_specs() if s.get("id") == spec_id]
    updated_spec  = updated_specs[0] if updated_specs else spec

    ig_published = flat_statuses.get("instagram") == "published"
    await query.edit_message_text(
        _format_campaign_dashboard(updated_spec),
        parse_mode="Markdown",
        reply_markup=_campaign_dashboard_keyboard(ig_fmt, ig_published, launched=True, pub_statuses=flat_statuses),
    )


async def callback_ig_action(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Маршрутизатор для действий с Instagram: ig:view / ig:confirm.
    """
    query = update.callback_query
    if not _is_authorized(update):
        await _deny(update)
        return
    await query.answer()

    action = query.data.split(":")[1]  # "view" | "confirm"

    store = Store(PROJECT)
    spec  = store.get_latest_content_spec()
    if spec is None:
        await query.edit_message_text("Активная кампания не найдена. Запустите /review.")
        return

    if action == "view":
        ig_fmt = spec.get("instagram_format", "carousel")
        content = _truncate(_format_ig_view(spec))
        carousel_images = spec.get("carousel_images", {})
        slides = spec.get("content_data", {}).get("instagram", {}).get("carousel", [])
        n_slides = len(slides)

        if ig_fmt == "carousel":
            gen_btn = InlineKeyboardButton(
                f"🎨 Сгенерировать изображения ({n_slides})",
                callback_data="genimg:instagram:carousel",
            )
        else:
            gen_btn = InlineKeyboardButton(
                "🎬 Сгенерировать видео (скоро)",
                callback_data="genvid:placeholder",
            )

        await query.edit_message_text(
            content,
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([
                [gen_btn],
                [InlineKeyboardButton("⬅ Назад к кампании", callback_data="ig:dashboard")],
            ]),
        )

    elif action == "confirm":
        spec_id = spec.get("id", "")
        store.save_pub_status(spec_id, "instagram", "published")

        # Перезагружаем и показываем обновлённый дашборд
        updated_specs = [s for s in store.load_campaign_specs() if s.get("id") == spec_id]
        updated_spec  = updated_specs[0] if updated_specs else spec
        updated_spec.setdefault("pub_statuses", {})["instagram"] = "published"

        ig_fmt       = updated_spec.get("instagram_format", "carousel")
        pub_statuses = updated_spec.get("pub_statuses", {})
        await query.edit_message_text(
            _format_campaign_dashboard(updated_spec),
            parse_mode="Markdown",
            reply_markup=_campaign_dashboard_keyboard(ig_fmt, ig_published=True, launched=True, pub_statuses=pub_statuses),
        )

    elif action == "dashboard":
        ig_fmt       = spec.get("instagram_format", "carousel")
        pub_statuses = spec.get("pub_statuses", {})
        ig_published = pub_statuses.get("instagram") == "published"
        launched     = bool(pub_statuses)
        await query.edit_message_text(
            _format_campaign_dashboard(spec),
            parse_mode="Markdown",
            reply_markup=_campaign_dashboard_keyboard(ig_fmt, ig_published, launched, pub_statuses),
        )


async def callback_platform(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if not _is_authorized(update):
        await _deny(update)
        return

    await query.answer()

    platform = query.data.split(":")[1]
    label = _PLATFORM_LABELS.get(platform, platform)

    await query.edit_message_text(
        f"{label}\n\nВыберите, что открыть:",
        reply_markup=_section_keyboard(platform),
    )


# ---------------------------------------------------------------------------
# Обработчики разделов и навигации
# ---------------------------------------------------------------------------

def _section_content_keyboard(platform: str, section: str) -> InlineKeyboardMarkup:
    """Клавиатура под разделом: кнопка генерации (если применимо) + Назад."""
    buttons = []
    if (platform, section) in _IMAGE_GEN_SECTIONS:
        buttons.append(InlineKeyboardButton(
            "🎨 Сгенерировать изображение",
            callback_data=f"genimg:{platform}:{section}",
        ))
    elif platform == "reels" and section == "script":
        buttons.append(InlineKeyboardButton(
            "🎬 Сгенерировать видео (скоро)",
            callback_data="genvid:placeholder",
        ))
    buttons.append(InlineKeyboardButton("⬅ Назад", callback_data=f"platform:{platform}"))
    return InlineKeyboardMarkup([[b] for b in buttons])


async def callback_section(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if not _is_authorized(update):
        await _deny(update)
        return

    await query.answer()

    _, platform, section = query.data.split(":")
    data = context.user_data.get("last_content") or context.bot_data.get("last_content")

    # Если данных нет в памяти — загружаем из последнего Campaign Spec
    if not data:
        store = Store(PROJECT)
        spec = store.get_latest_content_spec()
        if spec:
            data = spec.get("content_data")
            if data:
                context.user_data["last_content"] = data
                context.bot_data["last_content"] = data

    if not data:
        await query.answer("Данные кампании не найдены. Запустите /next.", show_alert=True)
        return

    content = _truncate(_format_section(platform, section, data))
    await query.edit_message_text(
        content,
        reply_markup=_section_content_keyboard(platform, section),
    )


async def callback_back(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if not _is_authorized(update):
        await _deny(update)
        return

    await query.answer()
    await query.edit_message_text(
        "✅ Кампания готова.\n\nВыберите платформу, чтобы открыть материал:",
        reply_markup=_platform_keyboard(),
    )


def _load_content_data(context: ContextTypes.DEFAULT_TYPE) -> dict | None:
    """Возвращает данные кампании из памяти или последнего Campaign Spec."""
    data = context.user_data.get("last_content") or context.bot_data.get("last_content")
    if not data:
        store = Store(PROJECT)
        spec = store.get_latest_content_spec()
        if spec:
            data = spec.get("content_data")
            if data:
                context.user_data["last_content"] = data
                context.bot_data["last_content"] = data
    return data


async def _handle_single_image(
    query, context: ContextTypes.DEFAULT_TYPE, platform: str, section: str
) -> None:
    """Генерация одного изображения (не карусель)."""
    data = _load_content_data(context)
    if not data:
        await query.edit_message_text("Данные кампании не найдены. Запустите /next.")
        return

    visual_idea = data.get("visual_idea", "")
    if not visual_idea:
        await query.edit_message_text("Нет описания визуала для генерации.")
        return

    size = _IMAGE_SIZE.get(platform, "1:1")
    platform_label = _PLATFORM_LABELS.get(platform, platform)

    await query.edit_message_text(
        f"🎨 Генерирую изображение для {platform_label}...\n⏳ Обычно занимает 2–3 минуты."
    )

    try:
        from engine import image_provider
        url = await asyncio.to_thread(image_provider.generate_image, visual_idea, size)

        store = Store(PROJECT)
        suffix = Path(url.split("?")[0]).suffix or ".jpg"
        spec_id = data.get("_spec_id", "unknown")
        dest = store.campaigns_dir() / f"{spec_id}_{platform}_image{suffix}"
        await asyncio.to_thread(image_provider.download_image, url, dest)

        with open(dest, "rb") as img_file:
            await query.message.reply_photo(
                photo=img_file,
                caption=f"🖼 {platform_label}\n\nОпубликуйте этот материал, затем введите /results",
            )

        await query.edit_message_text(
            f"✅ Изображение для {platform_label} готово.",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("⬅ Назад", callback_data=f"platform:{platform}"),
            ]]),
        )

    except Exception as exc:
        logger.error(f"Ошибка генерации изображения: {exc}")
        await query.edit_message_text(
            f"Ошибка генерации: {exc}\n\nПопробуйте ещё раз.",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("⬅ Назад", callback_data=f"platform:{platform}"),
            ]]),
        )


async def _carousel_confirm(query, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Показывает диалог подтверждения перед рендером карусели."""
    data = _load_content_data(context)
    if not data:
        await query.edit_message_text("Данные кампании не найдены. Запустите /next.")
        return

    instagram_data = data.get("instagram", {})
    slides = instagram_data.get("carousel", [])
    # Жёсткое ограничение: не более 4 слайдов
    if len(slides) > 4:
        slides = slides[:4]
    n = len(slides)

    if n == 0:
        await query.edit_message_text("Карусель не содержит слайдов.")
        return

    context.user_data["carousel_pending"] = {
        "slides":       slides,
        "spec_id":      data.get("_spec_id", "unknown"),
        "content_data": data,
    }

    roles = " → ".join(
        _ROLE_LABEL.get(s.get("role", ""), f"Слайд {s.get('slide', i+1)}")
        for i, s in enumerate(slides)
    )
    await query.edit_message_text(
        f"🎨 Будет создано *{n}* слайда карусели:\n_{roles}_\n\n"
        f"Рендер локальный — мгновенно, без расхода Kie.ai.\n\n"
        f"Продолжить?",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup([[
            InlineKeyboardButton("✅ Создать", callback_data="genimg_go:instagram:carousel"),
            InlineKeyboardButton("❌ Отмена",  callback_data="platform:instagram"),
        ]]),
    )


async def _run_carousel_generation(
    query, context: ContextTypes.DEFAULT_TYPE, is_retry: bool = False
) -> None:
    """Рендерит карусель локально через Pillow (без Kie.ai)."""
    pending = context.user_data.get("carousel_pending")
    if not pending:
        await query.edit_message_text("Данные сессии устарели. Выберите карусель заново.")
        return

    slides: list[dict]  = pending["slides"]
    spec_id: str        = pending["spec_id"]
    content_data: dict  = pending.get("content_data", {})
    store               = Store(PROJECT)
    output_dir          = store.campaigns_dir()

    await query.edit_message_text("🎨 Собираю карусель...")

    from engine import carousel_renderer
    await asyncio.to_thread(carousel_renderer.ensure_fonts)

    # Определяем источник фото: tips-кампания использует assets/photos_tips/
    specs = store.load_campaign_specs()
    spec  = next((s for s in specs if s.get("id") == spec_id), {})
    use_tips = bool(spec.get("idea", {}).get("tip_source_url", ""))

    try:
        saved_images = await asyncio.to_thread(
            carousel_renderer.render_photo_carousel, slides, output_dir, spec_id, use_tips
        )
    except (FileNotFoundError, ValueError) as ph_err:
        logger.warning(f"[Bot] Фотобиблиотека недоступна ({ph_err}). Fallback: плоский фон.")
        try:
            saved_images = await asyncio.to_thread(
                carousel_renderer.render_carousel, slides, output_dir, spec_id
            )
        except Exception as e:
            logger.error(f"Ошибка рендера карусели: {e}", exc_info=True)
            await query.edit_message_text(f"❌ Ошибка при создании карусели:\n{e}")
            return
    except Exception as e:
        logger.error(f"Ошибка рендера карусели: {e}", exc_info=True)
        await query.edit_message_text(f"❌ Ошибка при создании карусели:\n{e}")
        return

    logger.info(f"[Bot] saved_images={saved_images}")

    # Отправляем PNG-слайды (текст уже на изображении — подпись не нужна)
    ig = content_data.get("instagram", {})
    for i, slide_obj in enumerate(slides):
        slide_num = slide_obj.get("slide", i + 1)
        img_path  = saved_images.get(str(slide_num))
        path_exists = Path(img_path).exists() if img_path else False
        logger.info(f"[Bot] Слайд {slide_num}: img_path={img_path}, exists={path_exists}")
        if img_path and path_exists:
            with open(img_path, "rb") as f:
                await query.message.reply_photo(photo=f)
        else:
            role = _ROLE_LABEL.get(slide_obj.get("role", ""), f"Слайд {slide_num}")
            await query.message.reply_text(f"❌ Слайд {slide_num} ({role}) не создан\npath={img_path}")

    # Подпись + CTA + хэштеги — отдельным сообщением для копирования в Instagram
    footer_parts = []
    if ig.get("caption"):
        footer_parts.append(f"📝 *Подпись*\n{ig['caption']}")
    if ig.get("cta"):
        footer_parts.append(f"📣 *CTA*\n{ig['cta']}")
    if ig.get("hashtags"):
        tags = "  ".join(f"#{t.lstrip('#')}" for t in ig["hashtags"])
        footer_parts.append(f"🏷 {tags}")
    if footer_parts:
        await query.message.reply_text("\n\n".join(footer_parts), parse_mode="Markdown")

    # Сохраняем пути в Campaign Specification
    if saved_images:
        store.save_carousel_images(spec_id, saved_images)

    context.user_data.pop("carousel_pending", None)
    n = len(slides)
    await query.edit_message_text(
        f"✅ Карусель готова — {n} слайдов.",
        reply_markup=InlineKeyboardMarkup([[
            InlineKeyboardButton("⬅ Назад к кампании", callback_data="ig:dashboard"),
        ]]),
    )


async def callback_generate_image(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Точка входа: одно изображение или карусель."""
    query = update.callback_query
    if not _is_authorized(update):
        await _deny(update)
        return

    await query.answer()

    parts = query.data.split(":")  # genimg:platform:section
    platform = parts[1] if len(parts) > 1 else "instagram"
    section  = parts[2] if len(parts) > 2 else "post"

    if platform == "instagram" and section == "carousel":
        await _carousel_confirm(query, context)
    else:
        await _handle_single_image(query, context, platform, section)


async def callback_carousel_go(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Подтверждение получено — запускаем генерацию всей карусели."""
    query = update.callback_query
    if not _is_authorized(update):
        await _deny(update)
        return

    await query.answer()
    await _run_carousel_generation(query, context, is_retry=False)


async def callback_carousel_retry(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Догенерация только упавших слайдов."""
    query = update.callback_query
    if not _is_authorized(update):
        await _deny(update)
        return

    await query.answer()

    pending = context.user_data.get("carousel_pending")
    if not pending or not pending.get("retry_indices"):
        await query.edit_message_text("Нет данных для повторной генерации. Начните заново.")
        return

    n_retry = len(pending["retry_indices"])
    n_total = len(pending.get("slides", pending.get("prompts", [])))

    await query.edit_message_text(
        f"Будет догенерировано *{n_retry}* из *{n_total}* изображений.\n"
        f"Это потребует *{n_retry}* генераций Kie.ai.\n\n"
        f"Продолжить?",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup([[
            InlineKeyboardButton("✅ Продолжить", callback_data="genimg_go:instagram:carousel"),
            InlineKeyboardButton("❌ Отмена",     callback_data="platform:instagram"),
        ]]),
    )


async def callback_generate_video(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Заглушка: генерация видео будет добавлена в следующей версии."""
    query = update.callback_query
    await query.answer(
        "Генерация видео будет доступна в следующей версии.",
        show_alert=True,
    )


# ---------------------------------------------------------------------------
# Results: пошаговый ввод результатов кампании
# ---------------------------------------------------------------------------

# Состояния ConversationHandler
_RESULTS_SELECT, _RESULTS_FIELD = range(2)

# Поля для ввода: (ключ в dict, название, подсказка)
_RESULTS_FIELDS: list[tuple[str, str, str]] = [
    ("views",    "Просмотры",   "Введите просмотры:"),
    ("likes",    "Лайки",       "Введите лайки:"),
    ("comments", "Комментарии", "Введите комментарии:"),
    ("saves",    "Сохранения",  "Введите сохранения:"),
    ("clicks",   "Переходы",    "Введите переходы по ссылке:"),
    ("orders",   "Заявки",      "Введите заявки (обращения):"),
    ("notes",    "Заметки",     "Добавьте заметки (наблюдения, что сработало):"),
]
_SKIP_HINT = "Введите число или — чтобы пропустить."
_NOTES_SKIP_HINT = "Введите текст или — чтобы пропустить."


async def cmd_results_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if not _is_authorized(update):
        await _deny(update)
        return ConversationHandler.END

    store = Store(PROJECT)
    campaigns = controller.get_published_campaigns(store)

    if not campaigns:
        await update.message.reply_text(
            "Нет опубликованных кампаний.\n\n"
            "Сначала подтвердите публикацию через /publish или CLI."
        )
        return ConversationHandler.END

    keyboard = [
        [InlineKeyboardButton(
            s["source"].get("idea_title", s["id"]),
            callback_data=f"rsel:{s['id']}",
        )]
        for s in campaigns
    ]
    keyboard.append([InlineKeyboardButton("Отмена", callback_data="rsel:cancel")])

    await update.message.reply_text(
        "Выберите кампанию для внесения результатов:",
        reply_markup=InlineKeyboardMarkup(keyboard),
    )
    return _RESULTS_SELECT


async def results_campaign_selected(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()

    value = query.data.split(":", 1)[1]
    if value == "cancel":
        await query.edit_message_text("Отменено.")
        return ConversationHandler.END

    context.user_data["rspec_id"] = value
    context.user_data["rdraft"] = {}
    context.user_data["rfield_idx"] = 0

    _, _, prompt = _RESULTS_FIELDS[0]
    total = len(_RESULTS_FIELDS)
    await query.edit_message_text(f"[1/{total}] {prompt}\n{_SKIP_HINT}")
    return _RESULTS_FIELD


async def results_collect_field(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if not _is_authorized(update):
        await _deny(update)
        return ConversationHandler.END

    idx: int = context.user_data.get("rfield_idx", 0)
    key, label, _ = _RESULTS_FIELDS[idx]
    raw = update.message.text.strip()

    if raw == "—" or raw == "-":
        value = None
    elif key == "notes":
        value = raw
    else:
        try:
            value = max(0, int(raw))
        except ValueError:
            await update.message.reply_text(f"Нужно число. {_SKIP_HINT}")
            return _RESULTS_FIELD

    context.user_data["rdraft"][key] = value

    next_idx = idx + 1
    context.user_data["rfield_idx"] = next_idx
    total = len(_RESULTS_FIELDS)

    if next_idx >= total:
        # Все поля собраны — сохраняем
        draft: dict = context.user_data["rdraft"]
        spec_id: str = context.user_data["rspec_id"]
        store = Store(PROJECT)
        controller.save_campaign_results(store, spec_id, draft)

        lines = ["✅ Результаты сохранены.\n"]
        for fkey, flabel, _ in _RESULTS_FIELDS:
            val = draft.get(fkey)
            if val is not None:
                lines.append(f"{flabel}: {val}")
        lines.append("\nКампания переведена в статус results_collected.\nГотова к этапу Insights.")
        await update.message.reply_text("\n".join(lines))
        return ConversationHandler.END

    next_key, _, next_prompt = _RESULTS_FIELDS[next_idx]
    hint = _NOTES_SKIP_HINT if next_key == "notes" else _SKIP_HINT
    await update.message.reply_text(f"[{next_idx + 1}/{total}] {next_prompt}\n{hint}")
    return _RESULTS_FIELD


async def results_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    await update.message.reply_text("Внесение результатов отменено.")
    return ConversationHandler.END


def _build_results_conversation() -> ConversationHandler:
    return ConversationHandler(
        entry_points=[CommandHandler("results", cmd_results_start)],
        states={
            _RESULTS_SELECT: [CallbackQueryHandler(results_campaign_selected, pattern=r"^rsel:")],
            _RESULTS_FIELD:  [MessageHandler(filters.TEXT & ~filters.COMMAND, results_collect_field)],
        },
        fallbacks=[CommandHandler("cancel", results_cancel)],
        per_message=False,
    )


# ---------------------------------------------------------------------------
# Scheduler: ежедневная проверка расписания
# ---------------------------------------------------------------------------

# Защита от параллельного запуска задач
_sched_research_running = False
_sched_tips_running = False


async def _run_scheduled_research(context) -> None:
    """Плановый Research каждые 2 дня — новые идеи не зависят от текущего Workflow."""
    global _sched_research_running
    if _sched_research_running:
        logger.warning("[Scheduler] Research уже выполняется, пропуск")
        return
    _sched_research_running = True
    store = Store(PROJECT)
    try:
        from engine import research as _research
        logger.info("[Scheduler] Запуск планового Research (каждые 2 дня)")
        _, data = await asyncio.to_thread(_research.run, store)
        sched_state.mark_research_done(store, success=True)

        if data is None:
            await context.bot.send_message(
                chat_id=ALLOWED_CHAT_ID,
                text="⏰ Плановый Research: ошибка парсинга — см. logs/bot_err.log",
            )
            return

        ideas = data.get("ideas", [])
        n = len(ideas)
        titles = "\n".join(f"• {i.get('title', '—')}" for i in ideas[:4])
        await context.bot.send_message(
            chat_id=ALLOWED_CHAT_ID,
            text=(
                f"⏰ Плановый Research завершён.\n"
                f"Появилось *{n}* новых идей:\n\n{titles}\n\n"
                f"Используй /review чтобы выбрать лучшие."
            ),
            parse_mode="Markdown",
        )
    except Exception as e:
        logger.error(f"[Scheduler] Ошибка планового Research: {e}", exc_info=True)
        sched_state.mark_research_done(store, success=False)
        try:
            await context.bot.send_message(
                chat_id=ALLOWED_CHAT_ID,
                text=f"⚠️ Плановый Research завершился с ошибкой:\n{e}",
            )
        except Exception:
            pass
    finally:
        _sched_research_running = False


async def _run_scheduled_tips(context) -> None:
    """Еженедельный Tips Research — практические советы по уборке."""
    global _sched_tips_running
    if _sched_tips_running:
        logger.warning("[Scheduler] Tips Research уже выполняется, пропуск")
        return
    _sched_tips_running = True
    store = Store(PROJECT)
    try:
        logger.info("[Scheduler] Запуск еженедельного Tips Research")
        count, tips = await asyncio.to_thread(tips_research.run, store)
        sched_state.mark_tips_done(store, success=True)

        if count == 0:
            await context.bot.send_message(
                chat_id=ALLOWED_CHAT_ID,
                text="⏰ Еженедельные советы: не удалось найти подтверждённые источники. Попробую снова на следующей неделе.",
            )
            return

        titles = "\n".join(f"• {t.get('title', '—')}" for t in tips)
        await context.bot.send_message(
            chat_id=ALLOWED_CHAT_ID,
            text=(
                f"📚 Еженедельные советы готовы — *{count}* шт.:\n\n{titles}\n\n"
                f"Используй /tips чтобы рассмотреть и одобрить."
            ),
            parse_mode="Markdown",
        )
    except Exception as e:
        logger.error(f"[Scheduler] Ошибка Tips Research: {e}", exc_info=True)
        sched_state.mark_tips_done(store, success=False)
        try:
            await context.bot.send_message(
                chat_id=ALLOWED_CHAT_ID,
                text=f"⚠️ Еженедельные советы завершились с ошибкой:\n{e}",
            )
        except Exception:
            pass
    finally:
        _sched_tips_running = False


async def scheduled_step(context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Ежедневная проверка расписания (SCHEDULER_HOUR UTC).
    Независимо проверяет два таймера:
      — Research каждые 2 дня
      — Tips Research каждые 7 дней
    Ошибка одной задачи не останавливает другую.
    """
    store = Store(PROJECT)

    # 1. Проверяем плановый Research (каждые 2 дня)
    if sched_state.research_due(store, interval_days=2):
        asyncio.create_task(_run_scheduled_research(context))
    else:
        logger.info("[Scheduler] Research: срок не наступил, пропуск")

    # 2. Проверяем еженедельные Tips
    if sched_state.tips_due(store, interval_days=7):
        asyncio.create_task(_run_scheduled_tips(context))
    else:
        logger.info("[Scheduler] Tips: срок не наступил, пропуск")


# ---------------------------------------------------------------------------
# /tips — просмотр и одобрение практических советов
# ---------------------------------------------------------------------------

_TOPIC_EMOJI = {
    "удаление пятен":       "🧹",
    "уход за поверхностями":"🪟",
    "бытовая химия":        "🧴",
    "запахи":               "🌿",
    "ошибки":               "⚠️",
    "мягкая мебель":        "🛋",
}


def _tip_text(tip: dict, idx: int, total: int) -> str:
    topic = tip.get("topic", "")
    emoji = _TOPIC_EMOJI.get(topic, "💡")
    source = tip.get("source_name", "—")
    url = tip.get("source_url", "")
    source_line = f"[{source}]({url})" if url else source
    safety = tip.get("safety_notes", "")
    lines = [
        f"{emoji} *{tip.get('title', '—')}* ({idx}/{total})",
        f"\n_{tip.get('verified_fact', '—')}_",
        f"\n📎 Источник: {source_line}",
        f"\n🎯 Угол подачи: {tip.get('content_angle', '—')}",
    ]
    if safety:
        lines.append(f"\n⚠️ {safety}")
    return "\n".join(lines)


def _tips_keyboard(tip_title: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[
        InlineKeyboardButton("✅ Одобрить", callback_data=f"tip:approve:{tip_title[:40]}"),
        InlineKeyboardButton("❌ Отклонить", callback_data=f"tip:reject:{tip_title[:40]}"),
        InlineKeyboardButton("⏭ Пропустить", callback_data=f"tip:skip:{tip_title[:40]}"),
    ]])


async def command_tips(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not _is_authorized(update):
        await _deny(update)
        return
    store = Store(PROJECT)
    pending = store.get_pending_tips()
    if not pending:
        await update.message.reply_text(
            "📭 Нет советов на рассмотрении.\n\n"
            "Еженедельные советы появляются автоматически раз в 7 дней.",
        )
        return
    tip = pending[0]
    total = len(pending)
    await update.message.reply_text(
        _tip_text(tip, 1, total),
        parse_mode="Markdown",
        reply_markup=_tips_keyboard(tip.get("title", "")),
        disable_web_page_preview=True,
    )


async def callback_tip_action(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if not _is_authorized(update):
        await _deny(update)
        return
    await query.answer()

    parts = query.data.split(":", 2)  # tip:action:title_prefix
    if len(parts) < 3:
        return
    _, action, title_prefix = parts

    store = Store(PROJECT)
    pending = store.get_pending_tips()

    # Находим совет по префиксу title
    tip = next((t for t in pending if t.get("title", "")[:40] == title_prefix), None)
    if not tip:
        await query.edit_message_text("Совет не найден — возможно уже обработан.")
        return

    tip_title = tip.get("title", "—")

    if action == "approve":
        store.update_tip_status(tip_title, "approved")
        # Одобренный совет добавляем в idea_bank как обычную идею для Create
        from datetime import datetime as _dt
        bank_idea = {
            "session_date": _dt.now().strftime("%Y-%m-%d %H:%M"),
            "funnel_stage": "тёплая",
            "title": tip_title,
            "source": tip.get("source_name", "—"),
            "trigger": tip.get("verified_fact", "—"),
            "potential": "Средний",
            "potential_rationale": f"Практический совет с верифицированным источником: {tip.get('source_name', '—')}",
            "adaptation": tip.get("content_angle", "—"),
            "status": "approved",
            "approved_date": _dt.now().strftime("%Y-%m-%d"),
            "tip_source_url": tip.get("source_url", ""),
            "safety_notes": tip.get("safety_notes", ""),
        }
        bank = store.load_bank_ideas()
        bank.append(bank_idea)
        store.save_bank_ideas(bank)
        msg = f"✅ Совет одобрен и добавлен в Банк идей:\n*{tip_title}*"
    elif action == "reject":
        store.update_tip_status(tip_title, "rejected")
        msg = f"❌ Совет отклонён:\n*{tip_title}*"
    else:
        msg = f"⏭ Пропущен:\n*{tip_title}*"

    # Показываем следующий совет
    remaining = store.get_pending_tips()
    if remaining:
        next_tip = remaining[0]
        total = len(remaining)
        await query.edit_message_text(
            msg + f"\n\n—\n\n" + _tip_text(next_tip, 1, total),
            parse_mode="Markdown",
            reply_markup=_tips_keyboard(next_tip.get("title", "")),
            disable_web_page_preview=True,
        )
    else:
        await query.edit_message_text(
            msg + "\n\n✅ Все советы рассмотрены.",
            parse_mode="Markdown",
        )


# ---------------------------------------------------------------------------
# Запуск
# ---------------------------------------------------------------------------

def main() -> None:
    if not BOT_TOKEN:
        raise EnvironmentError("TELEGRAM_BOT_TOKEN не найден в .env")
    if not ALLOWED_CHAT_ID:
        raise EnvironmentError("TELEGRAM_CHAT_ID не найден в .env")

    app = Application.builder().token(BOT_TOKEN).build()

    app.add_handler(_build_results_conversation())  # ConversationHandler первым
    app.add_handler(CommandHandler("start",  cmd_start))
    app.add_handler(CommandHandler("status", cmd_status))
    app.add_handler(CommandHandler("next",   cmd_next))
    app.add_handler(CommandHandler("review", cmd_review))
    app.add_handler(CommandHandler("tips",   command_tips))
    app.add_handler(CallbackQueryHandler(callback_tip_action, pattern=r"^tip:"))
    app.add_handler(CallbackQueryHandler(callback_review,           pattern=r"^review:"))
    app.add_handler(CallbackQueryHandler(callback_instagram_format, pattern=r"^igformat:"))
    app.add_handler(CallbackQueryHandler(callback_campaign_action,  pattern=r"^campaign:"))
    app.add_handler(CallbackQueryHandler(callback_view_platform,    pattern=r"^view:"))
    app.add_handler(CallbackQueryHandler(callback_ig_action,        pattern=r"^ig:"))
    app.add_handler(CallbackQueryHandler(callback_platform,         pattern=r"^platform:"))
    app.add_handler(CallbackQueryHandler(callback_section,          pattern=r"^section:"))
    app.add_handler(CallbackQueryHandler(callback_back,             pattern=r"^back:"))
    app.add_handler(CallbackQueryHandler(callback_generate_image,   pattern=r"^genimg:"))
    app.add_handler(CallbackQueryHandler(callback_carousel_go,      pattern=r"^genimg_go:"))
    app.add_handler(CallbackQueryHandler(callback_carousel_retry,   pattern=r"^genimg_retry:"))
    app.add_handler(CallbackQueryHandler(callback_generate_video,   pattern=r"^genvid:"))

    import datetime
    if app.job_queue:
        app.job_queue.run_daily(
            scheduled_step,
            time=datetime.time(hour=SCHEDULER_HOUR, minute=0, tzinfo=datetime.timezone.utc),
        )
        logger.info(f"Scheduler: ежедневный запуск в {SCHEDULER_HOUR:02d}:00 UTC")
    else:
        logger.warning("JobQueue недоступен — scheduler отключён. Установите: pip install 'python-telegram-bot[job-queue]'")

    logger.info(f"Бот запущен | проект: {PROJECT} | chat_id: {ALLOWED_CHAT_ID}")
    app.run_polling(allowed_updates=Update.ALL_TYPES, drop_pending_updates=True)


if __name__ == "__main__":
    main()
