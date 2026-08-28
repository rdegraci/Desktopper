"""Ops REPL thread persistence (ops_thread.jsonl in appdir)."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

THREAD_FILE = "ops_thread.jsonl"

OPS_HELP_TITLE = "How this works"
OPS_HELP_LINES = [
    "Describe what you want in your app — tables, screens, rules, and permissions.",
    "The assistant may ask clarifying questions or show a plan before applying.",
    "Nothing changes until a plan is applied (or you confirm apply).",
    "For Python hooks and schedules, use the sections below — not this message box.",
    "After changes apply, return to the App and refresh.",
]
OPS_HELP_FOOTER = "Type help anytime to see this message again."


def help_payload() -> dict[str, Any]:
    return {
        "title": OPS_HELP_TITLE,
        "lines": list(OPS_HELP_LINES),
        "footer": OPS_HELP_FOOTER,
    }


def help_message_text() -> str:
    payload = help_payload()
    parts = [payload["title"], ""] + [f"• {line}" for line in payload["lines"]]
    if payload.get("footer"):
        parts.extend(["", str(payload["footer"])])
    return "\n".join(parts)


def append_help_exchange(appdir: Path) -> list[dict[str, Any]]:
    append_entry(appdir, {"role": "user", "text": "help"})
    append_entry(
        appdir,
        {
            "role": "assistant",
            "action": "help",
            "message": help_message_text(),
        },
    )
    return read_thread(appdir)


def _thread_path(appdir: Path) -> Path:
    return appdir / THREAD_FILE


def thread_timestamp() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def read_thread(appdir: Path) -> list[dict[str, Any]]:
    path = _thread_path(appdir)
    if not path.is_file():
        return []
    entries: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(obj, dict):
            entries.append(obj)
    return entries


def append_entry(appdir: Path, entry: dict[str, Any]) -> None:
    appdir.mkdir(parents=True, exist_ok=True)
    path = _thread_path(appdir)
    if "ts" not in entry:
        entry = {**entry, "ts": thread_timestamp()}
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(entry, ensure_ascii=False) + "\n")


def clear_thread(appdir: Path) -> None:
    path = _thread_path(appdir)
    if path.is_file():
        path.unlink()
