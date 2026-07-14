"""
Точка входа CLI.
Использование:
  python engine/run.py workflow          — основная точка входа: следующий шаг pipeline (Этап 8)
  python engine/run.py publish           — подтвердить публикацию контента (Этап 8)
  python engine/run.py research          — запустить research вручную
  python engine/run.py review            — рассмотреть идеи вручную
  python engine/run.py create            — создать пакет публикации вручную
  python engine/run.py test              — проверка подключения к LLM
"""

import sys
import logging
from pathlib import Path
import yaml
from dotenv import load_dotenv

BASE_DIR = Path(__file__).parent.parent
load_dotenv(BASE_DIR / ".env")

# Настройка логирования: INFO в консоль с временными метками
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)s  %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)

# Добавляем корень проекта в путь, чтобы engine-импорты работали
sys.path.insert(0, str(BASE_DIR))

from engine.store import Store
from engine.context import build_system_message, build_messages
from engine import llm_client
from engine import research
from engine import review
from engine import create
from engine import workflow


def get_active_project() -> str:
    config_path = BASE_DIR / "config.yaml"
    with open(config_path, encoding="utf-8") as f:
        config = yaml.safe_load(f)
    return config["projects"]["active"]


def cmd_test():
    """Этап 1: загрузить контекст проекта и сделать тестовый вызов LLM."""
    project = get_active_project()
    logger.info(f"Активный проект: {project}")

    store = Store(project)
    logger.info("Профиль проекта загружен")

    system = build_system_message(store)
    messages = build_messages(
        "Прочитай профиль проекта и ответь в 2–3 предложениях: "
        "с каким проектом ты работаешь и какова главная цель контента?"
    )

    logger.info("Отправляю запрос к LLM...")
    result = llm_client.complete(mode="default", system=system, messages=messages)

    print("\n" + "=" * 60)
    print("ОТВЕТ LLM:")
    print("=" * 60)
    print(result)
    print("=" * 60 + "\n")

    saved = store.save_session(f"# Тест Этапа 1\n\n{result}", session_type="test")
    logger.info(f"Сессия сохранена: {saved}")


def cmd_research():
    """Этап 3: research-сессия — один LLM-вызов, Markdown-отчёт + JSON."""
    project = get_active_project()
    logger.info(f"Активный проект: {project}")

    store = Store(project)
    report, data = research.run(store)

    print("\n" + "=" * 60)
    print("RESEARCH-СЕССИЯ:")
    print("=" * 60)
    print(report)
    print("=" * 60 + "\n")

    if data is None:
        print("[!] Структурированные данные не получены — см. файл parse_error в sessions/\n")


def cmd_review():
    """Этап 5: рассмотрение идей — одобрить или отклонить каждую из candidate_ideas."""
    project = get_active_project()
    logger.info(f"Активный проект: {project}")

    store = Store(project)
    review.run(store)


def cmd_create():
    """Этап 7: генерация полного пакета публикации по следующей одобренной идее."""
    project = get_active_project()
    logger.info(f"Активный проект: {project}")

    store = Store(project)
    result = create.run(store)

    if result is None:
        print("\nНет идей, ожидающих создания контента.")
        print("Сначала одобрите идеи через: python engine/run.py review\n")
        return

    package, _ = result

    print("\n" + "=" * 60)
    print("ПАКЕТ ПУБЛИКАЦИИ:")
    print("=" * 60)
    print(package)
    print("=" * 60 + "\n")


def cmd_workflow():
    """Этап 8: определяет текущий шаг pipeline и выполняет его."""
    project = get_active_project()
    logger.info(f"Активный проект: {project}")
    store = Store(project)
    workflow.run(store)


def cmd_publish():
    """Этап 8: подтвердить, что контент опубликован."""
    project = get_active_project()
    logger.info(f"Активный проект: {project}")
    store = Store(project)

    idea = store.next_for_publish()
    if idea is None:
        print("\nНет контента, ожидающего подтверждения публикации.\n")
        return

    sep = "─" * 60
    print(f"\n{sep}")
    print(f"  Подтверждение публикации")
    print(sep)
    print(f"  Идея:      {idea.get('title', '—')}")
    print(f"  Адаптация: {idea.get('adaptation', '—')}")
    print(f"  Контент создан: {idea.get('content_date', '—')}")
    print(sep)
    print("  Вы опубликовали этот контент? [y] Да  [n] Нет")

    choice = input("  > ").strip().lower()
    if choice == "y":
        from datetime import date as _date
        published_at = _date.today().isoformat()

        store.mark_published(idea)
        logger.info(f"Отмечено как опубликованное: {idea.get('title', '—')}")

        # Обновляем Campaign Specification, если он существует
        specs = store.load_campaign_specs()
        matching = next(
            (s for s in specs if s.get("source", {}).get("idea_title") == idea.get("title")),
            None,
        )
        if matching:
            store.mark_spec_platform_published(
                spec_id=matching["id"],
                platform="instagram",
                published_at=published_at,
                url=None,
            )
            logger.info(f"Campaign Specification обновлён: published ({matching['id']})")

        print(f"\n  ✓ Отмечено как опубликованное.")
        print(f"  Следующий шаг: python engine/run.py workflow\n")
    else:
        print("\n  Публикация не подтверждена. Статус не изменён.\n")


COMMANDS = {
    "workflow": cmd_workflow,
    "publish":  cmd_publish,
    "research": cmd_research,
    "review":   cmd_review,
    "create":   cmd_create,
    "test":     cmd_test,
}


def main():
    if len(sys.argv) < 2 or sys.argv[1] not in COMMANDS:
        available = ", ".join(COMMANDS)
        print(f"Использование: python engine/run.py [{available}]")
        sys.exit(1)

    COMMANDS[sys.argv[1]]()


if __name__ == "__main__":
    main()
