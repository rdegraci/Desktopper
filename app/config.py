"""Appdir, copy-once examples, and conf.yaml / .env loading."""

from __future__ import annotations

import json
import os
import re
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from app.providers import (
    REASONING_EFFORTS,
    pick_api_key,
    resolve_provider,
)

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_SUPPORT_NAME = "Desktopper"
EMPTY_SCHEMA = {
    "version": 0,
    "app": {"title": "Desktopper"},
    "tables": {},
    "screens": [],
    "formulas": [],
    "rules": [],
    "roles": [],
    "grants": [],
    "import_profiles": [],
    "layouts": [],
    "reminders": [],
    "jobs": [],
    "sync": {"tables": [], "label": "Home"},
}


class BindRefusedError(Exception):
    error_code = "bind_refused"

    def __init__(self, bind: str) -> None:
        super().__init__(
            f"bind {bind!r} is not allowed. Use a loopback address in conf.yaml."
        )
        self.bind = bind


@dataclass
class LlmConfig:
    provider: str
    base_url: str
    model: str
    temperature: float
    timeout_seconds: int
    max_tokens: int
    reasoning_effort: str | None


@dataclass
class LoggingConfig:
    level: str
    file: str
    max_bytes: int
    backup_count: int


@dataclass
class AppConfig:
    appdir: Path
    bind: str
    port: int
    timezone: str
    support_name: str
    llm: LlmConfig
    logging: LoggingConfig
    llm_api_key: str

    def public_dict(self) -> dict[str, Any]:
        """Values safe to show in the browser. Never includes the API key."""
        return {
            "bind": self.bind,
            "port": self.port,
            "timezone": self.timezone,
            "llm": {
                "provider": self.llm.provider,
                "base_url": self.llm.base_url,
                "model": self.llm.model,
            },
        }


def repo_root() -> Path:
    return REPO_ROOT


def resolve_appdir() -> Path:
    override = os.environ.get("DESKTOPPER_APPDIR", "").strip()
    if override:
        return Path(override).expanduser().resolve()
    return (
        Path.home() / "Library" / "Application Support" / DEFAULT_SUPPORT_NAME
    ).resolve()


def _parse_env_file(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    if not path.is_file():
        return values
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            continue
        key, _, rest = line.partition("=")
        key = key.strip()
        if not key:
            continue
        values[key] = rest.strip()
    return values


def _copy_if_missing(src: Path, dest: Path) -> None:
    if dest.exists():
        return
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dest)


def schema_path(appdir: Path) -> Path:
    return appdir / "schema.json"


def write_empty_schema(appdir: Path) -> dict:
    path = schema_path(appdir)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "version": EMPTY_SCHEMA["version"],
        "app": dict(EMPTY_SCHEMA["app"]),
        "tables": {},
        "screens": [],
    }
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return payload


def read_or_create_schema(appdir: Path) -> dict:
    path = schema_path(appdir)
    if not path.is_file():
        return write_empty_schema(appdir)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return write_empty_schema(appdir)
    if not isinstance(data, dict):
        return write_empty_schema(appdir)
    data.setdefault("version", 0)
    data.setdefault("app", {"title": "Desktopper"})
    if not isinstance(data.get("app"), dict):
        data["app"] = {"title": "Desktopper"}
    data["app"].setdefault("title", "Desktopper")
    data.setdefault("tables", {})
    data.setdefault("screens", [])
    for key, default in (
        ("formulas", []),
        ("rules", []),
        ("roles", []),
        ("grants", []),
        ("import_profiles", []),
        ("layouts", []),
        ("reminders", []),
        ("jobs", []),
    ):
        data.setdefault(key, default if isinstance(default, list) else default)
        if not isinstance(data[key], list):
            data[key] = []
    data.setdefault("sync", {"tables": [], "label": "Home"})
    if not isinstance(data.get("sync"), dict):
        data["sync"] = {"tables": [], "label": "Home"}
    if not isinstance(data["tables"], dict):
        data["tables"] = {}
    if not isinstance(data["screens"], list):
        data["screens"] = []
    return data


def ensure_appdir(appdir: Path | None = None) -> Path:
    path = appdir if appdir is not None else resolve_appdir()
    path.mkdir(parents=True, exist_ok=True)
    (path / "migrations").mkdir(exist_ok=True)
    (path / "hooks").mkdir(exist_ok=True)
    _copy_if_missing(REPO_ROOT / ".env.example", path / ".env")
    _copy_if_missing(REPO_ROOT / "config.yaml.example", path / "conf.yaml")
    read_or_create_schema(path)
    return path


def load_config(appdir: Path | None = None) -> AppConfig:
    path = ensure_appdir(appdir)
    conf_path = path / "conf.yaml"
    raw = yaml.safe_load(conf_path.read_text(encoding="utf-8")) or {}
    if not isinstance(raw, dict):
        raise ValueError("conf.yaml must be a mapping")

    server = raw.get("server") or {}
    llm_raw = raw.get("llm") or {}
    app_raw = raw.get("app") or {}
    log_raw = raw.get("logging") or {}

    bind = str(server.get("bind", "127.0.0.1")).strip()
    if bind == "0.0.0.0":
        raise BindRefusedError(bind)

    env = _parse_env_file(path / ".env")
    spec = resolve_provider(llm_raw.get("provider"))
    api_key = pick_api_key(env, spec)

    base_url = str(llm_raw.get("base_url") or spec.base_url).strip()
    model = str(llm_raw.get("model") or spec.default_model).strip()
    effort_raw = str(llm_raw.get("reasoning_effort") or "").strip().lower()
    reasoning_effort = None
    if spec.reasoning:
        reasoning_effort = effort_raw if effort_raw in REASONING_EFFORTS else "low"

    cfg = AppConfig(
        appdir=path,
        bind=bind,
        port=int(server.get("port", 8000)),
        timezone=str(app_raw.get("timezone", "America/New_York")),
        support_name=str(app_raw.get("support_name", DEFAULT_SUPPORT_NAME)),
        llm=LlmConfig(
            provider=spec.name,
            base_url=base_url,
            model=model,
            temperature=float(llm_raw.get("temperature", 0.0)),
            timeout_seconds=int(llm_raw.get("timeout_seconds", 120)),
            max_tokens=int(llm_raw.get("max_tokens", 4096)),
            reasoning_effort=reasoning_effort,
        ),
        logging=LoggingConfig(
            level=str(log_raw.get("level", "info")).lower(),
            file=str(log_raw.get("file", "desktopper.jsonl")),
            max_bytes=int(log_raw.get("max_bytes", 2000000)),
            backup_count=int(log_raw.get("backup_count", 3)),
        ),
        llm_api_key=api_key,
    )
    return cfg


_SK_RE = re.compile(r"sk-[A-Za-z0-9]{20,}")
_XAI_RE = re.compile(r"xai-[A-Za-z0-9_-]{20,}")


def redact_value(value: Any) -> Any:
    if isinstance(value, str):
        return _XAI_RE.sub("[redacted]", _SK_RE.sub("[redacted]", value))
    if isinstance(value, dict):
        return {k: redact_value(v) for k, v in value.items()}
    if isinstance(value, list):
        return [redact_value(v) for v in value]
    return value
