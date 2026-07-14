"""
Адаптер прямого Anthropic API (заглушка).
Реализуется при необходимости перейти с OpenRouter на нативный API.
Контракт идентичен openrouter.py.
"""


def complete(model: str, system: str, messages: list[dict], params: dict) -> str:
    raise NotImplementedError(
        "Адаптер Anthropic не реализован. "
        "Используйте provider: openrouter в config.yaml, "
        "или реализуйте этот адаптер через anthropic SDK."
    )
