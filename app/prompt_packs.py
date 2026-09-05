"""Parse and load Ops prompt packs from markdown files."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

_STEP_HEADING_RE = re.compile(
    r"^##\s+(?:Prompt|Step)\s+(\d+)\s*[—–\-]\s*(.+?)\s*$",
    re.IGNORECASE | re.MULTILINE,
)
_TITLE_RE = re.compile(r"^#\s+(.+?)\s*$", re.MULTILINE)
_FENCE_RE = re.compile(
    r"```(?:text)?\s*\n(.*?)```",
    re.DOTALL | re.IGNORECASE,
)
_SKIP_SECTION_RE = re.compile(
    r"^##\s+(How to run|If Ops goes sideways)\b",
    re.IGNORECASE,
)


def parse_prompt_pack(markdown: str, *, filename: str | None = None) -> dict[str, Any]:
    """Parse a markdown prompt pack into title + ordered steps."""
    title = _pack_title(markdown, filename)
    steps: list[dict[str, Any]] = []
    matches = list(_STEP_HEADING_RE.finditer(markdown))
    for i, match in enumerate(matches):
        heading_title = match.group(2).strip()
        start = match.end()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(markdown)
        body = markdown[start:end]
        # Truncate at non-step ## sections so recovery text is not scanned as intent.
        skip = _SKIP_SECTION_RE.search(body)
        if skip:
            body = body[: skip.start()]
        intent = _first_intent_fence(body)
        if intent is None:
            continue
        # Only heading + non-fence prose; intent text often says "optional" for fields.
        prose = _FENCE_RE.sub("", body)
        optional = (
            "optional" in heading_title.lower() or "optional" in prose.lower()
        )
        steps.append(
            {
                "index": len(steps),
                "title": heading_title,
                "intent": intent,
                "optional": optional,
            }
        )
    return {"title": title, "steps": steps}


def examples_dir(repo: Path | None = None) -> Path:
    from app.config import repo_root

    root = repo if repo is not None else repo_root()
    return (root / "examples").resolve()


def list_example_packs(examples: Path | None = None) -> list[dict[str, Any]]:
    """List shipped markdown packs under examples/."""
    root = examples if examples is not None else examples_dir()
    if not root.is_dir():
        return []
    packs: list[dict[str, Any]] = []
    for path in sorted(root.glob("*.md")):
        if not path.is_file():
            continue
        text = path.read_text(encoding="utf-8")
        parsed = parse_prompt_pack(text, filename=path.name)
        packs.append(
            {
                "id": path.stem,
                "title": parsed["title"],
                "filename": path.name,
            }
        )
    return packs


def resolve_example_pack_path(name: str, examples: Path | None = None) -> Path | None:
    """Resolve a basename pack path under examples/; reject unsafe names."""
    root = (examples if examples is not None else examples_dir()).resolve()
    if not name or name in (".", ".."):
        return None
    if "/" in name or "\\" in name or ".." in name:
        return None
    base = name if name.endswith(".md") else f"{name}.md"
    if Path(base).name != base:
        return None
    target = (root / base).resolve()
    try:
        target.relative_to(root)
    except ValueError:
        return None
    if not target.is_file():
        return None
    return target


def load_example_pack(name: str, examples: Path | None = None) -> dict[str, Any] | None:
    """Load and parse a shipped pack by basename (with or without .md)."""
    path = resolve_example_pack_path(name, examples=examples)
    if path is None:
        return None
    text = path.read_text(encoding="utf-8")
    parsed = parse_prompt_pack(text, filename=path.name)
    return {
        "title": parsed["title"],
        "filename": path.name,
        "steps": parsed["steps"],
    }


def _pack_title(markdown: str, filename: str | None) -> str:
    match = _TITLE_RE.search(markdown)
    if match:
        return match.group(1).strip()
    if filename:
        return Path(filename).stem.replace("-", " ").replace("_", " ")
    return "Prompt pack"


def _first_intent_fence(body: str) -> str | None:
    match = _FENCE_RE.search(body)
    if not match:
        return None
    return match.group(1).strip()
