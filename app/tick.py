"""Background scheduler thread."""

from __future__ import annotations

import threading
import time
from datetime import datetime, timezone
from typing import Any

from app.config import AppConfig
from app.jobs import ensure_default_jobs, fire_due_jobs
from app.reminders import fire_due_reminders

_tick_lock = threading.Lock()
_last_tick_at: str | None = None
_running = False
_thread: threading.Thread | None = None
SLEEP_SECONDS = 10


def last_tick_at() -> str | None:
    return _last_tick_at


def is_running() -> bool:
    return _running


def run_tick(cfg: AppConfig) -> None:
    global _last_tick_at
    with _tick_lock:
        try:
            fire_due_reminders(cfg)
            fire_due_jobs(cfg)
        finally:
            _last_tick_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _loop(cfg: AppConfig) -> None:
    global _running
    _running = True
    while _running:
        try:
            run_tick(cfg)
        except Exception:
            pass
        time.sleep(SLEEP_SECONDS)


def start_scheduler(cfg: AppConfig) -> None:
    global _thread, _running
    ensure_default_jobs(cfg)
    if _thread and _thread.is_alive():
        return
    _running = True
    _thread = threading.Thread(target=_loop, args=(cfg,), daemon=True, name="desktopper-tick")
    _thread.start()


def stop_scheduler() -> None:
    global _running
    _running = False


def scheduler_status() -> dict[str, Any]:
    return {"running": is_running(), "last_tick_at": last_tick_at()}
