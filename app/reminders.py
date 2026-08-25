"""Wall-clock reminders: spec objects plus _schedules."""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from typing import Any

from app.config import AppConfig, read_or_create_schema, schema_path
from app.db_paths import db_path
from app.host_db import connect
from app.notices import insert_notice
from app.schedules import compute_next_run_at, schedule_summary, validate_schedule
from app.schema_validate import NAME_RE, ValidationError

REMINDER_KEYS = {
    "id",
    "title",
    "body",
    "enabled",
    "tz",
    "schedule",
    "action",
    "table",
    "title_column",
    "when",
}
ALLOWED_ACTION_KINDS = frozenset({"notify", "email"})
MAX_SNOOZE_MINUTES = 10080


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _now_dt(cfg: AppConfig) -> datetime:
    from zoneinfo import ZoneInfo

    return datetime.now(ZoneInfo(cfg.timezone))


def _find_reminder(schema: dict[str, Any], rid: str) -> dict[str, Any] | None:
    for item in schema.get("reminders") or []:
        if isinstance(item, dict) and item.get("id") == rid:
            return item
    return None


def validate_reminder_object(obj: dict[str, Any], *, is_update: bool = False) -> None:
    if not isinstance(obj, dict):
        raise ValidationError("bad_reminder", "Reminder must be an object.")
    extra = set(obj) - REMINDER_KEYS
    if extra:
        raise ValidationError("unknown_key", f"Reminder has unknown keys: {sorted(extra)}.")
    rid = obj.get("id")
    if not isinstance(rid, str) or not NAME_RE.match(rid):
        raise ValidationError("bad_reminder", "Reminder id must be snake_case.")
    if not isinstance(obj.get("title"), str) or not obj["title"].strip():
        raise ValidationError("bad_reminder", "Reminder title is required.")
    if "body" in obj and obj["body"] is not None and not isinstance(obj["body"], str):
        raise ValidationError("bad_reminder", "Reminder body must be a string.")
    if "enabled" in obj and not isinstance(obj["enabled"], bool):
        raise ValidationError("bad_reminder", "enabled must be boolean.")
    schedule = obj.get("schedule")
    if not isinstance(schedule, dict):
        raise ValidationError("bad_reminder", "schedule is required.")
    validate_schedule(schedule, allow_on_date_column=True)
    action = obj.get("action") or {"kind": "notify"}
    if not isinstance(action, dict):
        raise ValidationError("bad_reminder", "action must be an object.")
    kind = action.get("kind", "notify")
    if kind not in ALLOWED_ACTION_KINDS:
        raise ValidationError("bad_reminder", f"Unknown action kind: {kind!r}.")


def upsert_schedule_row(
    cfg: AppConfig,
    reminder_id: str,
    reminder: dict[str, Any],
    *,
    conn: sqlite3.Connection | None = None,
) -> str | None:
    if reminder.get("enabled") is False:
        _clear_schedule(cfg, reminder_id, conn=conn)
        return None
    schedule = reminder.get("schedule") or {}
    if schedule.get("kind") == "on_date_column":
        return None
    nxt = compute_next_run_at(
        schedule,
        tz_name=reminder.get("tz"),
        default_tz=cfg.timezone,
        now=_now_dt(cfg),
    )
    nxt_iso = nxt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ") if nxt else None
    own = conn is None
    if own:
        conn = connect(cfg.appdir)
    try:
        conn.execute(
            """
            INSERT INTO _schedules (spec_kind, spec_id, next_run_at, last_run_at, last_key, done)
            VALUES ('reminder', ?, ?, NULL, NULL, 0)
            ON CONFLICT(spec_kind, spec_id) DO UPDATE SET
                next_run_at = excluded.next_run_at,
                done = 0
            """,
            (reminder_id, nxt_iso),
        )
        if own:
            conn.commit()
    finally:
        if own:
            conn.close()
    return nxt_iso


def _clear_schedule(cfg: AppConfig, reminder_id: str, *, conn: sqlite3.Connection | None = None) -> None:
    own = conn is None
    if own:
        conn = connect(cfg.appdir)
    try:
        conn.execute(
            "UPDATE _schedules SET next_run_at = NULL, done = 1 WHERE spec_kind = 'reminder' AND spec_id = ?",
            (reminder_id,),
        )
        if own:
            conn.commit()
    finally:
        if own:
            conn.close()


def create_reminder(cfg: AppConfig, body: dict[str, Any]) -> dict[str, Any]:
    validate_reminder_object(body)
    schema = read_or_create_schema(cfg.appdir)
    if _find_reminder(schema, body["id"]):
        raise ValidationError("duplicate_reminder", f"Reminder {body['id']!r} already exists.")
    from app.final_schema import merge_final_schema

    merged = merge_final_schema(schema, {"add_reminders": [body]})
    merged["version"] = int(schema.get("version") or 0) + 1
    schema_path(cfg.appdir).write_text(json.dumps(merged, indent=2) + "\n", encoding="utf-8")
    rem = _find_reminder(merged, body["id"]) or body
    nxt = upsert_schedule_row(cfg, body["id"], rem)
    return reminder_view(cfg, rem, next_run_at=nxt)


def update_reminder(cfg: AppConfig, rid: str, patch: dict[str, Any]) -> dict[str, Any]:
    schema = read_or_create_schema(cfg.appdir)
    existing = _find_reminder(schema, rid)
    if not existing:
        raise ValidationError("not_found", f"Reminder {rid!r} not found.")
    merged_item = {**existing, **patch, "id": rid}
    validate_reminder_object(merged_item, is_update=True)
    from app.final_schema import merge_final_schema

    merged = merge_final_schema(schema, {"update_reminders": [merged_item]})
    merged["version"] = int(schema.get("version") or 0) + 1
    schema_path(cfg.appdir).write_text(json.dumps(merged, indent=2) + "\n", encoding="utf-8")
    rem = _find_reminder(merged, rid) or merged_item
    if rem.get("enabled") is False:
        _clear_schedule(cfg, rid)
        nxt = None
    else:
        nxt = upsert_schedule_row(cfg, rid, rem)
    return reminder_view(cfg, rem, next_run_at=nxt)


def reminder_view(cfg: AppConfig, rem: dict[str, Any], *, next_run_at: str | None = None) -> dict[str, Any]:
    if next_run_at is None:
        conn = connect(cfg.appdir)
        try:
            cur = conn.execute(
                "SELECT next_run_at FROM _schedules WHERE spec_kind = 'reminder' AND spec_id = ?",
                (rem.get("id"),),
            )
            row = cur.fetchone()
            next_run_at = row[0] if row else None
        finally:
            conn.close()
    schedule = rem.get("schedule") or {}
    return {
        **rem,
        "schedule_summary": schedule_summary(schedule),
        "next_run_at": next_run_at,
    }


def list_reminders(cfg: AppConfig) -> list[dict[str, Any]]:
    schema = read_or_create_schema(cfg.appdir)
    items = []
    for rem in schema.get("reminders") or []:
        if isinstance(rem, dict) and rem.get("id"):
            items.append(reminder_view(cfg, rem))
    return items


def get_reminder(cfg: AppConfig, rid: str) -> dict[str, Any]:
    schema = read_or_create_schema(cfg.appdir)
    rem = _find_reminder(schema, rid)
    if not rem:
        raise ValidationError("not_found", f"Reminder {rid!r} not found.")
    return reminder_view(cfg, rem)


def snooze_reminder(cfg: AppConfig, rid: str, minutes: int) -> dict[str, Any]:
    if not isinstance(minutes, int) or minutes < 1 or minutes > MAX_SNOOZE_MINUTES:
        raise ValidationError("bad_snooze", f"minutes must be 1-{MAX_SNOOZE_MINUTES}.")
    get_reminder(cfg, rid)
    from datetime import timedelta

    now = datetime.now(timezone.utc)
    conn = connect(cfg.appdir)
    try:
        cur = conn.execute(
            "SELECT next_run_at FROM _schedules WHERE spec_kind = 'reminder' AND spec_id = ?",
            (rid,),
        )
        row = cur.fetchone()
        base = now
        if row and row[0]:
            try:
                base = max(now, datetime.fromisoformat(row[0].replace("Z", "+00:00")))
            except ValueError:
                base = now
        nxt = base + timedelta(minutes=minutes)
        nxt_iso = nxt.strftime("%Y-%m-%dT%H:%M:%SZ")
        conn.execute(
            "UPDATE _schedules SET next_run_at = ? WHERE spec_kind = 'reminder' AND spec_id = ?",
            (nxt_iso, rid),
        )
        conn.commit()
    finally:
        conn.close()
    schema = read_or_create_schema(cfg.appdir)
    rem = _find_reminder(schema, rid)
    return reminder_view(cfg, rem or {"id": rid}, next_run_at=nxt_iso)


def dismiss_reminder(cfg: AppConfig, rid: str) -> dict[str, Any]:
    return update_reminder(cfg, rid, {"enabled": False})


def fire_reminder(cfg: AppConfig, reminder_id: str, *, conn: sqlite3.Connection | None = None) -> bool:
    schema = read_or_create_schema(cfg.appdir)
    rem = _find_reminder(schema, reminder_id)
    if not rem or rem.get("enabled") is False:
        return False
    action = rem.get("action") or {"kind": "notify"}
    title = rem.get("title") or "Reminder"
    body = rem.get("body")
    if action.get("kind") == "email":
        from app.rules import try_send_email

        if not try_send_email(cfg, action.get("to"), title, body or ""):
            insert_notice(
                cfg.appdir,
                title=title,
                body=(body or "") + " (email skipped: SMTP not configured)",
                reminder_id=reminder_id,
                conn=conn,
            )
    else:
        insert_notice(
            cfg.appdir,
            title=title,
            body=body,
            reminder_id=reminder_id,
            conn=conn,
        )
    schedule = rem.get("schedule") or {}
    own = conn is None
    if own:
        conn = connect(cfg.appdir)
    try:
        if schedule.get("kind") == "once":
            conn.execute(
                "UPDATE _schedules SET next_run_at = NULL, last_run_at = ?, done = 1 WHERE spec_kind = 'reminder' AND spec_id = ?",
                (_now_iso(), reminder_id),
            )
            schema_file = schema_path(cfg.appdir)
            fresh = read_or_create_schema(cfg.appdir)
            rem_obj = _find_reminder(fresh, reminder_id)
            if rem_obj:
                rem_obj["enabled"] = False
                fresh["version"] = int(fresh.get("version") or 0) + 1
                schema_file.write_text(json.dumps(fresh, indent=2) + "\n", encoding="utf-8")
        else:
            nxt = compute_next_run_at(
                schedule,
                tz_name=rem.get("tz"),
                default_tz=cfg.timezone,
                now=_now_dt(cfg),
                last_run_at=_now_dt(cfg),
            )
            nxt_iso = nxt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ") if nxt else None
            conn.execute(
                "UPDATE _schedules SET next_run_at = ?, last_run_at = ? WHERE spec_kind = 'reminder' AND spec_id = ?",
                (nxt_iso, _now_iso(), reminder_id),
            )
        if own:
            conn.commit()
    finally:
        if own:
            conn.close()
    return True


def fire_due_reminders(cfg: AppConfig, *, limit: int = 50) -> int:
    now_iso = _now_iso()
    conn = connect(cfg.appdir)
    fired = 0
    try:
        cur = conn.execute(
            """
            SELECT spec_id FROM _schedules
            WHERE spec_kind = 'reminder' AND done = 0 AND next_run_at IS NOT NULL AND next_run_at <= ?
            ORDER BY next_run_at LIMIT ?
            """,
            (now_iso, limit),
        )
        ids = [row[0] for row in cur.fetchall()]
        for rid in ids:
            if fire_reminder(cfg, rid, conn=conn):
                fired += 1
        conn.commit()
    finally:
        conn.close()
    return fired
