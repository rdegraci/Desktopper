"""Bound-parameter CRUD for schema user tables."""

from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from typing import Any

from app.config import AppConfig, read_or_create_schema
from app.db_paths import db_path
from app.hooks import HookError, run_hooks
from app.log import emit
from app.schema_validate import NAME_RE, SYSTEM_COLUMNS

WRITE_SKIP = {"id"}


class CrudError(Exception):
    def __init__(self, status: int, msg: str) -> None:
        super().__init__(msg)
        self.status = status
        self.msg = msg


def _quote_ident(name: str) -> str:
    if not NAME_RE.match(name):
        raise CrudError(400, "Bad identifier.")
    return '"' + name + '"'


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _tables(schema: dict[str, Any]) -> dict[str, Any]:
    tables = schema.get("tables") or {}
    if not isinstance(tables, dict):
        return {}
    return tables


def _require_table(schema: dict[str, Any], name: str) -> dict[str, Any]:
    if not isinstance(name, str) or not NAME_RE.match(name):
        raise CrudError(404, "Table not found.")
    table = _tables(schema).get(name)
    if not isinstance(table, dict):
        raise CrudError(404, "Table not found.")
    return table


def _columns(table: dict[str, Any]) -> list[dict[str, Any]]:
    cols = table.get("columns") or []
    if not isinstance(cols, list):
        return []
    return [c for c in cols if isinstance(c, dict) and NAME_RE.match(str(c.get("name") or ""))]


def _writable(table: dict[str, Any]) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    for col in _columns(table):
        name = col["name"]
        if name in WRITE_SKIP:
            continue
        if name in ("created_at", "updated_at"):
            continue
        if col.get("hidden"):
            continue
        out[name] = col
    return out


def _coerce(col: dict[str, Any], value: Any) -> Any:
    if value is None:
        if col.get("nullable", True):
            return None
        raise CrudError(400, f"Column {col['name']} is required.")
    typ = col.get("type")
    widget = col.get("widget")
    if widget == "checkbox":
        if isinstance(value, bool):
            return 1 if value else 0
        if value in (0, 1, "0", "1"):
            return int(value)
        raise CrudError(400, f"Column {col['name']} must be 0 or 1.")
    if typ == "INTEGER":
        if isinstance(value, bool):
            raise CrudError(400, f"Column {col['name']} must be an integer.")
        if isinstance(value, int):
            return value
        if isinstance(value, str) and value.lstrip("-").isdigit():
            return int(value)
        raise CrudError(400, f"Column {col['name']} must be an integer.")
    if typ == "REAL":
        if isinstance(value, bool):
            raise CrudError(400, f"Column {col['name']} must be a number.")
        if isinstance(value, (int, float)):
            return float(value)
        try:
            return float(value)
        except (TypeError, ValueError):
            raise CrudError(400, f"Column {col['name']} must be a number.") from None
    if typ == "TEXT":
        if isinstance(value, str):
            return value
        raise CrudError(400, f"Column {col['name']} must be text.")
    raise CrudError(400, f"Column {col['name']} has a bad type.")


def _pick_fields(table: dict[str, Any], body: dict[str, Any]) -> dict[str, Any]:
    writable = _writable(table)
    out: dict[str, Any] = {}
    if not isinstance(body, dict):
        raise CrudError(400, "Body must be a JSON object.")
    for key, value in body.items():
        if key not in writable:
            continue
        out[key] = _coerce(writable[key], value)
    return out


def _row_to_dict(cursor: sqlite3.Cursor, row: sqlite3.Row) -> dict[str, Any]:
    return {cursor.description[i][0]: row[i] for i in range(len(row))}


def _connect(cfg: AppConfig) -> sqlite3.Connection:
    conn = sqlite3.connect(str(db_path(cfg.appdir)))
    conn.row_factory = sqlite3.Row
    return conn


def _select_sql(table_name: str, table: dict[str, Any]) -> str:
    names = [c["name"] for c in _columns(table)]
    if "id" not in names:
        names.insert(0, "id")
    cols = ", ".join(_quote_ident(n) for n in names)
    return f"SELECT {cols} FROM {_quote_ident(table_name)}"


def list_rows(
    cfg: AppConfig,
    table_name: str,
    *,
    limit: int = 50,
    offset: int = 0,
) -> list[dict[str, Any]]:
    schema = read_or_create_schema(cfg.appdir)
    table = _require_table(schema, table_name)
    limit = max(1, min(int(limit), 200))
    offset = max(0, int(offset))
    sql = _select_sql(table_name, table) + " ORDER BY " + _quote_ident("id") + " LIMIT ? OFFSET ?"
    conn = _connect(cfg)
    try:
        cur = conn.execute(sql, (limit, offset))
        return [_row_to_dict(cur, row) for row in cur.fetchall()]
    finally:
        conn.close()


def _get_row_conn(
    conn: sqlite3.Connection,
    schema: dict[str, Any],
    table_name: str,
    row_id: int,
) -> dict[str, Any]:
    table = _require_table(schema, table_name)
    sql = _select_sql(table_name, table) + " WHERE " + _quote_ident("id") + " = ?"
    cur = conn.execute(sql, (row_id,))
    row = cur.fetchone()
    if row is None:
        raise CrudError(404, "Row not found.")
    return _row_to_dict(cur, row)


def get_row(cfg: AppConfig, table_name: str, row_id: int) -> dict[str, Any]:
    schema = read_or_create_schema(cfg.appdir)
    conn = _connect(cfg)
    try:
        return _get_row_conn(conn, schema, table_name, row_id)
    finally:
        conn.close()


def insert_row(
    cfg: AppConfig,
    table_name: str,
    body: dict[str, Any],
    *,
    request_id: str | None = None,
    depth: int = 0,
) -> dict[str, Any]:
    schema = read_or_create_schema(cfg.appdir)
    table = _require_table(schema, table_name)
    fields = _pick_fields(table, body)
    now = _now()
    fields["created_at"] = now
    fields["updated_at"] = now
    names = list(fields.keys())
    placeholders = ", ".join("?" for _ in names)
    col_sql = ", ".join(_quote_ident(n) for n in names)
    sql = (
        f"INSERT INTO {_quote_ident(table_name)} ({col_sql}) VALUES ({placeholders})"
    )
    conn = _connect(cfg)
    new_id = 0
    try:
        conn.execute("BEGIN")
        cur = conn.execute(sql, tuple(fields[n] for n in names))
        new_id = int(cur.lastrowid)
        row = _get_row_conn(conn, schema, table_name, new_id)
        try:
            run_hooks(
                cfg,
                conn=conn,
                table=table_name,
                event="create",
                row=row,
                depth=depth,
                request_id=request_id,
            )
            from app.rules import run_on_write_rules
            from app.sync import append_row_sync

            run_on_write_rules(cfg, table_name, row, conn=conn)
            append_row_sync(cfg, table_name, new_id, {k: row[k] for k in fields if k in row}, conn=conn)
        except HookError as exc:
            conn.rollback()
            raise CrudError(500, f"Hook {exc.hook_id} failed: {exc.msg}") from exc
        conn.commit()
    except CrudError:
        raise
    except sqlite3.Error as exc:
        conn.rollback()
        raise CrudError(500, "Insert failed.") from exc
    finally:
        conn.close()
    emit(
        cfg,
        event="crud.insert",
        component="crud",
        msg=f"Inserted {table_name} {new_id}.",
        request_id=request_id,
        schema_version=int(schema.get("version") or 0),
        detail={"table": table_name, "id": new_id},
    )
    return get_row(cfg, table_name, new_id)


def update_row(
    cfg: AppConfig,
    table_name: str,
    row_id: int,
    body: dict[str, Any],
    *,
    request_id: str | None = None,
    depth: int = 0,
) -> dict[str, Any]:
    schema = read_or_create_schema(cfg.appdir)
    table = _require_table(schema, table_name)
    fields = _pick_fields(table, body)
    fields["updated_at"] = _now()
    names = list(fields.keys())
    assigns = ", ".join(_quote_ident(n) + " = ?" for n in names)
    sql = (
        f"UPDATE {_quote_ident(table_name)} SET {assigns} WHERE "
        + _quote_ident("id")
        + " = ?"
    )
    params = tuple(fields[n] for n in names) + (row_id,)
    conn = _connect(cfg)
    try:
        conn.execute("BEGIN")
        row_before = _get_row_conn(conn, schema, table_name, row_id)
        conn.execute(sql, params)
        row_after = _get_row_conn(conn, schema, table_name, row_id)
        try:
            run_hooks(
                cfg,
                conn=conn,
                table=table_name,
                event="update",
                row=row_after,
                row_before=row_before,
                depth=depth,
                request_id=request_id,
            )
            from app.rules import run_on_write_rules
            from app.sync import append_row_sync

            run_on_write_rules(cfg, table_name, row_after, conn=conn)
            for key in fields:
                if key in row_after and row_before.get(key) != row_after.get(key):
                    append_row_sync(
                        cfg, table_name, row_id, {key: row_after[key]}, conn=conn
                    )
        except HookError as exc:
            conn.rollback()
            raise CrudError(500, f"Hook {exc.hook_id} failed: {exc.msg}") from exc
        conn.commit()
    except CrudError:
        raise
    except sqlite3.Error as exc:
        conn.rollback()
        raise CrudError(500, "Update failed.") from exc
    finally:
        conn.close()
    emit(
        cfg,
        event="crud.update",
        component="crud",
        msg=f"Updated {table_name} {row_id}.",
        request_id=request_id,
        schema_version=int(schema.get("version") or 0),
        detail={"table": table_name, "id": row_id},
    )
    return get_row(cfg, table_name, row_id)


def delete_row(
    cfg: AppConfig,
    table_name: str,
    row_id: int,
    *,
    request_id: str | None = None,
    depth: int = 0,
) -> None:
    schema = read_or_create_schema(cfg.appdir)
    _require_table(schema, table_name)
    sql = f"DELETE FROM {_quote_ident(table_name)} WHERE " + _quote_ident("id") + " = ?"
    conn = _connect(cfg)
    try:
        conn.execute("BEGIN")
        row_before = _get_row_conn(conn, schema, table_name, row_id)
        try:
            run_hooks(
                cfg,
                conn=conn,
                table=table_name,
                event="delete",
                row=row_before,
                row_before=row_before,
                depth=depth,
                request_id=request_id,
            )
        except HookError as exc:
            conn.rollback()
            raise CrudError(500, f"Hook {exc.hook_id} failed: {exc.msg}") from exc
        conn.execute(sql, (row_id,))
        from app.sync import append_sync_event

        append_sync_event(
            cfg, table=table_name, row_id=row_id, column="_deleted", value=1, conn=conn
        )
        conn.commit()
    except CrudError:
        raise
    except sqlite3.Error as exc:
        conn.rollback()
        raise CrudError(500, "Delete failed.") from exc
    finally:
        conn.close()
    emit(
        cfg,
        event="crud.delete",
        component="crud",
        msg=f"Deleted {table_name} {row_id}.",
        request_id=request_id,
        schema_version=int(schema.get("version") or 0),
        detail={"table": table_name, "id": row_id},
    )


def _display_column(schema: dict[str, Any], table_name: str, table: dict[str, Any]) -> str:
    for screen in schema.get("screens") or []:
        if not isinstance(screen, dict):
            continue
        if screen.get("table") == table_name and screen.get("type") == "list":
            cols = screen.get("columns") or []
            if cols and isinstance(cols[0], str) and NAME_RE.match(cols[0]):
                return cols[0]
    for col in _columns(table):
        if col.get("hidden"):
            continue
        if col["name"] in SYSTEM_COLUMNS:
            continue
        if col.get("type") == "TEXT":
            return col["name"]
    return "id"


def list_options(cfg: AppConfig, table_name: str) -> list[dict[str, Any]]:
    schema = read_or_create_schema(cfg.appdir)
    table = _require_table(schema, table_name)
    display = _display_column(schema, table_name, table)
    sql = (
        "SELECT "
        + _quote_ident("id")
        + " AS id, "
        + _quote_ident(display)
        + " AS label FROM "
        + _quote_ident(table_name)
        + " ORDER BY "
        + _quote_ident("id")
    )
    conn = _connect(cfg)
    try:
        cur = conn.execute(sql)
        out = []
        for row in cur.fetchall():
            out.append({"id": row["id"], "label": row["label"]})
        return out
    finally:
        conn.close()
