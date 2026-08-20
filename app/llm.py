"""OpenAI-compatible chat via urllib. Never log the API key."""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from typing import Any

from app.config import AppConfig, repo_root

FALLBACK_PROMPT = """You are the schema editor for a local SQLite app.
Return one JSON object only. No markdown fences. No HTML, JavaScript, or SQL.
Whitelist keys: summary, app, add_tables, add_columns, add_screens, extend_enums, update_labels, hide_columns.
Additive changes only. Table and column names snake_case [a-z][a-z0-9_]*.
Types INTEGER REAL TEXT. Do not include id, created_at, or updated_at on new tables.
"""


class LlmError(Exception):
    def __init__(self, error_code: str, msg: str, output_head: str | None = None) -> None:
        super().__init__(msg)
        self.error_code = error_code
        self.msg = msg
        self.output_head = output_head


def load_system_prompt() -> str:
    path = repo_root() / "docs" / "cache" / "MVP-PROMPT.md"
    if path.is_file():
        return path.read_text(encoding="utf-8")
    return FALLBACK_PROMPT


def strip_fences(text: str) -> str:
    body = text.strip()
    if not body.startswith("```"):
        return body
    lines = body.splitlines()
    if lines and lines[0].startswith("```"):
        lines = lines[1:]
    if lines and lines[-1].strip() == "```":
        lines = lines[:-1]
    return "\n".join(lines).strip()


def parse_json_object(text: str) -> dict[str, Any]:
    cleaned = strip_fences(text)
    try:
        data = json.loads(cleaned)
    except json.JSONDecodeError as exc:
        head = cleaned[:500]
        raise LlmError("llm_parse", "Model output is not JSON.", head) from exc
    if not isinstance(data, dict):
        raise LlmError("llm_parse", "Model output is not a JSON object.", cleaned[:500])
    return data


def chat_completion(cfg: AppConfig, messages: list[dict[str, str]]) -> str:
    base = cfg.llm.base_url.rstrip("/")
    url = base + "/chat/completions"
    payload = json.dumps(
        {
            "model": cfg.llm.model,
            "messages": messages,
            "temperature": cfg.llm.temperature,
            "max_tokens": cfg.llm.max_tokens,
        }
    ).encode("utf-8")
    req = urllib.request.Request(url, data=payload, method="POST")
    req.add_header("Content-Type", "application/json")
    if cfg.llm_api_key:
        req.add_header("Authorization", "Bearer " + cfg.llm_api_key)
    try:
        with urllib.request.urlopen(req, timeout=cfg.llm.timeout_seconds) as resp:
            raw = resp.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        raise LlmError("llm_down", f"LLM HTTP {exc.code}.") from exc
    except OSError as exc:
        raise LlmError("llm_down", "LLM is unreachable.") from exc
    try:
        body = json.loads(raw)
        content = body["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError, json.JSONDecodeError) as exc:
        raise LlmError("llm_parse", "LLM response shape is unexpected.", raw[:500]) from exc
    if not isinstance(content, str):
        raise LlmError("llm_parse", "LLM content is not text.", raw[:500])
    return content
