"""Scheduled jobs: whitelist kinds only."""

from __future__ import annotations

import copy
import json
import sqlite3
from datetime import datetime, timezone
from typing import Any

from app.config import AppConfig, read_or_create_schema, schema_path
from app.host_db import connect
from app.schedules import compute_next_run_at, validate_schedule
from app.schedules import compute_next_run_at, validate_schedule
from app.schema_validate import NAME_RE, ValidationError

JOB_KINDS = frozenset({"run_rules", "due_reminders", "sync_pull", "expire_sessions"})
JOB_KEYS = {"id", "kind", "enabled", "schedule", "tz"}
DEFAULT_JOBS = (
    {"id": "due_reminders", "kind": "due_reminders", "enabled": True, "schedule": {"kind": "interval", "every_seconds": 60}},
    {"id": "run_rules", "kind": "run_rules", "enabled": True, "schedule": {"kind": "interval", "every_seconds": 60}},
    {"id": "expire_sessions", "kind": "expire_sessions", "enabled": True, "schedule": {"kind": "interval", "every_seconds": 3600}},
)


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def validate_job(obj: dict[str, Any]) -> None:
    if not isinstance(obj, dict):
        raise ValidationError("bad_job", "Job must be an object.")
    extra = set(obj) - JOB_KEYS
    if extra:
        raise ValidationError("unknown_key", f"Job has unknown keys: {sorted(extra)}.")
    jid = obj.get("id")
    if not isinstance(jid, str) or not NAME_RE.match(jid):
        raise ValidationError("bad_job", "Job id must be snake_case.")
    kind = obj.get("kind")
    if kind not in JOB_KINDS:
        raise ValidationError("bad_job", f"Unknown job kind: {kind!r}.")
    schedule = obj.get("schedule")
    if not isinstance(schedule, dict):
        raise ValidationError("bad_job", "schedule is required.")
    validate_schedule(schedule, allow_on_date_column=False)


def ensure_default_jobs(cfg: AppConfig) -> None:
    schema = read_or_create_schema(cfg.appdir)
    jobs = schema.get("jobs")
    if isinstance(jobs, list) and jobs:
        return
    out = copy.deepcopy(schema)
    out["jobs"] = [dict(j) for j in DEFAULT_JOBS]
    out["version"] = int(out.get("version") or 0) + 1
    schema_path(cfg.appdir).write_text(json.dumps(out, indent=2) + "\n", encoding="utf-8")
    for job in out["jobs"]:
        upsert_job_schedule(cfg, job["id"], job)


def upsert_job_schedule(cfg: AppConfig, job_id: str, job: dict[str, Any], *, conn: sqlite3.Connection | None = None) -> None:
    if job.get("enabled") is False:
        return
    nxt = compute_next_run_at(
        job["schedule"],
        tz_name=job.get("tz"),
        default_tz=cfg.timezone,
    )
    nxt_iso = nxt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ") if nxt else None
    own = conn is None
    if own:
        conn = connect(cfg.appdir)
    try:
        conn.execute(
            """
            INSERT INTO _schedules (spec_kind, spec_id, next_run_at, done)
            VALUES ('job', ?, ?, 0)
            ON CONFLICT(spec_kind, spec_id) DO UPDATE SET next_run_at = excluded.next_run_at
            """,
            (job_id, nxt_iso),
        )
        if own:
            conn.commit()
    finally:
        if own:
            conn.close()


def apply_job_diff(cfg: AppConfig, diff: dict[str, Any]) -> list[str]:
    changed: list[str] = []
    add = diff.get("add_jobs") or []
    disable = diff.get("disable_jobs") or []
    if not add and not disable:
        return changed
    schema = read_or_create_schema(cfg.appdir)
    out = copy.deepcopy(schema)
    out.setdefault("jobs", [])
    for item in add:
        validate_job(item)
        found = False
        for idx, existing in enumerate(out["jobs"]):
            if isinstance(existing, dict) and existing.get("id") == item["id"]:
                out["jobs"][idx] = {**existing, **item}
                found = True
                break
        if not found:
            new_item = dict(item)
            new_item.setdefault("enabled", True)
            out["jobs"].append(new_item)
        changed.append(item["id"])
    id_set = set(str(x) for x in disable)
    for item in out["jobs"]:
        if isinstance(item, dict) and item.get("id") in id_set:
            item["enabled"] = False
            changed.append(item["id"])
    out["version"] = int(out.get("version") or 0) + 1
    schema_path(cfg.appdir).write_text(json.dumps(out, indent=2) + "\n", encoding="utf-8")
    for jid in set(changed):
        job = next((j for j in out["jobs"] if isinstance(j, dict) and j.get("id") == jid), None)
        if job and job.get("enabled") is not False:
            upsert_job_schedule(cfg, jid, job)
    return changed


def _find_job(schema: dict[str, Any], jid: str) -> dict[str, Any] | None:
    for item in schema.get("jobs") or []:
        if isinstance(item, dict) and item.get("id") == jid:
            return item
    return None


def run_job(cfg: AppConfig, job_id: str) -> tuple[bool, str]:
    schema = read_or_create_schema(cfg.appdir)
    job = _find_job(schema, job_id)
    if not job or job.get("enabled") is False:
        return False, "disabled"
    kind = job.get("kind")
    started = _now_iso()
    ok, message = True, "ok"
    try:
        if kind == "due_reminders":
            from app.reminders import fire_due_reminders

            n = fire_due_reminders(cfg)
            message = f"fired {n} reminders"
        elif kind == "run_rules":
            from app.rules import run_scheduled_rules

            n = run_scheduled_rules(cfg)
            message = f"ran rules on {n} rows"
        elif kind == "sync_pull":
            from app.sync import pull_peer

            message = pull_peer(cfg)
        elif kind == "expire_sessions":
            from app.auth import expire_sessions

            n = expire_sessions(cfg)
            message = f"expired {n} sessions"
        else:
            ok, message = False, f"unknown kind {kind!r}"
    except Exception as exc:
        ok, message = False, str(exc)

    finished = _now_iso()
    conn = connect(cfg.appdir)
    try:
        conn.execute(
            "INSERT INTO _job_runs (job_id, started_at, finished_at, ok, message) VALUES (?, ?, ?, ?, ?)",
            (job_id, started, finished, 1 if ok else 0, message),
        )
        nxt = compute_next_run_at(
            job["schedule"],
            tz_name=job.get("tz"),
            default_tz=cfg.timezone,
            last_run_at=datetime.now(timezone.utc),
        )
        nxt_iso = nxt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ") if nxt else None
        conn.execute(
            "UPDATE _schedules SET next_run_at = ?, last_run_at = ? WHERE spec_kind = 'job' AND spec_id = ?",
            (nxt_iso, finished, job_id),
        )
        conn.commit()
    finally:
        conn.close()
    return ok, message


def fire_due_jobs(cfg: AppConfig, *, limit: int = 50) -> int:
    now_iso = _now_iso()
    conn = connect(cfg.appdir)
    ran = 0
    try:
        cur = conn.execute(
            """
            SELECT spec_id FROM _schedules
            WHERE spec_kind = 'job' AND done = 0 AND next_run_at IS NOT NULL AND next_run_at <= ?
            ORDER BY next_run_at LIMIT ?
            """,
            (now_iso, limit),
        )
        for (job_id,) in cur.fetchall():
            run_job(cfg, job_id)
            ran += 1
    finally:
        conn.close()
    return ran
