"""
Campaign Specification — единый источник данных для Create и будущих модулей.
Создаётся автоматически после утверждения идеи в Review.
Хранится в data/{project}/campaigns/camp_{id}.json + .md

MVP-правило: одна идея = одна кампания = один Campaign Specification.
"""

from datetime import datetime


def create_from_idea(idea: dict, project: str) -> dict:
    """
    Создаёт Campaign Specification из одобренной идеи.
    Idea Bank не изменяется — spec создаётся параллельно.
    """
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    spec_id = f"camp_{timestamp}"
    date_str = datetime.now().strftime("%Y-%m-%d")

    return {
        "id": spec_id,
        "created_at": date_str,
        "status": "approved",
        "project": project,
        "source": {
            "idea_title": idea.get("title", "—"),
            "approved_at": idea.get("approved_date", date_str),
        },
        "campaign": {
            "goal": idea.get("potential_rationale", ""),
            "funnel_stage": idea.get("funnel_stage", ""),
            "target_action": "",
        },
        "platforms": [
            {
                "platform": "instagram",
                "format": "post",
                "role": "основная публикация",
                "funnel_function": idea.get("funnel_stage", ""),
                "key_message": idea.get("trigger", ""),
                "cta": "",
                "content_status": "pending",
                "content_file": None,
                "published_at": None,
                "published_url": None,
            }
        ],
        "idea": idea,
    }


def format_spec(spec: dict) -> str:
    """Markdown-вид Campaign Specification для чтения человеком."""
    idea = spec.get("idea", {})
    campaign = spec.get("campaign", {})
    source = spec.get("source", {})

    lines = [
        f"# Campaign Specification: {source.get('idea_title', '—')}\n",
        f"**ID:** `{spec.get('id', '—')}`  "
        f"|  **Создан:** {spec.get('created_at', '—')}  "
        f"|  **Статус:** {spec.get('status', '—')}\n",
        "---\n",
        "## Кампания\n",
        f"- **Цель:** {campaign.get('goal', '—')}",
        f"- **Этап воронки:** {campaign.get('funnel_stage', '—')}",
        f"- **Целевое действие:** {campaign.get('target_action', '—') or 'не указано'}",
        "\n---\n",
        "## Площадки\n",
    ]

    for p in spec.get("platforms", []):
        lines += [
            f"### {p.get('platform', '—')} — {p.get('format', '—')}",
            f"- **Роль:** {p.get('role', '—')}",
            f"- **Функция в воронке:** {p.get('funnel_function', '—')}",
            f"- **Ключевая мысль:** {p.get('key_message', '—')}",
            f"- **Статус контента:** {p.get('content_status', '—')}",
        ]
        if p.get("content_file"):
            lines.append(f"- **Файл контента:** {p.get('content_file')}")
        lines.append("")

    lines += [
        "---\n",
        "## Исходная идея\n",
        f"- **Название:** {idea.get('title', '—')}",
        f"- **Источник:** {idea.get('source', '—')}",
        f"- **Триггер:** {idea.get('trigger', '—')}",
        f"- **Адаптация:** {idea.get('adaptation', '—')}",
        f"- **Потенциал:** {idea.get('potential', '—')} — {idea.get('potential_rationale', '—')}",
    ]

    return "\n".join(lines)
