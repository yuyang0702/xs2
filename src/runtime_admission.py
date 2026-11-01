"""Ephemeral launch admission shared by Controller and Executor processes."""
from __future__ import annotations

import os
from contextlib import contextmanager
from functools import wraps
from pathlib import Path
from threading import RLock

GUARD_ENV = "DETERMINFLOW_LAUNCH_GUARD_FILE"
RESTART_MESSAGE = "服务正在安全重启，请稍后重试；当前任务和作品设置会保留。"
_activity_lock = RLock()
_activities: dict[str, int] = {}
_RAISE = object()


class AdmissionClosed(RuntimeError):
    pass


def is_closed(guard_file: Path | None = None) -> bool:
    raw = os.environ.get(GUARD_ENV, "") if guard_file is None else guard_file
    if not raw:
        return False
    try:
        Path(raw).stat()
        return True
    except FileNotFoundError:
        return False
    except OSError:
        return True


def ensure_accepting() -> None:
    if is_closed():
        raise AdmissionClosed(RESTART_MESSAGE)


@contextmanager
def activity_scope(reason: str):
    """Fence actual work, including preparation before the first model call."""
    with _activity_lock:
        ensure_accepting()
        _activities[reason] = _activities.get(reason, 0) + 1
    try:
        yield
    finally:
        with _activity_lock:
            remaining = _activities[reason] - 1
            if remaining:
                _activities[reason] = remaining
            else:
                del _activities[reason]


def active_reasons() -> list[str]:
    with _activity_lock:
        return list(_activities)


def create_guard(path: Path, owner: str) -> None:
    """Serialize marker creation with work admission in Controller threads."""
    with _activity_lock:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("x", encoding="utf-8") as marker:
            marker.write(owner)


def admitted_activity(reason: str, *, closed_result=_RAISE):
    """Track async entrypoints; background pollers can noop while fenced."""
    def decorate(function):
        @wraps(function)
        async def guarded(*args, **kwargs):
            try:
                with activity_scope(reason):
                    return await function(*args, **kwargs)
            except AdmissionClosed:
                if closed_result is _RAISE:
                    raise
                return closed_result.copy() if isinstance(closed_result, dict) else closed_result
        return guarded
    return decorate
