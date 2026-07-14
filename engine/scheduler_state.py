"""
Хранение состояния Scheduler в data/{project}/scheduler_state.json.
Персистентно между перезапусками бота.
"""

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from engine.store import Store

logger = logging.getLogger(__name__)

_FILENAME = "scheduler_state.json"


def _path(store: Store) -> Path:
    return store.project_dir / _FILENAME


def _atomic_write(path: Path, data: dict) -> None:
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)


def load(store: Store) -> dict:
    path = _path(store)
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception as e:
        logger.warning(f"[Scheduler] Не удалось прочитать state: {e}")
        return {}


def save(store: Store, state: dict) -> None:
    try:
        _atomic_write(_path(store), state)
    except Exception as e:
        logger.error(f"[Scheduler] Не удалось сохранить state: {e}")


def get_last_research_dt(store: Store) -> datetime | None:
    """Дата последнего планового Research (UTC)."""
    state = load(store)
    raw = state.get("last_research_at")
    if not raw:
        return None
    try:
        return datetime.fromisoformat(raw).replace(tzinfo=timezone.utc)
    except Exception:
        return None


def get_last_tips_dt(store: Store) -> datetime | None:
    """Дата последнего Tips Research (UTC)."""
    state = load(store)
    raw = state.get("last_tips_at")
    if not raw:
        return None
    try:
        return datetime.fromisoformat(raw).replace(tzinfo=timezone.utc)
    except Exception:
        return None


def mark_research_done(store: Store, success: bool = True) -> None:
    state = load(store)
    now = datetime.now(timezone.utc).isoformat()
    if success:
        state["last_research_at"] = now
        state["last_research_success"] = now
    else:
        state["last_research_error"] = now
    save(store, state)


def mark_tips_done(store: Store, success: bool = True) -> None:
    state = load(store)
    now = datetime.now(timezone.utc).isoformat()
    if success:
        state["last_tips_at"] = now
        state["last_tips_success"] = now
    else:
        state["last_tips_error"] = now
    save(store, state)


def research_due(store: Store, interval_days: int = 2) -> bool:
    """True если с последнего Research прошло >= interval_days дней."""
    last = get_last_research_dt(store)
    if last is None:
        return True
    elapsed = (datetime.now(timezone.utc) - last).total_seconds()
    return elapsed >= interval_days * 86400


def tips_due(store: Store, interval_days: int = 7) -> bool:
    """True если с последнего Tips Research прошло >= interval_days дней."""
    last = get_last_tips_dt(store)
    if last is None:
        return True
    elapsed = (datetime.now(timezone.utc) - last).total_seconds()
    return elapsed >= interval_days * 86400
