"""Apply validated spec diffs to SQLite and schema.json."""

from __future__ import annotations

import copy
import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.config import AppConfig, read_or_create_schema, schema_path
from app.final_schema import apply_final_side_effects, merge_final_schema
from app.hooks import apply_hook_diff, read_registry
from app.db_paths import DB_NAME, db_path, quote_ident as _quote_ident
from app.log import emit
from app.schema_validate import SYSTEM_COLUMNS, ValidationError, validate_diff

BACKUP_NAME = "schema.json.bak"


class EngineError(Exception):
    def __init__(self, error_code: str, msg: str) -> None:
        super().__init__(msg)
        self.error_code = error_code
        self.msg = msg


def _sql_type(col: dict[str, Any]) -> str:
    return str(col.get("type") or "TEXT")


def _default_sql(col: dict[str, Any]) -> str:
    if "default" not in col:
        return ""
    value = col["default"]
    if value is None:
        return " DEFAULT NULL"
    if isinstance(value, bool):
        return f" DEFAULT {1 if value else 0}"
    if isinstance(value, int):
        return f" DEFAULT {value}"
    if isinstance(value, float):
        return f" DEFAULT {value}"
    if isinstance(value, str):
        escaped = value.replace("'", "''")
        return f" DEFAULT '{escaped}'"
    return ""


def _create_table_sql(name: str, user_columns: list[dict[str, Any]]) -> str:
    parts = [
        f"{_quote_ident('id')} INTEGER PRIMARY KEY",
        f"{_quote_ident('created_at')} TEXT",
        f"{_quote_ident('updated_at')} TEXT",
    ]
    for col in user_columns:
        if col.get("name") in SYSTEM_COLUMNS:
            continue
        ident = _quote_ident(col["name"])
        typ = _sql_type(col)
        nullable = col.get("nullable", True)
        nn = "" if nullable else " NOT NULL"
        parts.append(f"{ident} {typ}{nn}{_default_sql(col)}")
    return f"CREATE TABLE {_quote_ident(name)} ({', '.join(parts)})"


def _alter_column_sql(table: str, col: dict[str, Any]) -> str:
    work = dict(col)
    if work.get("nullable") is False and "default" not in work:
        work["nullable"] = True
    ident = _quote_ident(work["name"])
    typ = _sql_type(work)
    nn = "" if work.get("nullable", True) else " NOT NULL"
    return (
        f"ALTER TABLE {_quote_ident(table)} ADD COLUMN {ident} {typ}{nn}{_default_sql(work)}"
    )


def _drop_column_sql(table: str, column: str) -> str:
    return f"ALTER TABLE {_quote_ident(table)} DROP COLUMN {_quote_ident(column)}"


def _strip_column_from_screens(schema: dict[str, Any], table: str, column: str) -> None:
    for screen in schema.get("screens") or []:
        if not isinstance(screen, dict):
            continue
        if screen.get("table") == table and isinstance(screen.get("columns"), list):
            screen["columns"] = [c for c in screen["columns"] if c != column]
        for grp in screen.get("groups") or []:
            if isinstance(grp, dict) and isinstance(grp.get("columns"), list):
                grp["columns"] = [c for c in grp["columns"] if c != column]
        kept_related = []
        for rel in screen.get("related") or []:
            if not isinstance(rel, dict):
                kept_related.append(rel)
                continue
            if rel.get("table") == table and rel.get("fk") == column:
                continue
            if isinstance(rel.get("columns"), list):
                rel["columns"] = [c for c in rel["columns"] if c != column]
            kept_related.append(rel)
        if "related" in screen:
            screen["related"] = kept_related
        if screen.get("table") == table and isinstance(screen.get("scopes"), list):
            screen["scopes"] = [
                s for s in screen["scopes"] if not isinstance(s, dict) or s.get("column") != column
            ]


def _system_column_defs() -> list[dict[str, Any]]:
    return [
        {
            "name": "id",
            "type": "INTEGER",
            "pk": True,
            "nullable": False,
            "hidden": True,
        },
        {"name": "created_at", "type": "TEXT", "hidden": True, "nullable": True},
        {"name": "updated_at", "type": "TEXT", "hidden": True, "nullable": True},
    ]


def _merge_schema(schema: dict[str, Any], diff: dict[str, Any]) -> dict[str, Any]:
    out = copy.deepcopy(schema)
    if not isinstance(out.get("tables"), dict):
        out["tables"] = {}
    if not isinstance(out.get("screens"), list):
        out["screens"] = []
    if not isinstance(out.get("app"), dict):
        out["app"] = {"title": "Desktopper"}

    app = diff.get("app")
    if isinstance(app, dict):
        if app.get("title"):
            out["app"]["title"] = app["title"]
        if app.get("prompt"):
            out["app"]["prompt"] = app["prompt"]
        if app.get("home"):
            out["app"]["home"] = app["home"]

    for item in diff.get("add_tables") or []:
        cols = _system_column_defs() + [
            copy.deepcopy(c)
            for c in (item.get("columns") or [])
            if isinstance(c, dict) and c.get("name") not in SYSTEM_COLUMNS
        ]
        out["tables"][item["name"]] = {
            "label": item.get("label", item["name"]),
            "hidden": bool(item.get("hidden", False)),
            "columns": cols,
        }
        if item.get("role") in ("primary", "lookup"):
            out["tables"][item["name"]]["role"] = item["role"]

    for item in diff.get("add_columns") or []:
        table = out["tables"][item["table"]]
        table.setdefault("columns", []).append(copy.deepcopy(item["column"]))

    for item in diff.get("update_tables") or []:
        table = out["tables"].get(item["name"])
        if not table:
            continue
        if "role" in item:
            table["role"] = item["role"]

    for item in diff.get("add_screens") or []:
        out["screens"].append(copy.deepcopy(item))

    for item in diff.get("update_screens") or []:
        sid = item.get("id")
        for screen in out["screens"]:
            if not isinstance(screen, dict) or screen.get("id") != sid:
                continue
            if "title" in item:
                screen["title"] = item["title"]
            if "columns" in item:
                screen["columns"] = copy.deepcopy(item["columns"])
            if "nav" in item:
                screen["nav"] = item["nav"]
            if "related" in item:
                screen["related"] = copy.deepcopy(item["related"])
            if "scopes" in item:
                screen["scopes"] = copy.deepcopy(item["scopes"])
            if "groups" in item:
                screen["groups"] = copy.deepcopy(item["groups"])
            if "empty" in item:
                screen["empty"] = item["empty"]
            break

    for item in diff.get("extend_enums") or []:
        for col in out["tables"][item["table"]].get("columns") or []:
            if col.get("name") != item["column"]:
                continue
            current = list(col.get("enum") or [])
            for val in item.get("add_values") or []:
                if val not in current:
                    current.append(val)
            col["enum"] = current

    for item in diff.get("update_columns") or []:
        table = out["tables"][item["table"]]
        for col in table.get("columns") or []:
            if col.get("name") != item["column"]:
                continue
            if "widget" in item:
                col["widget"] = item["widget"]
            if "label" in item:
                col["label"] = item["label"]
            if "nullable" in item:
                col["nullable"] = item["nullable"]
            if "enum" in item:
                col["enum"] = copy.deepcopy(item["enum"])
            break

    for item in diff.get("update_labels") or []:
        table = out["tables"][item["table"]]
        if "column" in item:
            for col in table.get("columns") or []:
                if col.get("name") == item["column"] and "label" in item:
                    col["label"] = item["label"]
        elif "label" in item:
            table["label"] = item["label"]

    for item in diff.get("hide_columns") or []:
        for col in out["tables"][item["table"]].get("columns") or []:
            if col.get("name") == item["column"]:
                col["hidden"] = True

    for item in diff.get("remove_columns") or []:
        tname = item["table"]
        cname = item["column"]
        table = out["tables"][tname]
        table["columns"] = [
            c for c in (table.get("columns") or []) if c.get("name") != cname
        ]
        _strip_column_from_screens(out, tname, cname)

    out = merge_final_schema(out, diff)

    out["version"] = int(out.get("version") or 0) + 1
    return out


def _write_migration(appdir: Path, version: int, summary: str, diff: dict[str, Any]) -> None:
    mig_dir = appdir / "migrations"
    mig_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    path = mig_dir / f"v{version}_{stamp}.json"
    payload = {
        "version": version,
        "timestamp": stamp,
        "summary": summary,
        "diff": diff,
    }
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def apply_diff(
    cfg: AppConfig,
    diff: dict[str, Any],
    *,
    request_id: str | None = None,
) -> dict[str, Any]:
    schema = read_or_create_schema(cfg.appdir)
    version_before = int(schema.get("version") or 0)
    hooks_registry = read_registry(cfg.appdir)
    try:
        validate_diff(schema, diff, hooks_registry=hooks_registry)
    except ValidationError as exc:
        emit(
            cfg,
            event="engine.validate.fail",
            component="engine",
            msg=exc.msg,
            ok=False,
            level="error",
            request_id=request_id,
            schema_version=version_before,
            detail={"error_code": exc.error_code},
        )
        raise
    emit(
        cfg,
        event="engine.validate.ok",
        component="engine",
        msg="Spec diff passed validation.",
        ok=True,
        request_id=request_id,
        schema_version=version_before,
        detail={"error_code": None},
    )

    schema_file = schema_path(cfg.appdir)
    backup = cfg.appdir / BACKUP_NAME
    backup.write_bytes(schema_file.read_bytes())

    conn = sqlite3.connect(str(db_path(cfg.appdir)))
    try:
        conn.execute("BEGIN")
        for item in diff.get("add_tables") or []:
            conn.execute(_create_table_sql(item["name"], item.get("columns") or []))
        for item in diff.get("add_columns") or []:
            conn.execute(_alter_column_sql(item["table"], item["column"]))
        for item in diff.get("remove_columns") or []:
            conn.execute(_drop_column_sql(item["table"], item["column"]))
        conn.commit()
    except sqlite3.Error as exc:
        conn.rollback()
        schema_file.write_bytes(backup.read_bytes())
        emit(
            cfg,
            event="engine.apply.fail",
            component="engine",
            msg="SQLite apply failed. Schema backup restored.",
            ok=False,
            level="error",
            request_id=request_id,
            schema_version=version_before,
            detail={"error_code": "io_error", "error": type(exc).__name__},
        )
        raise EngineError("io_error", "SQLite apply failed.") from exc
    finally:
        conn.close()

    merged = _merge_schema(schema, diff)
    schema_file.write_text(json.dumps(merged, indent=2) + "\n", encoding="utf-8")
    hooks_changed = apply_hook_diff(cfg, diff)
    apply_final_side_effects(cfg, diff)
    summary = str(diff.get("summary") or "Applied additive spec.")
    _write_migration(cfg.appdir, int(merged["version"]), summary, diff)
    emit(
        cfg,
        event="engine.apply.ok",
        component="engine",
        msg=summary if summary.endswith(".") else summary + ".",
        ok=True,
        request_id=request_id,
        schema_version=int(merged["version"]),
        detail={
            "error_code": None,
            "add_tables": [t.get("name") for t in (diff.get("add_tables") or [])],
            "add_columns": [
                f"{c.get('table')}.{c.get('column', {}).get('name')}"
                for c in (diff.get("add_columns") or [])
            ],
            "remove_columns": [
                f"{c.get('table')}.{c.get('column')}"
                for c in (diff.get("remove_columns") or [])
            ],
            "hooks_changed": hooks_changed,
        },
    )
    merged["_hooks_changed"] = hooks_changed
    return merged
