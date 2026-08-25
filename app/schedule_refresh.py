"""Refresh _schedules from schema.json reminders and jobs."""

from __future__ import annotations

from typing import Any

from app.config import AppConfig, read_or_create_schema
from app.host_db import connect
from app.jobs import upsert_job_schedule
from app.reminders import _clear_schedule, upsert_schedule_row


def refresh_schedules_for_diff(cfg: AppConfig, diff: dict[str, Any]) -> None:
    schema = read_or_create_schema(cfg.appdir)
    conn = connect(cfg.appdir)
    try:
        for item in diff.get("add_reminders") or []:
            if isinstance(item, dict) and item.get("id"):
                rid = item["id"]
                rem = _find_reminder(schema, rid)
                if rem:
                    if rem.get("enabled") is False:
                        _clear_schedule(cfg, rid, conn=conn)
                    else:
                        upsert_schedule_row(cfg, rid, rem, conn=conn)
        for item in diff.get("update_reminders") or []:
            if isinstance(item, dict) and item.get("id"):
                rid = item["id"]
                rem = _find_reminder(schema, rid)
                if rem:
                    if rem.get("enabled") is False:
                        _clear_schedule(cfg, rid, conn=conn)
                    else:
                        upsert_schedule_row(cfg, rid, rem, conn=conn)
        for rid in diff.get("disable_reminders") or []:
            _clear_schedule(cfg, str(rid), conn=conn)
        for item in diff.get("add_jobs") or []:
            if isinstance(item, dict) and item.get("id"):
                upsert_job_schedule(cfg, item["id"], item, conn=conn)
        for jid in diff.get("disable_jobs") or []:
            conn.execute(
                "UPDATE _schedules SET next_run_at = NULL, done = 1 WHERE spec_kind = 'job' AND spec_id = ?",
                (str(jid),),
            )
        conn.commit()
    finally:
        conn.close()


def _find_reminder(schema: dict[str, Any], rid: str) -> dict[str, Any] | None:
    for item in schema.get("reminders") or []:
        if isinstance(item, dict) and item.get("id") == rid:
            return item
    return None
