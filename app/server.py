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
    list_rows,
    update_row,
)
from app.log import (
    emit,
    log_config_load,
    log_server_start,
    read_recent_events,
    setup_logging,
)

STATIC_DIR = repo_root() / "static"
BOOTSTRAP_CSS = STATIC_DIR / "css" / "bootstrap.min.css"


def _load_schema(appdir: Path) -> dict:
    return read_or_create_schema(appdir)


def create_app() -> Flask:
    cfg = load_config()
    setup_logging(cfg)
    log_config_load(cfg)

    flask_app = Flask(__name__)
    flask_app.config["DESKTOPPER_CFG"] = cfg

    @flask_app.before_request
    def _assign_request_id() -> None:
        g.request_id = str(uuid.uuid4())
        g.cfg = cfg

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
        try:
            limit = int(request.args.get("limit", "50"))
            offset = int(request.args.get("offset", "0"))
        except ValueError:
            return jsonify({"error": "limit and offset must be integers."}), 400
        try:
            return jsonify(list_rows(cfg, name, limit=limit, offset=offset))
        except CrudError as err:
            return _crud_error(err)

    @flask_app.get("/api/tables/<name>/<int:row_id>")
    def api_get(name: str, row_id: int):
        try:
            return jsonify(get_row(cfg, name, row_id))
        except CrudError as err:
            return _crud_error(err)

    @flask_app.post("/api/tables/<name>")
    def api_insert(name: str):
        body = request.get_json(silent=True)
        if body is None:
            body = {}
        try:
            return jsonify(insert_row(cfg, name, body, request_id=g.request_id)), 201
        except CrudError as err:
            return _crud_error(err)

    @flask_app.put("/api/tables/<name>/<int:row_id>")
    def api_update(name: str, row_id: int):
        body = request.get_json(silent=True)
        if body is None:
            body = {}
        try:
            return jsonify(update_row(cfg, name, row_id, body, request_id=g.request_id))
        except CrudError as err:
            return _crud_error(err)

    @flask_app.delete("/api/tables/<name>/<int:row_id>")
    def api_delete(name: str, row_id: int):
        try:
            delete_row(cfg, name, row_id, request_id=g.request_id)
            return ("", 204)
        except CrudError as err:
            return _crud_error(err)

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
    except BindRefusedError as exc:
        print(str(exc), file=sys.stderr)
        sys.exit(1)
    app = create_app()
    log_server_start(cfg)
    print(f"http://{cfg.bind}:{cfg.port}/", flush=True)
    app.run(host=cfg.bind, port=cfg.port, debug=False, use_reloader=False)


if __name__ == "__main__":
    main()
