"""Change log sync between replicas."""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.config import AppConfig, read_or_create_schema
from app.host_db import connect, read_replica
from app.notices import insert_notice

SYNC_OUT = "sync_out"
SYNC_IN = "sync_in"
TOMBSTONE = "_deleted"


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _sync_tables(schema: dict[str, Any]) -> list[str]:
    sync = schema.get("sync") or {}
    tables = sync.get("tables") or []
    return [t for t in tables if isinstance(t, str)]


def should_sync_table(schema: dict[str, Any], table: str) -> bool:
    return table in _sync_tables(schema)


def append_sync_event(
    cfg: AppConfig,
    *,
    table: str,
    row_id: int,
    column: str,
    value: Any,
    conn=None,
) -> None:
    schema = read_or_create_schema(cfg.appdir)
    if not should_sync_table(schema, table):
        return
    replica = read_replica(cfg.appdir)
    replica_id = replica["replica_id"]
    seq = int(replica.get("last_seq", 0)) + 1
    replica["last_seq"] = seq
    from app.host_db import replica_path

    replica_path(cfg.appdir).write_text(json.dumps(replica, indent=2) + "\n", encoding="utf-8")
    own = conn is None
    if own:
        conn = connect(cfg.appdir)
    try:
        conn.execute(
            """
            INSERT INTO _sync_events (replica_id, seq, table_name, row_id, column_name, value_json, at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (replica_id, seq, table, row_id, column, json.dumps(value), _now_iso()),
        )
        if own:
            conn.commit()
    finally:
        if own:
            conn.close()


def append_row_sync(cfg: AppConfig, table: str, row_id: int, fields: dict[str, Any], *, conn=None) -> None:
    for col, val in fields.items():
        append_sync_event(cfg, table=table, row_id=row_id, column=col, value=val, conn=conn)


def sync_status(cfg: AppConfig) -> dict[str, Any]:
    replica = read_replica(cfg.appdir)
    conn = connect(cfg.appdir)
    try:
        cur = conn.execute("SELECT COUNT(*) FROM _sync_events")
        pending = int(cur.fetchone()[0])
    finally:
        conn.close()
    return {"replica_id": replica["replica_id"], "last_seq": replica.get("last_seq", 0), "pending": pending}


def export_events(cfg: AppConfig) -> dict[str, Any]:
    replica = read_replica(cfg.appdir)
    conn = connect(cfg.appdir)
    try:
        cur = conn.execute(
            "SELECT replica_id, seq, table_name, row_id, column_name, value_json, at FROM _sync_events ORDER BY id"
        )
        events = []
        for row in cur.fetchall():
            events.append(
                {
                    "replica_id": row[0],
                    "seq": row[1],
                    "table": row[2],
                    "row_id": row[3],
                    "column": row[4],
                    "value": json.loads(row[5]) if row[5] is not None else None,
                    "at": row[6],
                }
            )
    finally:
        conn.close()
    out_dir = cfg.appdir / SYNC_OUT
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    path = out_dir / f"events_{stamp}.json"
    payload = {"replica_id": replica["replica_id"], "events": events}
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return {"path": str(path), "count": len(events)}


def apply_events(cfg: AppConfig, events: list[dict[str, Any]]) -> dict[str, Any]:
    from app.db_paths import quote_ident as _quote_ident

    applied = 0
    skipped = 0
    conn = connect(cfg.appdir)
    try:
        for ev in events:
            remote = ev.get("replica_id")
            seq = ev.get("seq")
            table = ev.get("table")
            row_id = ev.get("row_id")
            column = ev.get("column")
            value = ev.get("value")
            at = ev.get("at")
            if not all([remote, seq, table, row_id, column, at]):
                skipped += 1
                continue
            cur = conn.execute(
                "SELECT last_seq FROM _sync_applied WHERE remote_replica = ?",
                (remote,),
            )
            row = cur.fetchone()
            last = int(row[0]) if row else 0
            if int(seq) <= last:
                skipped += 1
                continue
            if column == TOMBSTONE:
                conn.execute(f"DELETE FROM {_quote_ident(table)} WHERE id = ?", (row_id,))
            else:
                cur2 = conn.execute(f"SELECT {_quote_ident(column)} FROM {_quote_ident(table)} WHERE id = ?", (row_id,))
                existing = cur2.fetchone()
                if existing is None:
                    conn.execute(
                        f"INSERT INTO {_quote_ident(table)} (id, {_quote_ident(column)}) VALUES (?, ?)",
                        (row_id, value),
                    )
                else:
                    conn.execute(
                        f"UPDATE {_quote_ident(table)} SET {_quote_ident(column)} = ? WHERE id = ?",
                        (value, row_id),
                    )
            conn.execute(
                """
                INSERT INTO _sync_applied (remote_replica, last_seq) VALUES (?, ?)
                ON CONFLICT(remote_replica) DO UPDATE SET last_seq = excluded.last_seq
                """,
                (remote, int(seq)),
            )
            applied += 1
        conn.commit()
    finally:
        conn.close()
    return {"applied": applied, "skipped": skipped}


def import_batch(cfg: AppConfig, payload: dict[str, Any]) -> dict[str, Any]:
    events = payload.get("events") or []
    if not isinstance(events, list):
        raise ValueError("events must be a list")
    return apply_events(cfg, events)


def pull_peer(cfg: AppConfig) -> str:
    url = os.environ.get("SYNC_PEER_URL", "").strip()
    if not url:
        return "no peer configured"
    import urllib.request

    req = urllib.request.Request(url.rstrip("/") + "/api/sync/export", method="GET")
    with urllib.request.urlopen(req, timeout=30) as resp:
        payload = json.loads(resp.read().decode("utf-8"))
    result = import_batch(cfg, payload)
    return f"pulled {result['applied']} events"
