"""Rules: triggers, conditions, and actions."""

from __future__ import annotations

import copy
import json
import os
import smtplib
import sqlite3
from datetime import datetime, timezone
from email.message import EmailMessage
from typing import Any

from app.config import AppConfig, read_or_create_schema, schema_path
from app.db_paths import db_path, quote_ident as _quote_ident
from app.formulas import eval_expr
from app.notices import has_recent_notice, insert_notice
from app.schema_validate import NAME_RE, ValidationError

RULE_KEYS = {"id", "enabled", "trigger", "table", "when", "then"}
TRIGGER_KINDS = frozenset({"on_write", "schedule"})
ACTION_KINDS = frozenset({"notify", "set_column", "create_row", "email"})
MAX_ROWS_PER_TICK = 200


def validate_rule(obj: dict[str, Any], schema: dict[str, Any]) -> None:
    if not isinstance(obj, dict):
        raise ValidationError("bad_rule", "Rule must be an object.")
    extra = set(obj) - RULE_KEYS
    if extra:
        raise ValidationError("unknown_key", f"Rule has unknown keys: {sorted(extra)}.")
    rid = obj.get("id")
    if not isinstance(rid, str) or not NAME_RE.match(rid):
        raise ValidationError("bad_rule", "Rule id must be snake_case.")
    trigger = obj.get("trigger")
    if not isinstance(trigger, dict) or trigger.get("kind") not in TRIGGER_KINDS:
        raise ValidationError("bad_rule", "trigger.kind must be on_write or schedule.")
    table = obj.get("table")
    if not isinstance(table, str) or table not in (schema.get("tables") or {}):
        raise ValidationError("bad_rule", "Rule requires a valid table.")
    when = obj.get("when")
    if not isinstance(when, dict):
        raise ValidationError("bad_rule", "when expression is required.")
    from app.formulas import _validate_expr

    _validate_expr(when, schema, depth=0)
    then = obj.get("then")
    if not isinstance(then, list) or not then:
        raise ValidationError("bad_rule", "then must be a non-empty list.")
    for action in then:
        if not isinstance(action, dict):
            raise ValidationError("bad_rule", "Action must be an object.")
        kind = action.get("kind")
        if kind not in ACTION_KINDS:
            raise ValidationError("bad_rule", f"Unknown action kind: {kind!r}.")


def _find_rule(schema: dict[str, Any], rid: str) -> dict[str, Any] | None:
    for item in schema.get("rules") or []:
        if isinstance(item, dict) and item.get("id") == rid:
            return item
    return None


def try_send_email(cfg: AppConfig, to: str | None, subject: str, body: str) -> bool:
    host = os.environ.get("SMTP_HOST", "").strip()
    if not host or not to:
        return False
    port = int(os.environ.get("SMTP_PORT", "587"))
    user = os.environ.get("SMTP_USER", "").strip()
    password = os.environ.get("SMTP_PASSWORD", "").strip()
    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = user or "desktopper@localhost"
    msg["To"] = to
    msg.set_content(body)
    try:
        with smtplib.SMTP(host, port, timeout=30) as smtp:
            if user and password:
                smtp.starttls()
                smtp.login(user, password)
            smtp.send_message(msg)
        return True
    except Exception:
        return False


def _row_matches(cfg: AppConfig, rule: dict[str, Any], row: dict[str, Any], schema: dict[str, Any]) -> bool:
    try:
        return bool(
            eval_expr(
                rule["when"],
                schema=schema,
                row=row,
                default_tz=cfg.timezone,
            )
        )
    except Exception:
        return False


def _run_actions(
    cfg: AppConfig,
    rule: dict[str, Any],
    row: dict[str, Any],
    *,
    conn: sqlite3.Connection,
) -> None:
    schema = read_or_create_schema(cfg.appdir)
    for action in rule.get("then") or []:
        kind = action.get("kind")
        if kind == "notify":
            title = action.get("title") or "Notice"
            body = action.get("body")
            if has_recent_notice(cfg.appdir, rule_id=rule["id"], row_id=int(row["id"]), conn=conn):
                continue
            insert_notice(
                cfg.appdir,
                title=title,
                body=body,
                rule_id=rule["id"],
                row_id=int(row["id"]),
                conn=conn,
            )
        elif kind == "email":
            if not try_send_email(cfg, action.get("to"), action.get("subject", ""), action.get("body", "")):
                insert_notice(
                    cfg.appdir,
                    title=action.get("subject") or "Email skipped",
                    body=action.get("body"),
                    rule_id=rule["id"],
                    row_id=int(row["id"]),
                    conn=conn,
                )
        elif kind == "set_column":
            col = action.get("column")
            value = action.get("value")
            if isinstance(col, str):
                conn.execute(
                    f"UPDATE {_quote_ident(rule['table'])} SET {_quote_ident(col)} = ? WHERE id = ?",
                    (value, row["id"]),
                )
        elif kind == "create_row":
            target = action.get("table")
            fields = action.get("fields") or {}
            if isinstance(target, str) and target in (schema.get("tables") or {}):
                cols = ["created_at", "updated_at"] + list(fields.keys())
                now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
                vals = [now, now] + [fields[k] for k in fields]
                placeholders = ", ".join("?" for _ in cols)
                col_sql = ", ".join(_quote_ident(c) for c in cols)
                conn.execute(
                    f"INSERT INTO {_quote_ident(target)} ({col_sql}) VALUES ({placeholders})",
                    vals,
                )


def run_on_write_rules(cfg: AppConfig, table: str, row: dict[str, Any], *, conn: sqlite3.Connection) -> None:
    schema = read_or_create_schema(cfg.appdir)
    for rule in schema.get("rules") or []:
        if not isinstance(rule, dict) or rule.get("enabled") is False:
            continue
        trigger = rule.get("trigger") or {}
        if trigger.get("kind") != "on_write" or rule.get("table") != table:
            continue
        if _row_matches(cfg, rule, row, schema):
            _run_actions(cfg, rule, row, conn=conn)


def run_scheduled_rules(cfg: AppConfig, *, limit: int = MAX_ROWS_PER_TICK) -> int:
    schema = read_or_create_schema(cfg.appdir)
    conn = sqlite3.connect(str(db_path(cfg.appdir)))
    conn.row_factory = sqlite3.Row
    count = 0
    try:
        for rule in schema.get("rules") or []:
            if not isinstance(rule, dict) or rule.get("enabled") is False:
                continue
            trigger = rule.get("trigger") or {}
            if trigger.get("kind") != "schedule":
                continue
            table = rule["table"]
            cur = conn.execute(f"SELECT * FROM {_quote_ident(table)} LIMIT ?", (limit,))
            for db_row in cur.fetchall():
                row = dict(db_row)
                if _row_matches(cfg, rule, row, schema):
                    _run_actions(cfg, rule, row, conn=conn)
                    count += 1
        conn.commit()
    finally:
        conn.close()
    return count


def apply_rule_diff(cfg: AppConfig, diff: dict[str, Any]) -> list[str]:
    changed: list[str] = []
    add = diff.get("add_rules") or []
    disable = diff.get("disable_rules") or []
    if not add and not disable:
        return changed
    schema = read_or_create_schema(cfg.appdir)
    out = copy.deepcopy(schema)
    out.setdefault("rules", [])
    for item in add:
        validate_rule(item, out)
        found = False
        for idx, existing in enumerate(out["rules"]):
            if isinstance(existing, dict) and existing.get("id") == item["id"]:
                out["rules"][idx] = {**existing, **item}
                found = True
                break
        if not found:
            new_item = dict(item)
            new_item.setdefault("enabled", True)
            out["rules"].append(new_item)
        changed.append(item["id"])
    id_set = set(str(x) for x in disable)
    for item in out["rules"]:
        if isinstance(item, dict) and item.get("id") in id_set:
            item["enabled"] = False
            changed.append(item["id"])
    out["version"] = int(out.get("version") or 0) + 1
    schema_path(cfg.appdir).write_text(json.dumps(out, indent=2) + "\n", encoding="utf-8")
    return changed
