"""
Оркестратор workflow.

Читает текущее состояние системы и маршрутизирует к нужному модулю.
Не содержит бизнес-логики — только вызывает существующие модули.

Состояния и переходы:
  IDLE               → запускает research автоматически
  PENDING_REVIEW     → предлагает запустить review (требует решения пользователя)
  PENDING_CREATE     → запускает create автоматически
  PENDING_PUBLICATION→ ждёт подтверждения публикации от пользователя
  PENDING_RESULTS    → ждёт внесения результатов в results_log.md
"""

import logging
from engine.store import Store
from engine import research, create

logger = logging.getLogger(__name__)

# Состояния системы
IDLE                = "IDLE"
PENDING_REVIEW      = "PENDING_REVIEW"
PENDING_CREATE      = "PENDING_CREATE"
PENDING_PUBLICATION = "PENDING_PUBLICATION"
PENDING_RESULTS     = "PENDING_RESULTS"


def get_state(store: Store) -> str:
    """
    Определяет текущее состояние pipeline на основе данных в store.
    Возвращает одну из констант состояния.
    Эта функция — единственная точка входа для Telegram или планировщика,
    чтобы узнать, что сейчас нужно делать.
    """
    candidates   = store.load_candidate_ideas()
    bank_ideas   = store.load_bank_ideas()

    waiting_content = [i for i in bank_ideas if i.get("status") == "approved_waiting_content"]
    content_created = [i for i in bank_ideas if i.get("status") == "content_created"]
    published       = [i for i in bank_ideas if i.get("status") == "published"]

    # Campaign Spec готов к Create — приоритет выше Review,
    # чтобы пропущенные идеи не блокировали одобренную кампанию.
    if store.next_spec_for_create() is not None or waiting_content:
        return PENDING_CREATE
    if candidates:
        return PENDING_REVIEW
    if content_created:
        return PENDING_PUBLICATION
    if published:
        return PENDING_RESULTS
    return IDLE


def describe_state(state: str, store: Store) -> str:
    """
    Возвращает человекочитаемое описание текущего состояния.
    Используется CLI и может использоваться Telegram-адаптером.
    """
    bank_ideas = store.load_bank_ideas()

    if state == IDLE:
        return "Нет незавершённых задач. Запускаем research."

    if state == PENDING_REVIEW:
        n = len(store.load_candidate_ideas())
        return f"Найдено {n} идей, ожидающих рассмотрения."

    if state == PENDING_CREATE:
        idea = store.next_for_create()
        title = idea.get("title", "—") if idea else "—"
        return f"Одобренная идея ждёт создания контента: «{title}»."

    if state == PENDING_PUBLICATION:
        idea = store.next_for_publish()
        title = idea.get("title", "—") if idea else "—"
        return f"Контент готов к публикации: «{title}». Опубликуйте и подтвердите."

    if state == PENDING_RESULTS:
        n = len([i for i in bank_ideas if i.get("status") == "published"])
        return f"{n} публикаций ожидают внесения результатов в results_log.md."

    return "Неизвестное состояние."


def run(store: Store) -> None:
    """
    Запускает один шаг workflow.

    Автоматические шаги (не требуют участия пользователя):
      IDLE            → research.run()
      PENDING_CREATE  → create.run()

    Шаги, требующие действия пользователя:
      PENDING_REVIEW       → подсказывает запустить `review`
      PENDING_PUBLICATION  → подсказывает запустить `publish`
      PENDING_RESULTS      → подсказывает внести данные и повторить

    Telegram-адаптер вызывает get_state() + отдельные модули напрямую,
    минуя эту функцию.
    """
    state = get_state(store)
    description = describe_state(state, store)

    sep = "─" * 60
    print(f"\n{sep}")
    print(f"  Состояние: {state}")
    print(f"  {description}")
    print(sep)

    if state == IDLE:
        print("  Запускаю research...\n")
        report, data = research.run(store)
        print(report)
        if data is None:
            print("[!] Структурированные данные не получены — см. parse_error в sessions/\n")
        else:
            n = len(data.get("ideas", []))
            print(f"\n  ✓ Research завершён. Добавлено кандидатов: {n}")
            print(f"  Следующий шаг: python engine/run.py workflow  (или review)\n")

    elif state == PENDING_REVIEW:
        print("\n  Действие требует вашего участия.")
        print("  Запустите: python engine/run.py review\n")

    elif state == PENDING_CREATE:
        print("  Запускаю create...\n")
        result = create.run(store)
        if result:
            package, _ = result
            print(package)
            print("\n  ✓ Пакет публикации создан.")
            print("  Следующий шаг: python engine/run.py workflow  (или publish)\n")
        else:
            print("  [!] Не удалось создать контент.\n")

    elif state == PENDING_PUBLICATION:
        idea = store.next_for_publish()
        title = idea.get("title", "—") if idea else "—"
        print(f"\n  Опубликуйте контент «{title}» на выбранной платформе.")
        print("  Когда контент опубликован — запустите: python engine/run.py publish\n")

    elif state == PENDING_RESULTS:
        print("\n  Внесите результаты публикаций в файл:")
        print(f"  data/{store.project}/results_log.md")
        print("  После внесения запустите: python engine/run.py workflow\n")
