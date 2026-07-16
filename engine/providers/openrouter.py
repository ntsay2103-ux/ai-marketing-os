"""
Адаптер OpenRouter. Использует OpenAI SDK с кастомным base_url.
Реализует контракт: complete(model, system, messages, params) -> str
"""

import os
from openai import OpenAI


def complete(model: str, system: str, messages: list[dict], params: dict, json_mode: bool = False) -> str:
    api_key = os.getenv("OPENROUTER_API_KEY")
    if not api_key:
        raise EnvironmentError("OPENROUTER_API_KEY не найден в .env")

    client = OpenAI(
        api_key=api_key,
        base_url="https://openrouter.ai/api/v1",
        default_headers={
            "HTTP-Referer": "https://github.com/ntsay2103-ux/ai-marketing-os",
            "X-Title": "AI Marketing OS",
        },
    )

    all_messages = []
    if system:
        all_messages.append({"role": "system", "content": system})
    all_messages.extend(messages)

    create_kwargs = dict(
        model=model,
        messages=all_messages,
        max_tokens=params.get("max_tokens", 4096),
        temperature=params.get("temperature", 0.7),
    )
    if json_mode:
        create_kwargs["response_format"] = {"type": "json_object"}

    response = client.chat.completions.create(**create_kwargs)

    if not response.choices:
        raise RuntimeError(f"OpenRouter вернул пустой choices (model={model})")

    return response.choices[0].message.content or ""
