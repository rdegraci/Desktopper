"""Flask shell: home, ops, schema stub, logs. Slice 1."""

from __future__ import annotations

import json
import sys
import uuid
from pathlib import Path

from flask import Flask, g, jsonify, request, send_from_directory

from app.config import BindRefusedError, load_config, read_or_create_schema, repo_root
from app.crud import (
    CrudError,
    delete_row,
    get_row,
    insert_row,
    list_options,
    update_row,
)
from app.engine import EngineError
from app.auth import (
    SESSION_COOKIE,
    check_grant,
    create_user,
    current_user,
    ensure_owner,
    login,
    logout,
)
from app.formulas import evaluate_formula
from app.host_db import ensure_host_tables
from app.hooks import (
    get_hook,
    list_hooks_metadata,
    remove_hook,
    run_startup_hooks,
    save_hook_code,
    set_hook_enabled,
)
from app.import_csv import run_import
from app.notices import list_notices, mark_read
from app.reminders import (
    create_reminder,
    dismiss_reminder,
    get_reminder,
    list_reminders,
    snooze_reminder,
    update_reminder,
)
from app.sync import export_events, import_batch, sync_status
from app.tick import scheduler_status, start_scheduler
from app.intent import run_intent
from app.llm import LlmError, public_error_message
from app.search import global_search, list_rows_search
from app.log import (
    emit,
    log_config_load,
    log_server_start,
    read_recent_events,
    setup_logging,
)
from app.providers import UnknownLlmProviderError
from app.schema_validate import ValidationError

STATIC_DIR = repo_root() / "static"
BOOTSTRAP_CSS = STATIC_DIR / "css" / "bootstrap.min.css"


def _load_schema(appdir: Path) -> dict:
    return read_or_create_schema(appdir)


def create_app(*, llm_complete=None) -> Flask:
    cfg = load_config()
    setup_logging(cfg)
    log_config_load(cfg)

    flask_app = Flask(__name__)
    flask_app.config["DESKTOPPER_CFG"] = cfg
    flask_app.config["LLM_COMPLETE"] = llm_complete

    @flask_app.before_request
    def _assign_request_id() -> None:
        g.request_id = str(uuid.uuid4())
        g.cfg = cfg
        g.user = current_user(cfg)

    def _check_table_access(table: str, action: str):
        user = getattr(g, "user", None)
        schema = read_or_create_schema(cfg.appdir)
        if schema.get("grants") and not check_grant(cfg, table=table, action=action, user=user):
            return jsonify({"error": "forbidden", "error_code": "forbidden"}), 403
        return None

    @flask_app.after_request
    def _log_request(response):
        path = request.path or ""
        if path.startswith("/css/") or path.startswith("/js/"):
            return response
        emit(
            cfg,
            event="http.request",
            component="server",
            msg=f"{request.method} {path} -> {response.status_code}",
            request_id=getattr(g, "request_id", None),
            schema_version=_schema_version(cfg.appdir),
            detail={
                "method": request.method,
                "path": path,
                "status": response.status_code,
            },
        )
        return response

    @flask_app.get("/")
    def home():
        return send_from_directory(STATIC_DIR, "index.html")

    @flask_app.get("/ops")
    def ops():
        return send_from_directory(STATIC_DIR, "ops.html")

    @flask_app.get("/css/<path:name>")
    def css_file(name: str):
        return _safe_static("css", name)

    @flask_app.get("/js/<path:name>")
    def js_file(name: str):
        return _safe_static("js", name)

    @flask_app.get("/api/schema")
    def api_schema():
        data = _load_schema(cfg.appdir)
        emit(
            cfg,
            event="schema.read",
            component="server",
            msg="Read schema.json.",
            request_id=g.request_id,
            schema_version=int(data.get("version") or 0),
            detail=None,
        )
        return jsonify(data)

    @flask_app.get("/api/logs")
    def api_logs():
        try:
            limit = int(request.args.get("limit", "100"))
        except ValueError:
            limit = 100
        limit = max(1, min(limit, 500))
        log_path = cfg.appdir / cfg.logging.file
        events = read_recent_events(log_path, limit)
        return jsonify({"events": events})

    def _crud_error(err: CrudError):
        return jsonify({"error": err.msg}), err.status

    @flask_app.get("/api/tables/<name>/options")
    def api_options(name: str):
        try:
            return jsonify(list_options(cfg, name))
        except CrudError as err:
            return _crud_error(err)

    @flask_app.get("/api/tables/<name>")
    def api_list(name: str):
        denied = _check_table_access(name, "read")
        if denied:
            return denied
        try:
            limit = int(request.args.get("limit", "50"))
            offset = int(request.args.get("offset", "0"))
        except ValueError:
            return jsonify({"error": "limit and offset must be integers."}), 400
        try:
            filters = {
                key: val
                for key, val in request.args.items()
                if key not in ("q", "limit", "offset")
            }
            return jsonify(
                list_rows_search(
                    cfg,
                    name,
                    q=request.args.get("q"),
                    filters=filters or None,
                    limit=limit,
                    offset=offset,
                    request_id=g.request_id,
                    user=getattr(g, "user", None),
                )
            )
        except CrudError as err:
            return _crud_error(err)

    @flask_app.get("/api/search")
    def api_search():
        try:
            limit = int(request.args.get("limit", "50"))
        except ValueError:
            return jsonify({"error": "limit must be an integer."}), 400
        try:
            return jsonify(
                global_search(
                    cfg,
                    request.args.get("q"),
                    limit=limit,
                    request_id=g.request_id,
                )
            )
        except CrudError as err:
            return _crud_error(err)

    @flask_app.get("/api/tables/<name>/<int:row_id>")
    def api_get(name: str, row_id: int):
        try:
            return jsonify(get_row(cfg, name, row_id, user=getattr(g, "user", None)))
        except CrudError as err:
            return _crud_error(err)

    @flask_app.post("/api/tables/<name>")
    def api_insert(name: str):
        denied = _check_table_access(name, "create")
        if denied:
            return denied
        body = request.get_json(silent=True)
        if body is None:
            body = {}
        try:
            return jsonify(insert_row(cfg, name, body, request_id=g.request_id)), 201
        except CrudError as err:
            return _crud_error(err)

    @flask_app.put("/api/tables/<name>/<int:row_id>")
    def api_update(name: str, row_id: int):
        denied = _check_table_access(name, "update")
        if denied:
            return denied
        body = request.get_json(silent=True)
        if body is None:
            body = {}
        try:
            return jsonify(update_row(cfg, name, row_id, body, request_id=g.request_id))
        except CrudError as err:
            return _crud_error(err)

    @flask_app.delete("/api/tables/<name>/<int:row_id>")
    def api_delete(name: str, row_id: int):
        denied = _check_table_access(name, "delete")
        if denied:
            return denied
        try:
            delete_row(cfg, name, row_id, request_id=g.request_id)
            return ("", 204)
        except CrudError as err:
            return _crud_error(err)

    @flask_app.get("/api/hooks")
    def api_hooks_list():
        return jsonify({"hooks": list_hooks_metadata(cfg)})

    @flask_app.get("/api/hooks/<hook_id>")
    def api_hooks_get(hook_id: str):
        try:
            return jsonify(get_hook(cfg, hook_id))
        except ValidationError as exc:
            return jsonify({"error": exc.msg, "error_code": exc.error_code}), 404

    @flask_app.put("/api/hooks/<hook_id>")
    def api_hooks_put(hook_id: str):
        body = request.get_json(silent=True)
        if not isinstance(body, dict) or "code" not in body:
            return jsonify({"error": "code is required.", "error_code": "invalid_json"}), 400
        try:
            save_hook_code(cfg, hook_id, body["code"])
            return jsonify(get_hook(cfg, hook_id))
        except ValidationError as exc:
            return jsonify({"error": exc.msg, "error_code": exc.error_code}), 400

    @flask_app.patch("/api/hooks/<hook_id>")
    def api_hooks_patch(hook_id: str):
        body = request.get_json(silent=True)
        if not isinstance(body, dict) or "enabled" not in body:
            return (
                jsonify({"error": "enabled is required.", "error_code": "invalid_json"}),
                400,
            )
        try:
            set_hook_enabled(cfg, hook_id, bool(body["enabled"]))
            return jsonify(get_hook(cfg, hook_id))
        except ValidationError as exc:
            return jsonify({"error": exc.msg, "error_code": exc.error_code}), 404

    @flask_app.delete("/api/hooks/<hook_id>")
    def api_hooks_delete(hook_id: str):
        try:
            remove_hook(cfg, hook_id)
            return ("", 204)
        except ValidationError as exc:
            return jsonify({"error": exc.msg, "error_code": exc.error_code}), 404

    @flask_app.get("/api/notices")
    def api_notices_list():
        user = getattr(g, "user", None)
        uid = user.get("id") if user else None
        unread = request.args.get("unread") == "1"
        return jsonify({"notices": list_notices(cfg.appdir, user_id=uid, unread_only=unread)})

    @flask_app.post("/api/notices/<int:notice_id>/read")
    def api_notices_read(notice_id: int):
        if mark_read(cfg.appdir, notice_id):
            return jsonify({"ok": True})
        return jsonify({"error": "not found"}), 404

    @flask_app.get("/api/reminders")
    def api_reminders_list():
        return jsonify({"reminders": list_reminders(cfg)})

    @flask_app.get("/api/reminders/<rid>")
    def api_reminders_get(rid: str):
        try:
            return jsonify(get_reminder(cfg, rid))
        except ValidationError as exc:
            return jsonify({"error": exc.msg, "error_code": exc.error_code}), 404

    @flask_app.post("/api/reminders")
    def api_reminders_create():
        body = request.get_json(silent=True)
        if not isinstance(body, dict):
            return jsonify({"error": "JSON object required."}), 400
        try:
            return jsonify(create_reminder(cfg, body)), 201
        except ValidationError as exc:
            return jsonify({"error": exc.msg, "error_code": exc.error_code}), 400

    @flask_app.patch("/api/reminders/<rid>")
    def api_reminders_patch(rid: str):
        body = request.get_json(silent=True)
        if not isinstance(body, dict):
            return jsonify({"error": "JSON object required."}), 400
        try:
            return jsonify(update_reminder(cfg, rid, body))
        except ValidationError as exc:
            status = 404 if exc.error_code == "not_found" else 400
            return jsonify({"error": exc.msg, "error_code": exc.error_code}), status

    @flask_app.post("/api/reminders/<rid>/snooze")
    def api_reminders_snooze(rid: str):
        body = request.get_json(silent=True) or {}
        minutes = body.get("minutes", 15)
        try:
            return jsonify(snooze_reminder(cfg, rid, int(minutes)))
        except (ValidationError, ValueError, TypeError) as exc:
            code = getattr(exc, "error_code", "bad_snooze")
            msg = getattr(exc, "msg", str(exc))
            return jsonify({"error": msg, "error_code": code}), 400

    @flask_app.post("/api/reminders/<rid>/dismiss")
    def api_reminders_dismiss(rid: str):
        try:
            return jsonify(dismiss_reminder(cfg, rid))
        except ValidationError as exc:
            return jsonify({"error": exc.msg, "error_code": exc.error_code}), 404

    @flask_app.get("/api/scheduler/status")
    def api_scheduler_status():
        return jsonify(scheduler_status())

    @flask_app.get("/api/jobs")
    def api_jobs_list():
        from app.host_db import connect

        schema = read_or_create_schema(cfg.appdir)
        conn = connect(cfg.appdir)
        schedule: dict[str, str | None] = {}
        try:
            cur = conn.execute(
                "SELECT spec_id, next_run_at FROM _schedules WHERE spec_kind = 'job'"
            )
            for spec_id, next_run_at in cur.fetchall():
                schedule[str(spec_id)] = next_run_at
        finally:
            conn.close()
        jobs_out = []
        for job in schema.get("jobs") or []:
            if isinstance(job, dict) and job.get("id"):
                jobs_out.append({**job, "next_run_at": schedule.get(job["id"])})
        return jsonify({"jobs": jobs_out})

    @flask_app.get("/api/formulas/<formula_id>")
    def api_formula_eval(formula_id: str):
        try:
            value = evaluate_formula(cfg, formula_id)
            return jsonify({"id": formula_id, "value": value})
        except ValidationError as exc:
            return jsonify({"error": exc.msg, "error_code": exc.error_code}), 404

    @flask_app.post("/api/login")
    def api_login():
        body = request.get_json(silent=True) or {}
        name = body.get("name")
        password = body.get("password")
        try:
            token, user = login(cfg, str(name), str(password))
        except ValueError:
            return jsonify({"error": "invalid credentials"}), 401
        resp = jsonify({"user": user})
        resp.set_cookie(SESSION_COOKIE, token, httponly=True, samesite="Lax")
        return resp

    @flask_app.post("/api/logout")
    def api_logout():
        token = request.cookies.get(SESSION_COOKIE)
        if token:
            logout(cfg, token)
        resp = jsonify({"ok": True})
        resp.delete_cookie(SESSION_COOKIE)
        return resp

    @flask_app.post("/api/users")
    def api_users_create():
        user = getattr(g, "user", None)
        if not user or user.get("role") != "owner":
            return jsonify({"error": "forbidden"}), 403
        body = request.get_json(silent=True) or {}
        try:
            return jsonify(create_user(cfg, body.get("name", ""), body.get("password", ""), body.get("role", "guest"))), 201
        except ValueError as exc:
            return jsonify({"error": str(exc)}), 400

    @flask_app.post("/api/import/<profile_id>")
    def api_import_csv(profile_id: str):
        file = request.files.get("file")
        if not file:
            return jsonify({"error": "file required"}), 400
        try:
            return jsonify(run_import(cfg, profile_id, file.read()))
        except ValidationError as exc:
            return jsonify({"error": exc.msg, "error_code": exc.error_code}), 400

    @flask_app.get("/api/sync/status")
    def api_sync_status():
        return jsonify(sync_status(cfg))

    @flask_app.get("/api/sync/export")
    def api_sync_export():
        return jsonify(export_events(cfg))

    @flask_app.post("/api/sync/import")
    def api_sync_import():
        body = request.get_json(silent=True) or {}
        try:
            return jsonify(import_batch(cfg, body))
        except ValueError as exc:
            return jsonify({"error": str(exc)}), 400

    @flask_app.post("/api/intent")
    def api_intent():
        body = request.get_json(silent=True)
        if not isinstance(body, dict):
            return jsonify({"error": "JSON object required.", "error_code": "invalid_json"}), 400
        text = body.get("text")
        if not isinstance(text, str) or not text.strip():
            return jsonify({"error": "text is required.", "error_code": "invalid_json"}), 400
        try:
            result = run_intent(
                cfg,
                text.strip(),
                request_id=g.request_id,
                complete=flask_app.config.get("LLM_COMPLETE"),
            )
        except LlmError as exc:
            status = 503 if exc.error_code == "llm_down" else 400
            return jsonify(
                {"error": public_error_message(exc), "error_code": exc.error_code}
            ), status
        except ValidationError as exc:
            return jsonify({"error": exc.msg, "error_code": exc.error_code}), 400
        except EngineError as exc:
            return jsonify({"error": exc.msg, "error_code": exc.error_code}), 500
        return jsonify(result)

    return flask_app


def _schema_version(appdir: Path) -> int:
    try:
        data = _load_schema(appdir)
        return int(data.get("version") or 0)
    except (OSError, json.JSONDecodeError, TypeError, ValueError):
        return 0


def _safe_static(subdir: str, name: str):
    if ".." in name.split("/"):
        return ("Not found", 404)
    root = (STATIC_DIR / subdir).resolve()
    target = (root / name).resolve()
    try:
        target.relative_to(root)
    except ValueError:
        return ("Not found", 404)
    if not target.is_file():
        return ("Not found", 404)
    return send_from_directory(root, name)


def main() -> None:
    if not BOOTSTRAP_CSS.is_file():
        print(
            "Bootstrap CSS is missing. Run: python3 tools/fetch_bootstrap.py",
            file=sys.stderr,
        )
        sys.exit(1)
    try:
        cfg = load_config()
    except (BindRefusedError, UnknownLlmProviderError) as exc:
        print(str(exc), file=sys.stderr)
        sys.exit(1)
    setup_logging(cfg)
    ensure_host_tables(cfg.appdir)
    ensure_owner(cfg)
    run_startup_hooks(cfg)
    start_scheduler(cfg)
    app = create_app()
    log_server_start(cfg)
    print(f"http://{cfg.bind}:{cfg.port}/", flush=True)
    app.run(host=cfg.bind, port=cfg.port, debug=False, use_reloader=False)


if __name__ == "__main__":
    main()
