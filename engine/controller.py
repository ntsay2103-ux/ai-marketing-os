"""
Controller — интерфейс-агностичная точка входа для всех будущих интерфейсов.

Не содержит логики отображения (print/input).
Возвращает структурированные данные — каждый интерфейс рендерит их самостоятельно.

  CLI сейчас:       workflow.run() — wrapper с print/input (не меняется)
  Telegram (будущее): controller.step() → dict → Telegram-рендеринг
  Scheduler (будущее): controller.step() → dict → уведомление/условный запуск
"""

import logging
from engine.store import Store
from engine import research, create
from engine.workflow import get_state, describe_state
from engine.workflow import (
    IDLE, PENDING_REVIEW, PENDING_CREATE,
    PENDING_PUBLICATION, PENDING_RESULTS,
)

logger = logging.getLogger(__name__)


def get_status(store: Store) -> dict:
    """
    Возвращает текущее состояние системы без выполнения каких-либо действий.
    Пригоден для /status в Telegram или отображения дашборда.

    Возвращает:
    {
        "state": str,                  — константа (IDLE, PENDING_REVIEW, ...)
        "description": str,            — человекочитаемое описание
        "requires_user_action": bool,  — требуется ли участие пользователя
        "next_command": str | None,    — CLI-команда для следующего шага
    }
    """
    state = get_state(store)
    description = describe_state(state, store)

    requires_user_action = state in {PENDING_REVIEW, PENDING_PUBLICATION, PENDING_RESULTS}

    next_command = {
        IDLE:                None,         # step() запустит research автоматически
        PENDING_REVIEW:      "review",
        PENDING_CREATE:      None,         # step() запустит create автоматически
        PENDING_PUBLICATION: "publish",
        PENDING_RESULTS:     None,         # пользователь вносит данные вручную
    }.get(state)

    return {
        "state": state,
        "description": description,
        "requires_user_action": requires_user_action,
        "next_command": next_command,
    }


def step(store: Store, force_research: bool = False) -> dict:
    """
    Выполняет следующий автоматический шаг pipeline.
    Если шаг требует участия пользователя — не выполняет его, возвращает инструкцию.

    force_research=True: очищает очередь кандидатов и запускает новый Research
    независимо от текущего состояния (кроме PENDING_REVIEW и PENDING_CREATE).
    Idea Bank, кампании и результаты не затрагиваются.

    Автоматические шаги:
      IDLE            → research.run()
      PENDING_CREATE  → create.run()

    Интерактивные шаги (возвращает без действий):
      PENDING_REVIEW, PENDING_PUBLICATION, PENDING_RESULTS

    Возвращает:
    {
        "state": str,
        "description": str,
        "requires_user_action": bool,
        "next_command": str | None,
        "action_taken": str | None,    — "research" / "create" / None
        "result": dict | None,         — данные выполненного шага
        "error": str | None,           — описание ошибки, если шаг не выполнен
    }
    """
    status = get_status(store)
    state = status["state"]

    if force_research and state not in (PENDING_REVIEW, PENDING_CREATE):
        logger.info(f"[Controller] force_research=True, state={state} → очищаю кандидатов и запускаю research")
        store.save_candidate_ideas([])
        state = IDLE

    if state == IDLE:
        logger.info("[Controller] state=IDLE → запускаю research")
        report, data = research.run(store)

        if data is None:
            return {
                **status,
                "action_taken": "research",
                "result": None,
                "error": "Структурированные данные не получены — см. parse_error в sessions/",
            }

        return {
            **status,
            "action_taken": "research",
            "result": {
                "report": report,
                "ideas_count": len(data.get("ideas", [])),
            },
            "error": None,
            "requires_user_action": True,
            "next_command": "review",
        }

    if state == PENDING_CREATE:
        logger.info("[Controller] state=PENDING_CREATE → запускаю create")
        result = create.run(store)

        if result is None:
            return {
                **status,
                "action_taken": "create",
                "result": None,
                "error": "Не удалось создать контент.",
            }

        package, data = result
        return {
            **status,
            "action_taken": "create",
            "result": {
                "package": package,
                "data": data,
            },
            "error": None,
            "requires_user_action": True,
            "next_command": "publish",
        }

    # Состояния, требующие участия пользователя — возвращаем статус без действий
    return {
        **status,
        "action_taken": None,
        "result": None,
        "error": None,
    }


def get_pending_ideas(store: Store) -> list[dict]:
    """
    Возвращает список идей, ожидающих рассмотрения.
    Используется Telegram и другими интерфейсами для Review-сессии.
    """
    return store.load_candidate_ideas()


def decide_idea(store: Store, idea: dict, decision: str) -> dict:
    """
    Применяет решение по одной идее и немедленно обновляет candidate_ideas.

    decision: "approve" | "reject" | "skip"

    Возвращает:
    {
        "decision": str,
        "idea_title": str,
    }
    """
    from engine import review as _review

    _review.decide(store, idea, decision)

    if decision != "skip":
        candidates = store.load_candidate_ideas()
        remaining = [c for c in candidates if c.get("title") != idea.get("title")]
        store.save_candidate_ideas(remaining)

    return {
        "decision": decision,
        "idea_title": idea.get("title", "—"),
    }


def get_published_campaigns(store: Store) -> list[dict]:
    """
    Возвращает Campaign Specifications, готовые к внесению результатов.
    Используется модулем Results.
    """
    return store.get_published_specs()


def save_campaign_results(store: Store, spec_id: str, results: dict) -> None:
    """
    Сохраняет результаты кампании и переводит её в статус 'results_collected'.
    После этого кампания готова к этапу Insights.
    """
    store.save_results_to_spec(spec_id, results)
