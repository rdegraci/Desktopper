"""CRUD hooks: registry, loader, and spec diff apply."""

from __future__ import annotations

import importlib.util
import json
import traceback
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import sqlite3

from app.config import AppConfig
from app.log import emit
from app.schema_validate import NAME_RE, ValidationError

HOOKS_FILE = "hooks.json"
HOOKS_DIR = "hooks"
CRUD_HOOK_EVENTS = frozenset({"create", "update", "delete"})
STARTUP_HOOK_EVENT = "startup"
ALL_HOOK_EVENTS = CRUD_HOOK_EVENTS | {STARTUP_HOOK_EVENT}
EMPTY_REGISTRY: dict[str, Any] = {"version": 0, "hooks": []}

ADD_HOOK_KEYS = {"id", "table", "on", "code"}
UPDATE_HOOK_KEYS = {"id", "code", "enabled"}


class HookError(Exception):
    def __init__(self, hook_id: str, msg: str, *, tb_head: str | None = None) -> None:
        super().__init__(msg)
        self.hook_id = hook_id
        self.msg = msg
        self.tb_head = tb_head


def hooks_path(appdir: Path) -> Path:
    return appdir / HOOKS_FILE


def hooks_dir(appdir: Path) -> Path:
    return appdir / HOOKS_DIR


def read_registry(appdir: Path) -> dict[str, Any]:
    path = hooks_path(appdir)
    if not path.is_file():
        return dict(EMPTY_REGISTRY)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return dict(EMPTY_REGISTRY)
    if not isinstance(data, dict):
        return dict(EMPTY_REGISTRY)
    hooks = data.get("hooks")
    if not isinstance(hooks, list):
        hooks = []
    version = data.get("version")
    if not isinstance(version, int):
        version = 0
    return {"version": version, "hooks": hooks}


def write_registry(appdir: Path, data: dict[str, Any]) -> None:
    hooks_dir(appdir).mkdir(parents=True, exist_ok=True)
    path = hooks_path(appdir)
    path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")


def ensure_registry(appdir: Path) -> dict[str, Any]:
    hooks_dir(appdir).mkdir(parents=True, exist_ok=True)
    path = hooks_path(appdir)
    if not path.is_file():
        write_registry(appdir, dict(EMPTY_REGISTRY))
    return read_registry(appdir)


def hook_sources(appdir: Path) -> dict[str, str]:
    registry = read_registry(appdir)
    out: dict[str, str] = {}
    for item in registry.get("hooks") or []:
        if not isinstance(item, dict):
            continue
        hid = item.get("id")
        rel = item.get("file")
        if not isinstance(hid, str) or not isinstance(rel, str):
            continue
        path = _safe_hook_path(appdir, rel)
        if path.is_file():
            try:
                out[hid] = path.read_text(encoding="utf-8")
            except OSError:
                out[hid] = ""
    return out


def syntax_check(code: str, *, filename: str = "<hook>") -> None:
    if not isinstance(code, str) or not code.strip():
        raise ValidationError("bad_hook", "Hook code must be a non-empty string.")
    try:
        compile(code, filename, "exec")
    except SyntaxError as exc:
        raise ValidationError("bad_hook", f"Hook code has a syntax error: {exc}") from exc


def _safe_hook_path(appdir: Path, rel: str) -> Path:
    if not isinstance(rel, str) or ".." in rel.split("/"):
        raise ValidationError("bad_hook", "Hook file path is not allowed.")
    root = hooks_dir(appdir).resolve()
    target = (appdir / rel).resolve()
    try:
        target.relative_to(root)
    except ValueError:
        raise ValidationError("bad_hook", "Hook file must live under hooks/.") from None
    return target


def default_hook_filename(table: str, event: str, hook_id: str) -> str:
    base = f"{table}.on_{event}.py"
    path = hooks_dir(Path(".")) / base
    # collision check done by caller against registry
    _ = path
    return f"{HOOKS_DIR}/{base}"


def resolve_hook_filename(
    registry: dict[str, Any],
    table: str,
    event: str,
    hook_id: str,
) -> str:
    if event == STARTUP_HOOK_EVENT:
        preferred = f"{HOOKS_DIR}/{hook_id}.on_startup.py"
        used = {
            h.get("file")
            for h in (registry.get("hooks") or [])
            if isinstance(h, dict)
        }
        if preferred not in used:
            return preferred
        alt = f"{HOOKS_DIR}/startup_{hook_id}.py"
        if alt not in used:
            return alt
        raise ValidationError("bad_hook", f"No free hook filename for {hook_id}.")
    preferred = f"{HOOKS_DIR}/{table}.on_{event}.py"
    used = {
        h.get("file")
        for h in (registry.get("hooks") or [])
        if isinstance(h, dict)
    }
    if preferred not in used:
        return preferred
    alt = f"{HOOKS_DIR}/{table}_{hook_id}.py"
    if alt not in used:
        return alt
    raise ValidationError("bad_hook", f"No free hook filename for {hook_id}.")


def _hook_by_id(registry: dict[str, Any], hook_id: str) -> dict[str, Any] | None:
    for item in registry.get("hooks") or []:
        if isinstance(item, dict) and item.get("id") == hook_id:
            return item
    return None


@dataclass
class HookContext:
    appdir: Path
    cfg: AppConfig
    event: str
    table: str = ""
    row: dict[str, Any] | None = None
    conn: sqlite3.Connection | None = None
    row_before: dict[str, Any] | None = None
    depth: int = 0


def _load_run(appdir: Path, hook_id: str, rel: str):
    path = _safe_hook_path(appdir, rel)
    if not path.is_file():
        raise HookError(hook_id, f"Hook file missing: {rel}")
    mod_name = f"desktopper_hook_{hook_id}"
    spec = importlib.util.spec_from_file_location(mod_name, path)
    if spec is None or spec.loader is None:
        raise HookError(hook_id, f"Could not load hook: {rel}")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    run_fn = getattr(mod, "run", None)
    if not callable(run_fn):
        raise HookError(hook_id, "Hook file must define run(ctx).")
    return run_fn


def run_hooks(
    cfg: AppConfig,
    *,
    conn: sqlite3.Connection,
    table: str,
    event: str,
    row: dict[str, Any],
    row_before: dict[str, Any] | None = None,
    depth: int = 0,
    request_id: str | None = None,
) -> None:
    if depth > 0:
        return
    if event not in CRUD_HOOK_EVENTS:
        return
    registry = read_registry(cfg.appdir)
    schema_version = 0
    try:
        from app.config import read_or_create_schema

        schema_version = int(read_or_create_schema(cfg.appdir).get("version") or 0)
    except (OSError, json.JSONDecodeError, TypeError, ValueError):
        pass
    for item in registry.get("hooks") or []:
        if not isinstance(item, dict):
            continue
        if item.get("table") != table or item.get("on") != event:
            continue
        if item.get("enabled") is False:
            continue
        hook_id = str(item.get("id") or "")
        rel = item.get("file")
        if not hook_id or not isinstance(rel, str):
            continue
        ctx = HookContext(
            appdir=cfg.appdir,
            cfg=cfg,
            event=event,
            table=table,
            row=row,
            row_before=row_before,
            conn=conn,
            depth=depth,
        )
        try:
            run_fn = _load_run(cfg.appdir, hook_id, rel)
            run_fn(ctx)
        except HookError:
            raise
        except Exception as exc:
            tb = traceback.format_exc()
            emit(
                cfg,
                event="hook.run.fail",
                component="hooks",
                msg=str(exc),
                ok=False,
                level="error",
                request_id=request_id,
                schema_version=schema_version,
                detail={"hook_id": hook_id, "table": table, "event": event},
            )
            raise HookError(hook_id, str(exc), tb_head=tb[-500:]) from exc
        emit(
            cfg,
            event="hook.run.ok",
            component="hooks",
            msg=f"Ran hook {hook_id}.",
            request_id=request_id,
            schema_version=schema_version,
            detail={"hook_id": hook_id, "table": table, "event": event},
        )


def run_startup_hooks(cfg: AppConfig) -> None:
    """Run startup hooks once. Errors are logged; the server keeps starting."""
    registry = read_registry(cfg.appdir)
    schema_version = 0
    try:
        from app.config import read_or_create_schema

        schema_version = int(read_or_create_schema(cfg.appdir).get("version") or 0)
    except (OSError, json.JSONDecodeError, TypeError, ValueError):
        pass
    for item in registry.get("hooks") or []:
        if not isinstance(item, dict):
            continue
        if item.get("on") != STARTUP_HOOK_EVENT:
            continue
        if item.get("enabled") is False:
            continue
        hook_id = str(item.get("id") or "")
        rel = item.get("file")
        if not hook_id or not isinstance(rel, str):
            continue
        ctx = HookContext(appdir=cfg.appdir, cfg=cfg, event=STARTUP_HOOK_EVENT)
        try:
            run_fn = _load_run(cfg.appdir, hook_id, rel)
            run_fn(ctx)
        except Exception as exc:
            tb = traceback.format_exc()
            emit(
                cfg,
                event="hook.startup.fail",
                component="hooks",
                msg=str(exc),
                ok=False,
                level="error",
                schema_version=schema_version,
                detail={"hook_id": hook_id, "event": STARTUP_HOOK_EVENT, "trace": tb[-500:]},
            )
            continue
        emit(
            cfg,
            event="hook.startup.ok",
            component="hooks",
            msg=f"Ran startup hook {hook_id}.",
            schema_version=schema_version,
            detail={"hook_id": hook_id, "event": STARTUP_HOOK_EVENT},
        )


def apply_hook_diff(cfg: AppConfig, diff: dict[str, Any]) -> list[dict[str, str]]:
    """Apply hook-related keys from a spec diff. Returns change list for API preview."""
    changes: list[dict[str, str]] = []
    registry = ensure_registry(cfg.appdir)
    hooks = list(registry.get("hooks") or [])

    for item in diff.get("add_hooks") or []:
        hid = item["id"]
        event = item["on"]
        table = item.get("table") or ""
        rel = resolve_hook_filename(registry, table, event, hid)
        path = _safe_hook_path(cfg.appdir, rel)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(item["code"], encoding="utf-8")
        entry = {
            "id": hid,
            "table": table,
            "on": event,
            "file": rel,
            "enabled": True,
        }
        hooks.append(entry)
        registry["hooks"] = hooks
        changes.append({"id": hid, "action": "add"})

    for item in diff.get("update_hooks") or []:
        hid = item["id"]
        existing = _hook_by_id(registry, hid)
        if existing is None:
            raise ValidationError("bad_hook", f"Hook {hid} does not exist.")
        rel = existing.get("file")
        if not isinstance(rel, str):
            raise ValidationError("bad_hook", f"Hook {hid} has no file.")
        path = _safe_hook_path(cfg.appdir, rel)
        path.write_text(item["code"], encoding="utf-8")
        if "enabled" in item:
            existing["enabled"] = bool(item["enabled"])
        changes.append({"id": hid, "action": "update"})

    for hid in diff.get("disable_hooks") or []:
        existing = _hook_by_id(registry, str(hid))
        if existing is None:
            raise ValidationError("bad_hook", f"Hook {hid} does not exist.")
        existing["enabled"] = False
        changes.append({"id": str(hid), "action": "disable"})

    for hid in diff.get("remove_hooks") or []:
        sid = str(hid)
        existing = _hook_by_id(registry, sid)
        if existing is None:
            raise ValidationError("bad_hook", f"Hook {sid} does not exist.")
        rel = existing.get("file")
        registry["hooks"] = [h for h in hooks if not (isinstance(h, dict) and h.get("id") == sid)]
        hooks = registry["hooks"]
        if isinstance(rel, str):
            try:
                path = _safe_hook_path(cfg.appdir, rel)
                if path.is_file():
                    path.unlink()
            except ValidationError:
                pass
        changes.append({"id": sid, "action": "remove"})

    if changes:
        registry["version"] = int(registry.get("version") or 0) + 1
        write_registry(cfg.appdir, registry)
    return changes


def save_hook_code(cfg: AppConfig, hook_id: str, code: str) -> dict[str, Any]:
    if not NAME_RE.match(hook_id):
        raise ValidationError("bad_hook", "Hook id is not snake_case.")
    syntax_check(code, filename=f"{hook_id}.py")
    registry = ensure_registry(cfg.appdir)
    existing = _hook_by_id(registry, hook_id)
    if existing is None:
        raise ValidationError("bad_hook", f"Hook {hook_id} does not exist.")
    rel = existing.get("file")
    if not isinstance(rel, str):
        raise ValidationError("bad_hook", f"Hook {hook_id} has no file.")
    path = _safe_hook_path(cfg.appdir, rel)
    path.write_text(code, encoding="utf-8")
    registry["version"] = int(registry.get("version") or 0) + 1
    write_registry(cfg.appdir, registry)
    return existing


def set_hook_enabled(cfg: AppConfig, hook_id: str, enabled: bool) -> dict[str, Any]:
    registry = ensure_registry(cfg.appdir)
    existing = _hook_by_id(registry, hook_id)
    if existing is None:
        raise ValidationError("bad_hook", f"Hook {hook_id} does not exist.")
    existing["enabled"] = bool(enabled)
    registry["version"] = int(registry.get("version") or 0) + 1
    write_registry(cfg.appdir, registry)
    return existing


def remove_hook(cfg: AppConfig, hook_id: str) -> None:
    registry = ensure_registry(cfg.appdir)
    existing = _hook_by_id(registry, hook_id)
    if existing is None:
        raise ValidationError("bad_hook", f"Hook {hook_id} does not exist.")
    rel = existing.get("file")
    registry["hooks"] = [
        h
        for h in (registry.get("hooks") or [])
        if not (isinstance(h, dict) and h.get("id") == hook_id)
    ]
    if isinstance(rel, str):
        try:
            path = _safe_hook_path(cfg.appdir, rel)
            if path.is_file():
                path.unlink()
        except ValidationError:
            pass
    registry["version"] = int(registry.get("version") or 0) + 1
    write_registry(cfg.appdir, registry)


def list_hooks_metadata(cfg: AppConfig) -> list[dict[str, Any]]:
    registry = read_registry(cfg.appdir)
    out: list[dict[str, Any]] = []
    for item in registry.get("hooks") or []:
        if not isinstance(item, dict):
            continue
        out.append(
            {
                "id": item.get("id"),
                "table": item.get("table"),
                "on": item.get("on"),
                "file": item.get("file"),
                "enabled": item.get("enabled", True),
            }
        )
    return out


def get_hook(cfg: AppConfig, hook_id: str) -> dict[str, Any]:
    registry = read_registry(cfg.appdir)
    existing = _hook_by_id(registry, hook_id)
    if existing is None:
        raise ValidationError("bad_hook", f"Hook {hook_id} does not exist.")
    rel = existing.get("file")
    code = ""
    if isinstance(rel, str):
        path = _safe_hook_path(cfg.appdir, rel)
        if path.is_file():
            code = path.read_text(encoding="utf-8")
    return {
        "id": existing.get("id"),
        "table": existing.get("table"),
        "on": existing.get("on"),
        "file": existing.get("file"),
        "enabled": existing.get("enabled", True),
        "code": code,
    }
