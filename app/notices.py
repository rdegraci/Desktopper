"""In-app notices from rules, reminders, or the host."""

from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from typing import Any

from app.host_db import connect


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def insert_notice(
    appdir,
    *,
    title: str,
    body: str | None = None,
    user_id: int | None = None,
    rule_id: str | None = None,
    reminder_id: str | None = None,
    row_id: int | None = None,
    conn: sqlite3.Connection | None = None,
) -> int:
    own = conn is None
    if own:
        conn = connect(appdir)
    try:
        cur = conn.execute(
            """
            INSERT INTO _notices (user_id, title, body, rule_id, reminder_id, row_id, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (user_id, title, body, rule_id, reminder_id, row_id, _now_iso()),
        )
        if own:
            conn.commit()
        return int(cur.lastrowid)
    finally:
        if own:
            conn.close()


def list_notices(appdir, *, user_id: int | None = None, unread_only: bool = False) -> list[dict[str, Any]]:
    conn = connect(appdir)
    try:
        clauses = []
        params: list[Any] = []
        if user_id is not None:
            clauses.append("(user_id IS NULL OR user_id = ?)")
            params.append(user_id)
        if unread_only:
            clauses.append("read_at IS NULL")
        where = (" WHERE " + " AND ".join(clauses)) if clauses else ""
        cur = conn.execute(
            f"""
            SELECT id, user_id, title, body, rule_id, reminder_id, row_id, read_at, created_at
            FROM _notices{where}
            ORDER BY created_at DESC
            """,
            params,
        )
        rows = []
        for row in cur.fetchall():
            rows.append(
                {
                    "id": row[0],
                    "user_id": row[1],
                    "title": row[2],
                    "body": row[3],
                    "rule_id": row[4],
                    "reminder_id": row[5],
                    "row_id": row[6],
                    "read_at": row[7],
                    "created_at": row[8],
                    "unread": row[7] is None,
                }
            )
        return rows
    finally:
        conn.close()


def mark_read(appdir, notice_id: int) -> bool:
    conn = connect(appdir)
    try:
        cur = conn.execute(
            "UPDATE _notices SET read_at = ? WHERE id = ? AND read_at IS NULL",
            (_now_iso(), notice_id),
        )
        conn.commit()
        return cur.rowcount > 0
    finally:
        conn.close()


def has_recent_notice(
    appdir,
    *,
    rule_id: str,
    row_id: int,
    hours: int = 24,
    conn: sqlite3.Connection | None = None,
) -> bool:
    own = conn is None
    if own:
        conn = connect(appdir)
    try:
        cur = conn.execute(
            """
            SELECT 1 FROM _notices
            WHERE rule_id = ? AND row_id = ? AND read_at IS NULL
              AND created_at >= datetime('now', ?)
            LIMIT 1
            """,
            (rule_id, row_id, f"-{hours} hours"),
        )
        return cur.fetchone() is not None
    finally:
        if own:
            conn.close()
