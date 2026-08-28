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
from app.schema_validate import IntentValidationError, NAME_RE, ValidationError, validate_diff
from app.system_prompt import load_system_prompt

REPL_ACTIONS = frozenset({"clarify", "propose", "apply"})
_HISTORY_USER_CAP = 10
_HISTORY_ASSISTANT_CAP = 10


def cap_history(history: list[dict[str, Any]] | None) -> list[dict[str, Any]]:
    if not history:
        return []
    user_count = 0
    asst_count = 0
    kept: list[dict[str, Any]] = []
    for entry in reversed(history):
        if not isinstance(entry, dict):
            continue
        role = entry.get("role")
        if role == "user":
            if user_count >= _HISTORY_USER_CAP:
                continue
            user_count += 1
        elif role == "assistant":
            if asst_count >= _HISTORY_ASSISTANT_CAP:
                continue
            asst_count += 1
        else:
            continue
        kept.append(entry)
    kept.reverse()
    return kept


def history_messages(history: list[dict[str, Any]] | None) -> list[dict[str, str]]:
    messages: list[dict[str, str]] = []
    for entry in cap_history(history):
        role = entry.get("role")
        if role == "user":
            text = entry.get("content") or entry.get("text") or ""
            messages.append({"role": "user", "content": str(text)})
        elif role == "assistant":
            text = entry.get("content") or entry.get("message") or ""
            action = entry.get("action")
            if action:
                text = f"[{action}] {text}"
            messages.append({"role": "assistant", "content": str(text)})
    return messages


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


def build_user_payload(
    cfg: AppConfig,
    text: str,
    schema: dict[str, Any],
    *,
    ui_context: dict[str, Any] | None = None,
    history: list[dict[str, Any]] | None = None,
) -> str:
    stats = collect_stats(cfg, schema)
    hooks = read_registry(cfg.appdir)
    sources = hook_sources(cfg.appdir)
    payload: dict[str, Any] = {
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
    if ui_context is not None:
        payload["ui_context"] = ui_context
    if history is not None:
        payload["history"] = history
    return json.dumps(payload)


def validation_result(schema: dict[str, Any], diff: Any, *, hooks_registry: dict[str, Any]) -> dict[str, Any]:
    try:
        validate_diff(schema, diff, hooks_registry=hooks_registry)
    except ValidationError as exc:
        err: dict[str, Any] = {"code": exc.error_code, "message": exc.msg}
        if exc.detail:
            err["detail"] = exc.detail
        return {"ok": False, "errors": [err]}
    return {"ok": True, "errors": []}


def _apply_proposed_diff(
    cfg: AppConfig,
    diff: dict[str, Any],
    *,
    request_id: str | None,
    version_before: int,
) -> dict[str, Any]:
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
    summary = str(diff.get("summary") or "Applied spec.")
    emit(
        cfg,
        event="intent.apply.ok",
        component="intent",
        msg=summary,
        request_id=request_id,
        schema_version=int(merged.get("version") or 0),
        detail={"error_code": None, "summary": diff.get("summary"), "hooks_changed": hooks_changed},
    )
    return {
        "action": "apply",
        "message": summary,
        "summary": summary,
        "schema": merged,
        "version": int(merged.get("version") or 0),
        "hooks_changed": hooks_changed,
        "proposed_diff": diff,
        "validation": {"ok": True, "errors": []},
    }


def _call_llm(
    cfg: AppConfig,
    messages: list[dict[str, str]],
    *,
    request_id: str | None,
    version_before: int,
    complete: Callable[..., str] | None,
) -> str:
    emit(
        cfg,
        event="llm.request",
        component="llm",
        msg="Calling the model.",
        request_id=request_id,
        schema_version=version_before,
        detail={"model": cfg.llm.model, "provider": cfg.llm.provider},
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
    emit(
        cfg,
        event="llm.response",
        component="llm",
        msg="Model returned JSON.",
        request_id=request_id,
        schema_version=version_before,
        detail={"parse_ok": True, "output_len": len(raw or "")},
    )
    return raw


def _parse_llm_json(
    cfg: AppConfig,
    raw: str,
    *,
    request_id: str | None,
    version_before: int,
) -> dict[str, Any]:
    try:
        parsed = parse_json_object(raw)
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
    if not isinstance(parsed, dict):
        raise LlmError("llm_parse", "Model output is not a JSON object.", output_head=str(parsed)[:200])
    return parsed


def run_intent_repl(
    cfg: AppConfig,
    text: str,
    *,
    history: list[dict[str, Any]] | None = None,
    ui_context: dict[str, Any] | None = None,
    apply_diff_payload: dict[str, Any] | None = None,
    request_id: str | None = None,
    complete: Callable[..., str] | None = None,
) -> dict[str, Any]:
    schema = read_or_create_schema(cfg.appdir)
    version_before = int(schema.get("version") or 0)
    hooks_registry = read_registry(cfg.appdir)

    if apply_diff_payload is not None:
        if not isinstance(apply_diff_payload, dict):
            raise ValidationError("invalid_json", "apply_diff must be a JSON object.")
        message = str(apply_diff_payload.get("summary") or "Applied spec.")
        result = _apply_proposed_diff(
            cfg,
            apply_diff_payload,
            request_id=request_id,
            version_before=version_before,
        )
        result["message"] = message
        return result

    messages = [{"role": "system", "content": load_system_prompt("repl")}]
    messages.extend(history_messages(history))
    messages.append(
        {"role": "user", "content": build_user_payload(cfg, text, schema, ui_context=ui_context, history=history)}
    )
    raw = _call_llm(cfg, messages, request_id=request_id, version_before=version_before, complete=complete)
    parsed = _parse_llm_json(cfg, raw, request_id=request_id, version_before=version_before)

    action = parsed.get("action")
    if action not in REPL_ACTIONS:
        raise LlmError(
            "llm_parse",
            "Model response missing valid action.",
            output_head=str(parsed.get("action"))[:200],
        )

    message = str(parsed.get("message") or "")
    open_questions = parsed.get("open_questions") or []
    if not isinstance(open_questions, list):
        open_questions = []

    if action == "clarify":
        emit(
            cfg,
            event="intent.repl.clarify",
            component="intent",
            msg=message or "Clarification requested.",
            request_id=request_id,
            schema_version=version_before,
        )
        return {
            "action": "clarify",
            "message": message,
            "open_questions": open_questions,
            "proposed_diff": None,
            "validation": None,
            "version": None,
            "schema": None,
        }

    proposed_diff = parsed.get("proposed_diff")
    if not isinstance(proposed_diff, dict):
        raise LlmError(
            "llm_parse",
            "propose/apply requires proposed_diff object.",
            output_head=str(proposed_diff)[:200],
        )

    validation = validation_result(schema, proposed_diff, hooks_registry=hooks_registry)

    if action == "propose":
        emit(
            cfg,
            event="intent.repl.propose",
            component="intent",
            msg=message or str(proposed_diff.get("summary") or "Proposed plan."),
            request_id=request_id,
            schema_version=version_before,
            detail={"validation_ok": validation["ok"]},
        )
        return {
            "action": "propose",
            "message": message,
            "proposed_diff": proposed_diff,
            "open_questions": open_questions,
            "validation": validation,
            "version": None,
            "schema": None,
        }

    if not validation["ok"]:
        emit(
            cfg,
            event="intent.apply.fail",
            component="intent",
            msg=validation["errors"][0]["message"] if validation["errors"] else "Validation failed.",
            ok=False,
            level="error",
            request_id=request_id,
            schema_version=version_before,
            detail={"error_code": validation["errors"][0].get("code") if validation["errors"] else "validate"},
        )
        raise IntentValidationError(
            ValidationError(
                validation["errors"][0].get("code", "validate"),
                validation["errors"][0]["message"],
                detail=validation["errors"][0].get("detail"),
            ),
            truncate_rejected_diff(proposed_diff),
        )

    result = _apply_proposed_diff(
        cfg,
        proposed_diff,
        request_id=request_id,
        version_before=version_before,
    )
    if message:
        result["message"] = message
    return result


def run_intent(
    cfg: AppConfig,
    text: str,
    *,
    request_id: str | None = None,
    complete: Callable[..., str] | None = None,
) -> dict[str, Any]:
    schema = read_or_create_schema(cfg.appdir)
    version_before = int(schema.get("version") or 0)
    user_payload = build_user_payload(cfg, text, schema)
    messages = [
        {"role": "system", "content": load_system_prompt()},
        {"role": "user", "content": user_payload},
    ]
    raw = _call_llm(
        cfg,
        messages,
        request_id=request_id,
        version_before=version_before,
        complete=complete,
    )
    diff = _parse_llm_json(cfg, raw, request_id=request_id, version_before=version_before)
    result = _apply_proposed_diff(cfg, diff, request_id=request_id, version_before=version_before)
    return {
        "summary": result["summary"],
        "schema": result["schema"],
        "version": result["version"],
        "hooks_changed": result["hooks_changed"],
    }
