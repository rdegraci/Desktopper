"""CSV import with profiles."""

from __future__ import annotations

import csv
import io
import json
from datetime import datetime, timezone
from typing import Any

from app.config import AppConfig, read_or_create_schema
from app.db_paths import db_path, quote_ident as _quote_ident
from app.host_db import connect
from app.schema_validate import NAME_RE, ValidationError

PROFILE_KEYS = {
    "id",
    "table",
    "encoding",
    "delimiter",
    "header_row",
    "skip_rows",
    "quotechar",
    "decimal",
    "date_formats",
    "empty",
    "map",
    "duplicate_keys",
    "duplicate",
    "enabled",
}
MAX_FILE_BYTES = 5 * 1024 * 1024


def validate_profile(obj: dict[str, Any], schema: dict[str, Any]) -> None:
    if not isinstance(obj, dict):
        raise ValidationError("bad_profile", "Import profile must be an object.")
    extra = set(obj) - PROFILE_KEYS
    if extra:
        raise ValidationError("unknown_key", f"Profile has unknown keys: {sorted(extra)}.")
    pid = obj.get("id")
    if not isinstance(pid, str) or not NAME_RE.match(pid):
        raise ValidationError("bad_profile", "Profile id must be snake_case.")
    table = obj.get("table")
    if not isinstance(table, str) or table not in (schema.get("tables") or {}):
        raise ValidationError("bad_profile", "Profile requires a valid table.")
    dup = obj.get("duplicate", "skip")
    if dup not in ("skip", "update", "insert"):
        raise ValidationError("bad_profile", "duplicate must be skip, update, or insert.")


def _parse_date(raw: str, fmt: str) -> str | None:
    try:
        return datetime.strptime(raw.strip(), fmt).strftime("%Y-%m-%d")
    except ValueError:
        return None


def _coerce_value(val: str, col_type: str, decimal: str, date_fmt: str | None) -> Any:
    if val == "" or val is None:
        return None
    if col_type == "INTEGER":
        return int(val.replace(",", "") if decimal == "," else val)
    if col_type == "REAL":
        v = val.replace(",", ".") if decimal == "," else val
        return float(v)
    if date_fmt:
        parsed = _parse_date(val, date_fmt)
        if parsed is None:
            raise ValueError(f"bad date {val!r}")
        return parsed
    return val


def run_import(cfg: AppConfig, profile_id: str, file_bytes: bytes) -> dict[str, Any]:
    if len(file_bytes) > MAX_FILE_BYTES:
        raise ValidationError("file_too_large", "File exceeds 5 MiB limit.")
    schema = read_or_create_schema(cfg.appdir)
    profile = None
    for item in schema.get("import_profiles") or []:
        if isinstance(item, dict) and item.get("id") == profile_id:
            profile = item
            break
    if not profile or profile.get("enabled") is False:
        raise ValidationError("not_found", f"Profile {profile_id!r} not found.")

    encoding = profile.get("encoding", "utf-8")
    delimiter = profile.get("delimiter", ",")
    header_row = int(profile.get("header_row", 0))
    skip_rows = int(profile.get("skip_rows", 0))
    quotechar = profile.get("quotechar", '"')
    decimal = profile.get("decimal", ".")
    col_map = profile.get("map") or {}
    date_formats = profile.get("date_formats") or {}
    dup_keys = profile.get("duplicate_keys") or []
    dup_policy = profile.get("duplicate", "skip")
    table = profile["table"]
    table_def = schema["tables"][table]
    col_types = {c["name"]: c.get("type", "TEXT") for c in (table_def.get("columns") or [])}

    text = file_bytes.decode(encoding, errors="replace")
    lines = text.splitlines()
    for _ in range(skip_rows):
        if lines:
            lines.pop(0)
    reader = csv.DictReader(
        io.StringIO("\n".join(lines)),
        delimiter=delimiter,
        quotechar=quotechar,
    )
    if header_row > 0:
        pass

    import sqlite3

    conn = sqlite3.connect(str(db_path(cfg.appdir)))
    ok = 0
    fail = 0
    errors: list[dict[str, Any]] = []
    line_no = skip_rows + 1
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    try:
        for row in reader:
            line_no += 1
            try:
                fields: dict[str, Any] = {}
                for csv_col, db_col in col_map.items():
                    raw = row.get(csv_col, "")
                    if raw == "" and profile.get("empty") == "null":
                        fields[db_col] = None
                        continue
                    fmt = date_formats.get(db_col)
                    fields[db_col] = _coerce_value(raw, col_types.get(db_col, "TEXT"), decimal, fmt)
                if dup_keys:
                    where = " AND ".join(f"{_quote_ident(k)} = ?" for k in dup_keys)
                    params = [fields.get(k) for k in dup_keys]
                    cur = conn.execute(
                        f"SELECT id FROM {_quote_ident(table)} WHERE {where}",
                        params,
                    )
                    existing = cur.fetchone()
                    if existing:
                        if dup_policy == "skip":
                            continue
                        if dup_policy == "update":
                            sets = ", ".join(f"{_quote_ident(k)} = ?" for k in fields)
                            conn.execute(
                                f"UPDATE {_quote_ident(table)} SET {sets}, updated_at = ? WHERE id = ?",
                                list(fields.values()) + [now, existing[0]],
                            )
                            ok += 1
                            continue
                cols = ["created_at", "updated_at"] + list(fields.keys())
                vals = [now, now] + list(fields.values())
                placeholders = ", ".join("?" for _ in cols)
                col_sql = ", ".join(_quote_ident(c) for c in cols)
                conn.execute(
                    f"INSERT INTO {_quote_ident(table)} ({col_sql}) VALUES ({placeholders})",
                    vals,
                )
                ok += 1
            except Exception as exc:
                fail += 1
                errors.append({"line": line_no, "message": str(exc)})
        conn.commit()
    finally:
        conn.close()

    log_conn = connect(cfg.appdir)
    try:
        log_conn.execute(
            "INSERT INTO _import_runs (profile_id, ok_count, fail_count, log_json, created_at) VALUES (?, ?, ?, ?, ?)",
            (profile_id, ok, fail, json.dumps(errors), now),
        )
        log_conn.commit()
    finally:
        log_conn.close()

    return {"ok": ok, "fail": fail, "errors": errors}
