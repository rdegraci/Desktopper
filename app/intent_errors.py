"""Helpers for intent validation failures."""

from __future__ import annotations

import json
from typing import Any

_REJECTED_DIFF_MAX_BYTES = 8192


def truncate_rejected_diff(diff: dict[str, Any]) -> dict[str, Any]:
    text = json.dumps(diff, separators=(",", ":"))
    if len(text.encode("utf-8")) <= _REJECTED_DIFF_MAX_BYTES:
        return diff
    slim = {"summary": diff.get("summary"), "_truncated": True}
    for key, val in diff.items():
        if key == "summary":
            continue
        slim[key] = val
        if len(json.dumps(slim, separators=(",", ":")).encode("utf-8")) > _REJECTED_DIFF_MAX_BYTES:
            slim.pop(key)
            break
    return slim
