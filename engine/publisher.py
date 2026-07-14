"""
Автоматическая публикация кампании на площадках MVP.

MVP площадки: Instagram (ручной), Threads, Дзен, Сайт.
Все кроме Instagram — заглушки до подключения реальных API.

Возможные статусы платформы:
  published       — успешно опубликовано
  not_configured  — интеграция не настроена
  pending_manual  — ожидает ручной публикации пользователем
  error           — ошибка при публикации
"""

import logging

logger = logging.getLogger(__name__)

PUBLISHED       = "published"
NOT_CONFIGURED  = "not_configured"
PENDING_MANUAL  = "pending_manual"
ERROR           = "error"


def publish_threads(content_data: dict) -> dict:
    return {"status": NOT_CONFIGURED, "message": "Threads API не настроен"}


def publish_dzen(content_data: dict) -> dict:
    return {"status": NOT_CONFIGURED, "message": "Дзен API не настроен"}


def publish_site(content_data: dict) -> dict:
    return {"status": NOT_CONFIGURED, "message": "Публикация на сайте не настроена"}


async def run_auto_publish(content_data: dict, bot, chat_id: int) -> dict:
    """
    Запускает автопубликацию на всех MVP площадках.
    Instagram не публикуется — ожидает ручной публикации.
    Возвращает словарь статусов: {platform: {"status": ..., ...}}.
    """
    results: dict[str, dict] = {}
    results["threads"]   = publish_threads(content_data)
    results["dzen"]      = publish_dzen(content_data)
    results["site"]      = publish_site(content_data)
    results["instagram"] = {"status": PENDING_MANUAL}
    return results
