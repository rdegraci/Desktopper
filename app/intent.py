"""POST /api/intent: stats, LLM, parse, apply."""

from __future__ import annotations

import json
import sqlite3
from typing import Any, Callable

from app.config import AppConfig, read_or_create_schema
from app.db_paths import db_path, quote_ident as _quote_ident
from app.engine import EngineError, apply_diff
from app.hooks import hook_sources, read_registry
from app.llm import LlmError, chat_completion, parse_json_object
from app.log import emit
from app.intent_errors import truncate_rejected_diff
from app.schema_validate import IntentValidationError, NAME_RE, ValidationError
from app.system_prompt import load_system_prompt


def collect_stats(cfg: AppConfig, schema: dict[str, Any]) -> dict[str, Any]:
    tables = schema.get("tables") or {}
    stats: dict[str, Any] = {"tables": {}}
    conn = sqlite3.connect(str(db_path(cfg.appdir)))
    try:
        for tname, table in tables.items():
            if not isinstance(tname, str) or not NAME_RE.match(tname):
                continue
            cols = []
            if isinstance(table, dict):
                for col in table.get("columns") or []:
                    if isinstance(col, dict) and col.get("name"):
                        cols.append(col["name"])
            try:
                cur = conn.execute("SELECT COUNT(*) FROM " + _quote_ident(tname))
                count = int(cur.fetchone()[0])
            except sqlite3.Error:
                count = 0
            stats["tables"][tname] = {"columns": cols, "row_count": count}
    finally:
        conn.close()
    return stats


def run_intent(
    cfg: AppConfig,
    text: str,
    *,
    request_id: str | None = None,
    complete: Callable[..., str] | None = None,
) -> dict[str, Any]:
    schema = read_or_create_schema(cfg.appdir)
    version_before = int(schema.get("version") or 0)
    stats = collect_stats(cfg, schema)
    hooks = read_registry(cfg.appdir)
    sources = hook_sources(cfg.appdir)
    user_payload = json.dumps(
        {
            "intent": text,
            "schema": schema,
            "stats": stats,
            "hooks": hooks,
            "hook_sources": sources,
            "formula_ids": [f.get("id") for f in (schema.get("formulas") or []) if isinstance(f, dict)],
            "rule_ids": [r.get("id") for r in (schema.get("rules") or []) if isinstance(r, dict)],
            "reminder_ids": [r.get("id") for r in (schema.get("reminders") or []) if isinstance(r, dict)],
            "job_ids": [j.get("id") for j in (schema.get("jobs") or []) if isinstance(j, dict)],
            "layout_ids": [l.get("id") for l in (schema.get("layouts") or []) if isinstance(l, dict)],
            "role_names": [r.get("name") for r in (schema.get("roles") or []) if isinstance(r, dict)],
        }
    )
    messages = [
        {"role": "system", "content": load_system_prompt()},
        {"role": "user", "content": user_payload},
    ]
    emit(
        cfg,
        event="llm.request",
        component="llm",
        msg="Calling the model.",
        request_id=request_id,
        schema_version=version_before,
        detail={"model": cfg.llm.model, "provider": cfg.llm.provider, "intent_len": len(text)},
    )
    try:
        if complete is not None:
            raw = complete(messages)
        else:
            raw = chat_completion(cfg, messages)
    except LlmError as exc:
        emit(
            cfg,
            event="llm.response",
            component="llm",
            msg=exc.msg,
            ok=False,
            level="error",
            request_id=request_id,
            schema_version=version_before,
            detail={
                "parse_ok": False,
                "output_len": 0,
                "error_code": exc.error_code,
                "output_head": (exc.output_head or "")[:500],
            },
        )
        emit(
            cfg,
            event="intent.apply.fail",
            component="intent",
            msg=exc.msg,
            ok=False,
            level="error",
            request_id=request_id,
            schema_version=version_before,
            detail={"error_code": exc.error_code},
        )
        raise

    try:
        diff = parse_json_object(raw)
    except LlmError as exc:
        emit(
            cfg,
            event="llm.response",
            component="llm",
            msg="JSON parse failed.",
            ok=False,
            level="error",
            request_id=request_id,
            schema_version=version_before,
            detail={
                "parse_ok": False,
                "output_len": len(raw or ""),
                "output_head": (exc.output_head or "")[:500],
                "error_code": "llm_parse",
            },
        )
        emit(
            cfg,
            event="llm.parse",
            component="llm",
            msg="Model output is not JSON.",
            ok=False,
            level="error",
            request_id=request_id,
            schema_version=version_before,
            detail={
                "error_code": "llm_parse",
                "output_head": (exc.output_head or "")[:500],
            },
        )
        emit(
            cfg,
            event="intent.apply.fail",
            component="intent",
            msg="Model output is not JSON.",
            ok=False,
            level="error",
            request_id=request_id,
            schema_version=version_before,
            detail={"error_code": "llm_parse"},
        )
        raise

    emit(
        cfg,
        event="llm.response",
        component="llm",
        msg="Model returned JSON.",
        request_id=request_id,
        schema_version=version_before,
        detail={"parse_ok": True, "output_len": len(raw or "")},
    )

    try:
        merged = apply_diff(cfg, diff, request_id=request_id)
    except ValidationError as exc:
        emit(
            cfg,
            event="intent.apply.fail",
            component="intent",
            msg=exc.msg,
            ok=False,
            level="error",
            request_id=request_id,
            schema_version=version_before,
            detail={
                "error_code": exc.error_code,
                "diff_keys": sorted(diff.keys()) if isinstance(diff, dict) else [],
                **exc.detail,
            },
        )
        raise IntentValidationError(exc, truncate_rejected_diff(diff)) from exc
    except EngineError as exc:
        emit(
            cfg,
            event="intent.apply.fail",
            component="intent",
            msg=exc.msg,
            ok=False,
            level="error",
            request_id=request_id,
            schema_version=version_before,
            detail={"error_code": exc.error_code},
        )
        raise
    hooks_changed = merged.pop("_hooks_changed", [])
    emit(
        cfg,
        event="intent.apply.ok",
        component="intent",
        msg=str(diff.get("summary") or "Applied spec."),
        request_id=request_id,
        schema_version=int(merged.get("version") or 0),
        detail={"error_code": None, "summary": diff.get("summary"), "hooks_changed": hooks_changed},
    )
    return {
        "summary": diff.get("summary") or "Applied spec.",
        "schema": merged,
        "version": int(merged.get("version") or 0),
        "hooks_changed": hooks_changed,
    }
