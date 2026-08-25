"""Host SQLite tables. Not user schema."""

from __future__ import annotations

import json
import sqlite3
import uuid
from pathlib import Path
from typing import Any

from app.db_paths import db_path

REPLICA_FILE = "replica.json"

HOST_DDL = (
    """
    CREATE TABLE IF NOT EXISTS _users (
        id INTEGER PRIMARY KEY,
        name TEXT NOT NULL UNIQUE,
        password_hash TEXT NOT NULL,
        role TEXT NOT NULL DEFAULT 'owner',
        created_at TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS _sessions (
        token_hash TEXT PRIMARY KEY,
        user_id INTEGER NOT NULL,
        expires_at TEXT NOT NULL,
        FOREIGN KEY (user_id) REFERENCES _users(id)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS _notices (
        id INTEGER PRIMARY KEY,
        user_id INTEGER,
        title TEXT NOT NULL,
        body TEXT,
        rule_id TEXT,
        reminder_id TEXT,
        row_id INTEGER,
        read_at TEXT,
        created_at TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS _sync_events (
        id INTEGER PRIMARY KEY,
        replica_id TEXT NOT NULL,
        seq INTEGER NOT NULL,
        table_name TEXT NOT NULL,
        row_id INTEGER NOT NULL,
        column_name TEXT NOT NULL,
        value_json TEXT,
        at TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS _sync_applied (
        remote_replica TEXT PRIMARY KEY,
        last_seq INTEGER NOT NULL DEFAULT 0
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS _import_runs (
        id INTEGER PRIMARY KEY,
        profile_id TEXT NOT NULL,
        ok_count INTEGER NOT NULL DEFAULT 0,
        fail_count INTEGER NOT NULL DEFAULT 0,
        log_json TEXT,
        created_at TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS _schedules (
        id INTEGER PRIMARY KEY,
        spec_kind TEXT NOT NULL,
        spec_id TEXT NOT NULL,
        next_run_at TEXT,
        last_run_at TEXT,
        last_key TEXT,
        done INTEGER NOT NULL DEFAULT 0,
        UNIQUE(spec_kind, spec_id)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS _job_runs (
        id INTEGER PRIMARY KEY,
        job_id TEXT NOT NULL,
        started_at TEXT NOT NULL,
        finished_at TEXT,
        ok INTEGER NOT NULL DEFAULT 1,
        message TEXT
    )
    """,
)


def replica_path(appdir: Path) -> Path:
    return appdir / REPLICA_FILE


def read_replica(appdir: Path) -> dict[str, Any]:
    path = replica_path(appdir)
    if not path.is_file():
        return ensure_replica(appdir)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return ensure_replica(appdir)
    if not isinstance(data, dict):
        return ensure_replica(appdir)
    data.setdefault("replica_id", str(uuid.uuid4()))
    data.setdefault("last_seq", 0)
    return data


def ensure_replica(appdir: Path) -> dict[str, Any]:
    path = replica_path(appdir)
    if path.is_file():
        return read_replica(appdir)
    payload = {"replica_id": str(uuid.uuid4()), "last_seq": 0}
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return payload


def ensure_host_tables(appdir: Path) -> None:
    conn = sqlite3.connect(str(db_path(appdir)))
    try:
        for ddl in HOST_DDL:
            conn.execute(ddl)
        conn.commit()
    finally:
        conn.close()
    ensure_replica(appdir)


def connect(appdir: Path) -> sqlite3.Connection:
    return sqlite3.connect(str(db_path(appdir)))
