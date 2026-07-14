"""
Режим Review: рассмотрение идей из candidate_ideas.

Бизнес-логика (decide, apply_decision) не зависит от интерфейса.
CLI-функции (_show_idea, _prompt_decision, run) — единственное место с print/input.
Telegram или другой интерфейс вызывает только decide() напрямую.
"""

import logging
from datetime import datetime
from engine.store import Store

logger = logging.getLogger(__name__)

POTENTIAL_LABEL = {
    "Высокий": "🟢 Высокий",
    "Средний": "🟡 Средний",
    "Низкий":  "🔴 Низкий",
}

VALID_DECISIONS = {"approve", "reject", "skip"}


# ---------------------------------------------------------------------------
# Бизнес-логика — не зависит от интерфейса
# ---------------------------------------------------------------------------

def decide(store: Store, idea: dict, decision: str) -> str:
    """
    Применяет решение по одной идее.

    decision: "approve" | "reject" | "skip"
    Возвращает то же значение decision для удобства вызывающего кода.
    """
    if decision not in VALID_DECISIONS:
        raise ValueError(f"Недопустимое решение: '{decision}'. Допустимые: {VALID_DECISIONS}")

    if decision == "approve":
        store.approve_idea(idea)
        logger.info(f"Одобрена: {idea.get('title', '—')}")
        from engine import campaign as _camp
        _idea_with_date = {**idea, "approved_date": datetime.now().strftime("%Y-%m-%d")}
        _spec = _camp.create_from_idea(_idea_with_date, store.project)
        store.save_campaign_spec(_spec, _camp.format_spec(_spec))
        logger.info(f"Campaign Specification создан: {_spec['id']}")
    elif decision == "reject":
        logger.info(f"Отклонена: {idea.get('title', '—')}")
    elif decision == "skip":
        logger.info(f"Пропущена: {idea.get('title', '—')}")

    return decision


def apply_decisions(store: Store, ideas: list[dict], decisions: dict[int, str]) -> list[dict]:
    """
    Применяет словарь решений {index: decision} к списку идей.
    Возвращает список идей, оставшихся в очереди (только skip и нерассмотренные).
    """
    remaining = []
    for idx, idea in enumerate(ideas):
        d = decisions.get(idx)
        if d is None or d == "skip":
            remaining.append(idea)
    return remaining


# ---------------------------------------------------------------------------
# CLI-интерфейс — единственное место с print/input
# ---------------------------------------------------------------------------

_CLI_MAP = {"o": "approve", "x": "reject", "s": "skip", "q": "quit"}


def _show_idea(idea: dict, index: int, total: int) -> None:
    potential = idea.get("potential", "—")
    label = POTENTIAL_LABEL.get(potential, potential)
    sep = "─" * 60
    print(f"\n{sep}")
    print(f"  Идея {index}/{total}  |  Потенциал: {label}")
    print(f"  Сессия: {idea.get('session_date', '—')}  |  Аудитория: {idea.get('funnel_stage', '—')}")
    print(sep)
    print(f"  Название:  {idea.get('title', '—')}")
    print(f"  Источник:  {idea.get('source', '—')}")
    print(f"  Триггер:   {idea.get('trigger', '—')}")
    print(f"  Потенциал: {potential} — {idea.get('potential_rationale', '—')}")
    print(f"  Адаптация: {idea.get('adaptation', '—')}")
    print(sep)


def _prompt_decision() -> str:
    options = "  [o] одобрить   [x] отклонить   [s] пропустить   [q] выйти"
    while True:
        print(options)
        raw = input("  > ").strip().lower()
        if raw in _CLI_MAP:
            return _CLI_MAP[raw]
        print(f"  Неверный ввод. Допустимые: o / x / s / q")


def run(store: Store) -> None:
    """CLI-обёртка над decide(). Единственное место, где используется input()."""
    ideas = store.load_candidate_ideas()

    if not ideas:
        print("\nНет идей для рассмотрения. Сначала запустите research-сессию.\n")
        return

    total = len(ideas)
    print(f"\nНайдено идей для рассмотрения: {total}")

    decisions: dict[int, str] = {}

    for idx, idea in enumerate(ideas):
        _show_idea(idea, idx + 1, total)
        decision = _prompt_decision()

        if decision == "quit":
            print("\n  Выход. Нерассмотренные идеи остаются в candidate_ideas.\n")
            break

        decide(store, idea, decision)
        decisions[idx] = decision

        if decision == "approve":
            print("  ✓ Одобрена → idea_bank\n")
        elif decision == "reject":
            print("  ✗ Отклонена.\n")
        elif decision == "skip":
            print("  → Пропущена. Останется в candidate_ideas.\n")

    remaining = apply_decisions(store, ideas, decisions)
    store.save_candidate_ideas(remaining)

    approved = sum(1 for d in decisions.values() if d == "approve")
    rejected = sum(1 for d in decisions.values() if d == "reject")
    skipped = sum(1 for d in decisions.values() if d == "skip")

    sep = "─" * 60
    print(sep)
    print(f"  Итого рассмотрено: {approved + rejected} из {total}")
    print(f"  Одобрено:   {approved}")
    print(f"  Отклонено:  {rejected}")
    print(f"  Пропущено:  {skipped}")
    print(f"  Осталось в очереди: {len(remaining)}")
    print(sep + "\n")

    logger.info(f"Review завершён: одобрено={approved}, отклонено={rejected}, пропущено={skipped}, осталось={len(remaining)}")
