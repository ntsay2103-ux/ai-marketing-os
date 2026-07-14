"""
Tips Research — еженедельная генерация практических советов по уборке.

Каждый совет ОБЯЗАН иметь проверяемый источник.
AI не придумывает факты — только находит и структурирует.
Результат сохраняется в data/{project}/tips_bank.json (отдельно от idea_bank).
"""

import json
import logging
from datetime import datetime
from pathlib import Path
from engine.store import Store
from engine import llm_client
from engine.context import build_system_message, load_prompt

logger = logging.getLogger(__name__)

TIPS_PROMPT = """
Найди ровно 4 практических совета по профессиональному клинингу и уходу за домом.

КРИТИЧЕСКИ ВАЖНО:
— Каждый совет ОБЯЗАН быть основан на реальном источнике, который ты можешь назвать.
— Не придумывай факты. Не используй общеизвестные советы без источника.
— Если достоверного источника нет — не включай совет.
— Если нашёл меньше 4 надёжных советов — верни только те, что нашёл.

Приоритетные источники:
— Официальные сайты производителей бытовой химии (Grass, Svarog, Cif, Mr. Muscle, Domestos и др.)
— Официальные инструкции производителей поверхностей, напольных покрытий, мебели
— Профессиональные стандарты (IICRC, ISSA)
— Проверенные редакционные ресурсы (потребительские организации, профессиональные клининговые ассоциации)

НЕ использовать как единственное подтверждение:
— Анонимные посты в соцсетях
— Случайные YouTube-ролики без описания
— Ответ самой LLM без источника

Направления для поиска (выбери наиболее актуальные):
— Удаление сложных пятен (ржавчина, известковый налёт, жир, плесень)
— Уход за поверхностями (мрамор, ламинат, нержавеющая сталь, стекло, текстиль)
— Безопасное применение чистящих средств (совместимость, концентрации, риски)
— Профессиональные ошибки при уборке
— Уход за мягкой мебелью и коврами
— Устранение запахов

Верни ответ строго в формате JSON — без markdown-обёртки, без комментариев:

{
  "tips": [
    {
      "title": "Короткое название совета",
      "topic": "удаление пятен | уход за поверхностями | бытовая химия | запахи | ошибки | мягкая мебель | другое",
      "verified_fact": "Конкретный факт или рекомендация — что именно нужно делать и почему.",
      "source_name": "Название источника (сайт, документ, стандарт)",
      "source_url": "https://... (если доступен URL, иначе пустая строка)",
      "content_angle": "Как адаптировать этот факт в контент для нашей аудитории — угол подачи.",
      "safety_notes": "Важные предупреждения, если есть. Иначе пустая строка."
    }
  ],
  "found_count": 4,
  "search_summary": "Краткое описание что и где искал (1–2 предложения)"
}
"""


def _atomic_write(path: Path, data: list) -> None:
    """Атомарная запись JSON: пишем во временный файл, затем переименовываем."""
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)


def load_tips_bank(store: Store) -> list[dict]:
    path = store.project_dir / "tips_bank.json"
    if not path.exists():
        return []
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return []


def save_tips_bank(store: Store, tips: list[dict]) -> None:
    path = store.project_dir / "tips_bank.json"
    _atomic_write(path, tips)


def run(store: Store) -> tuple[int, list[dict]]:
    """
    Запускает Tips Research.
    Возвращает (количество_добавленных, список_новых_советов).
    Советы добавляются в tips_bank.json, не перезаписывая старые.
    """
    logger.info("[Tips] Запуск еженедельного research по советам")

    system = build_system_message(store)
    messages = [{"role": "user", "content": TIPS_PROMPT}]

    raw = llm_client.complete(
        mode="research",
        system=system,
        messages=messages,
        json_mode=True,
    )

    try:
        data = json.loads(raw)
    except json.JSONDecodeError as e:
        logger.error(f"[Tips] Ошибка парсинга JSON: {e}")
        return 0, []

    new_tips = data.get("tips", [])
    if not new_tips:
        logger.warning("[Tips] LLM не вернул ни одного совета")
        return 0, []

    # Добавляем метаданные к каждому совету
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    for tip in new_tips:
        tip.setdefault("status", "pending_review")
        tip.setdefault("created_at", now)

    # Добавляем к существующим (не перезаписываем)
    existing = load_tips_bank(store)
    existing.extend(new_tips)
    save_tips_bank(store, existing)

    found = data.get("found_count", len(new_tips))
    summary = data.get("search_summary", "")
    logger.info(f"[Tips] Добавлено советов: {len(new_tips)} (из найденных: {found}). {summary}")

    return len(new_tips), new_tips
