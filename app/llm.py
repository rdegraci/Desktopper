"""OpenAI-compatible chat via urllib. Never log the API key."""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from typing import Any

from app.config import AppConfig, redact_value, repo_root
from app.providers import resolve_provider

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


def _message_text(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for item in content:
            if isinstance(item, str):
                parts.append(item)
            elif isinstance(item, dict):
                text = item.get("text")
                if isinstance(text, str):
                    parts.append(text)
        return "".join(parts)
    return ""


def build_chat_request(
    cfg: AppConfig, messages: list[dict[str, str]]
) -> tuple[str, dict[str, str], dict[str, Any]]:
    spec = resolve_provider(cfg.llm.provider)
    base = cfg.llm.base_url.rstrip("/")
    url = base + "/chat/completions"
    payload: dict[str, Any] = {
        "model": cfg.llm.model,
        "messages": messages,
        "temperature": cfg.llm.temperature,
        spec.token_field: cfg.llm.max_tokens,
    }
    if spec.json_object:
        payload["response_format"] = {"type": "json_object"}
    if spec.reasoning and cfg.llm.reasoning_effort:
        payload["reasoning_effort"] = cfg.llm.reasoning_effort
    if spec.cache_key:
        payload["prompt_cache_key"] = spec.cache_key
    headers = {"Content-Type": "application/json"}
    if cfg.llm_api_key:
        headers["Authorization"] = "Bearer " + cfg.llm_api_key
    if spec.cache_header and spec.cache_key:
        headers[spec.cache_header] = spec.cache_key
    return url, headers, payload


def chat_completion(cfg: AppConfig, messages: list[dict[str, str]]) -> str:
    url, headers, payload = build_chat_request(cfg, messages)
    body_bytes = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(url, data=body_bytes, method="POST")
    for key, value in headers.items():
        req.add_header(key, value)
    try:
        with urllib.request.urlopen(req, timeout=cfg.llm.timeout_seconds) as resp:
            raw = resp.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        err_body = ""
        try:
            err_body = exc.read().decode("utf-8", errors="replace")[:500]
        except OSError:
            err_body = ""
        raise LlmError("llm_down", f"LLM HTTP {exc.code}.", err_body) from exc
    except OSError as exc:
        raise LlmError("llm_down", "LLM is unreachable.") from exc
    try:
        body = json.loads(raw)
        content = body["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError, json.JSONDecodeError) as exc:
        raise LlmError("llm_parse", "LLM response shape is unexpected.", raw[:500]) from exc
    text = _message_text(content)
    if not text:
        raise LlmError("llm_parse", "LLM content is not text.", raw[:500])
    return text


def public_error_message(exc: LlmError) -> str:
    """Safe one-line error for the browser. Never includes the API key."""
    msg = exc.msg
    head = (exc.output_head or "").strip()
    extra = ""
    if head:
        try:
            data = json.loads(head)
            if isinstance(data, dict):
                err = data.get("error")
                if isinstance(err, str):
                    extra = err
                elif isinstance(err, dict) and isinstance(err.get("message"), str):
                    extra = err["message"]
        except json.JSONDecodeError:
            extra = head
    extra = str(redact_value(extra)).strip()
    if extra and extra not in msg:
        return f"{msg} {extra}"[:500]
    return msg
