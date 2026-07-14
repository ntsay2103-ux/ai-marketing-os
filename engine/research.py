"""
Режим Research: определение этапа воронки, поиск идей, оценка потенциала.
Один вызов LLM → JSON → Python формирует Markdown-отчёт.
"""

import json
import logging
from datetime import datetime
from engine.store import Store
from engine.context import build_system_message, load_prompt, build_messages
from engine import llm_client

logger = logging.getLogger(__name__)

RESEARCH_USER_PROMPT = """
Проведи research-сессию по текущему проекту.

Верни ответ строго в формате JSON — без markdown-обёртки, без комментариев.

Структура JSON:
{
  "funnel_stage": "холодная | тёплая | горячая",
  "funnel_rationale": "Объяснение выбора этапа воронки (1–2 предложения)",
  "ideas": [
    {
      "title": "Название идеи",
      "source": "Источник или пример механики (из какой ниши перенесена)",
      "trigger": "Психологический триггер или механика — почему работает",
      "potential": "Низкий | Средний | Высокий",
      "potential_rationale": "Краткое обоснование потенциала",
      "adaptation": "Конкретное предложение адаптации под проект"
    }
  ],
  "recommended_title": "Название рекомендованной идеи",
  "recommended_rationale": "Почему рекомендуешь именно эту идею сегодня"
}

Требования:
- ideas: от 3 до 5 идей
- potential: строго одно из трёх значений: Низкий, Средний, Высокий
- funnel_stage: строго одно из трёх значений: холодная, тёплая, горячая
- recommended_title должен точно совпадать с одним из title в ideas
- Гипотезы обозначай словами «предположительно» или «вероятно» внутри текстовых полей
- Факты отделяй от допущений внутри текстовых полей

Используй контекст из RESEARCH_PROTOCOL для выбора идей и оценки потенциала.
"""

POTENTIAL_ORDER = {"Высокий": 0, "Средний": 1, "Низкий": 2}


def format_report(data: dict) -> str:
    """Формирует человекочитаемый Markdown-отчёт из JSON-данных."""
    lines = []

    stage = data.get("funnel_stage", "—")
    rationale = data.get("funnel_rationale", "")
    lines.append(f"# Research-сессия\n")
    lines.append(f"## Этап воронки: {stage.capitalize()}")
    if rationale:
        lines.append(f"\n{rationale}\n")

    lines.append("## Идеи для контента\n")

    ideas = data.get("ideas", [])
    sorted_ideas = sorted(ideas, key=lambda x: POTENTIAL_ORDER.get(x.get("potential", ""), 99))

    for i, idea in enumerate(sorted_ideas, 1):
        potential = idea.get("potential", "—")
        title = idea.get("title", "—")
        lines.append(f"### {i}. {title}  `[{potential}]`\n")
        lines.append(f"**Источник:** {idea.get('source', '—')}\n")
        lines.append(f"**Триггер:** {idea.get('trigger', '—')}\n")
        lines.append(f"**Потенциал:** {potential} — {idea.get('potential_rationale', '—')}\n")
        lines.append(f"**Адаптация:** {idea.get('adaptation', '—')}\n")

    rec_title = data.get("recommended_title", "—")
    rec_why = data.get("recommended_rationale", "")
    lines.append(f"## Рекомендация\n")
    lines.append(f"**{rec_title}**\n")
    if rec_why:
        lines.append(f"{rec_why}\n")

    return "\n".join(lines)


def run(store: Store) -> tuple[str, dict | None]:
    """
    Запускает research-сессию: один вызов LLM → JSON → Markdown.
    Возвращает (markdown_report, data_dict или None при ошибке парсинга).
    Сохраняет .md и .json в sessions/.
    """
    logger.info("Запуск research-сессии")

    protocol = load_prompt("research_protocol")

    system = build_system_message(store)
    if protocol.strip():
        system += "\n\n---\n## Протокол исследования\n\n" + protocol

    messages = build_messages(RESEARCH_USER_PROMPT)

    raw = llm_client.complete(
        mode="research",
        system=system,
        messages=messages,
        json_mode=True,
    )

    try:
        data = json.loads(raw)
    except json.JSONDecodeError as e:
        error_path = store.save_raw_error(raw, reason=str(e))
        logger.error(
            f"Не удалось распарсить JSON от LLM: {e}\n"
            f"Сырой ответ сохранён: {error_path}"
        )
        print(f"\n[!] Ошибка парсинга JSON: {e}")
        print(f"    Сырой ответ LLM сохранён: {error_path}\n")
        return raw, None

    report = format_report(data)

    md_path = store.save_session(report, session_type="research")
    json_path = store.save_json(data, session_type="research")
    logger.info(f"Markdown сохранён: {md_path}")
    logger.info(f"JSON сохранён:     {json_path}")

    session_date = datetime.now().strftime("%Y-%m-%d %H:%M")
    candidates_path = store.append_candidates(
        ideas=data.get("ideas", []),
        funnel_stage=data.get("funnel_stage", "—"),
        session_date=session_date,
    )
    logger.info(f"Кандидаты сохранены: {candidates_path}")

    return report, data
