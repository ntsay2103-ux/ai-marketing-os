"""
Единственная точка взаимодействия с LLM для всех модулей системы.
Читает конфигурацию, выбирает провайдера и модель, логирует каждый вызов.
Модули вызывают только: llm_client.complete(mode, system, messages)
"""

import time
import logging
from pathlib import Path
import yaml

BASE_DIR = Path(__file__).parent.parent

logger = logging.getLogger(__name__)


def _load_config() -> dict:
    path = BASE_DIR / "config.yaml"
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f)


def _strip_markdown_fence(text: str) -> str:
    """
    Извлекает JSON из ответа модели.
    Обрабатывает три случая:
    1. Чистый JSON
    2. ```json...``` обёртка
    3. Смешанный текст (chain-of-thought) + ```json...``` где-то внутри
    """
    import re as _re

    stripped = text.strip()

    # Случай 1: начинается с { или [ — чистый JSON
    if stripped.startswith(("{", "[")):
        return stripped

    # Случай 2/3: ищем первый ```json или ``` блок в тексте
    m = _re.search(r'```(?:json)?\s*\n(.*?)```', stripped, _re.DOTALL)
    if m:
        return m.group(1).strip()

    # Случай 4: в тексте есть { ... } — берём первый JSON-объект
    m2 = _re.search(r'(\{[\s\S]*\})', stripped)
    if m2:
        return m2.group(1).strip()

    return stripped


def _get_provider(provider_name: str):
    if provider_name == "openrouter":
        from engine.providers import openrouter
        return openrouter
    elif provider_name == "anthropic":
        from engine.providers import anthropic_provider
        return anthropic_provider
    else:
        raise ValueError(f"Неизвестный провайдер: '{provider_name}'. "
                         f"Допустимые значения: openrouter, anthropic")


def complete(mode: str, system: str, messages: list[dict], json_mode: bool = False) -> str:
    """
    Основной метод. Все модули вызывают только его.

    mode  — строка режима ('research', 'create', 'review', 'default')
    system — системное сообщение (контекст + профиль проекта)
    messages — список {"role": "user"/"assistant", "content": "..."}
    """
    config = _load_config()
    llm_cfg = config["llm"]

    provider_name = llm_cfg["provider"]
    model = llm_cfg["models"].get(mode) or llm_cfg["models"]["default"]
    params = llm_cfg.get("parameters", {})

    provider = _get_provider(provider_name)

    logger.info(f"[LLM] mode={mode}  provider={provider_name}  model={model}")
    start = time.time()

    result = provider.complete(
        model=model,
        system=system,
        messages=messages,
        params=params,
        json_mode=json_mode,
    )

    elapsed = time.time() - start

    if json_mode:
        result = _strip_markdown_fence(result)

    logger.info(f"[LLM] готово  время={elapsed:.1f}s  символов={len(result)}")

    return result
