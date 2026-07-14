"""
Сборка контекста для LLM из файлов проекта.
Не содержит бизнес-логики и не знает о конкретных моделях.
"""

from pathlib import Path

BASE_DIR = Path(__file__).parent.parent


def load_prompt(name: str) -> str:
    path = BASE_DIR / "prompts" / f"{name}.md"
    if not path.exists():
        return ""
    return path.read_text(encoding="utf-8")


def build_system_message(store) -> str:
    """Системное сообщение: инструкции + профиль проекта + банк идей + накопленные выводы."""
    parts = [load_prompt("system")]

    profile = store.load_profile()
    if profile.strip():
        parts.append("---\n## Профиль проекта\n\n" + profile)

    idea_bank = store.load_idea_bank()
    if idea_bank.strip() and "пусто" not in idea_bank.lower() and "пока нет" not in idea_bank.lower():
        parts.append("---\n## Банк идей (одобренные и уже созданные)\n\n" + idea_bank)

    insights = store.load_insights()
    if insights.strip() and "пока нет" not in insights.lower():
        parts.append("---\n## Накопленные выводы из прошлых циклов\n\n" + insights)

    return "\n\n".join(p for p in parts if p.strip())


def build_messages(user_text: str) -> list[dict]:
    """Обёртка для простых однозначных запросов."""
    return [{"role": "user", "content": user_text}]
