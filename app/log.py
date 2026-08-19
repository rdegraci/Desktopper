"""JSON Lines logger for LLM-readable events."""

from __future__ import annotations

import json
import logging
from datetime import datetime
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from app.config import AppConfig, redact_value

_LOGGER_NAME = "desktopper"


class JsonlFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload = getattr(record, "payload", None)
        if not isinstance(payload, dict):
            payload = {
                "ts": datetime.now().isoformat(),
                "level": record.levelname.lower(),
                "event": "log.raw",
                "component": "log",
                "request_id": None,
                "ok": True,
                "schema_version": None,
                "msg": record.getMessage(),
                "detail": None,
            }
        return json.dumps(redact_value(payload), ensure_ascii=False)


def _tz(name: str) -> ZoneInfo:
    try:
        return ZoneInfo(name)
    except ZoneInfoNotFoundError:
        return ZoneInfo("UTC")


def setup_logging(cfg: AppConfig) -> logging.Logger:
    log_path = cfg.appdir / cfg.logging.file
    logger = logging.getLogger(_LOGGER_NAME)
    logger.setLevel(getattr(logging, cfg.logging.level.upper(), logging.INFO))
    for handler in list(logger.handlers):
        handler.close()
        logger.removeHandler(handler)
    logger.propagate = False
    handler = RotatingFileHandler(
        log_path,
        maxBytes=max(cfg.logging.max_bytes, 1024),
        backupCount=max(cfg.logging.backup_count, 1),
        encoding="utf-8",
    )
    handler.setFormatter(JsonlFormatter())
    logger.addHandler(handler)
    return logger


def emit(
    cfg: AppConfig,
    *,
    event: str,
    component: str,
    msg: str,
    ok: bool = True,
    level: str = "info",
    request_id: str | None = None,
    schema_version: int | None = None,
    detail: dict[str, Any] | None = None,
) -> None:
    logger = logging.getLogger(_LOGGER_NAME)
    if not logger.handlers:
        setup_logging(cfg)
    now = datetime.now(_tz(cfg.timezone)).isoformat(timespec="milliseconds")
    payload = {
        "ts": now,
        "level": level,
        "event": event,
        "component": component,
        "request_id": request_id,
        "ok": ok,
        "schema_version": schema_version,
        "msg": msg,
        "detail": detail,
    }
    log_level = getattr(logging, level.upper(), logging.INFO)
    logger.log(log_level, msg, extra={"payload": payload})


def read_recent_events(log_path: Path, limit: int) -> list[dict[str, Any]]:
    if not log_path.is_file():
        return []
    lines = log_path.read_text(encoding="utf-8").splitlines()
    events: list[dict[str, Any]] = []
    for line in lines:
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(obj, dict):
            events.append(obj)
    if limit < 1:
        return []
    return events[-limit:]


def log_config_load(cfg: AppConfig, request_id: str | None = None) -> None:
    emit(
        cfg,
        event="config.load",
        component="config",
        msg="Loaded appdir config.",
        request_id=request_id,
        schema_version=0,
        detail={
            "bind": cfg.bind,
            "port": cfg.port,
            "llm.base_url": cfg.llm.base_url,
            "llm.model": cfg.llm.model,
        },
    )


def log_server_start(cfg: AppConfig, request_id: str | None = None) -> None:
    emit(
        cfg,
        event="server.start",
        component="server",
        msg=f"Listening on http://{cfg.bind}:{cfg.port}/",
        request_id=request_id,
        schema_version=0,
        detail={"bind": cfg.bind, "port": cfg.port},
    )
