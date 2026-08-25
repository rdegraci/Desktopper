"""Shared SQLite path and identifier helpers."""

from __future__ import annotations

from pathlib import Path

DB_NAME = "app.sqlite"


def db_path(appdir: Path) -> Path:
    return appdir / DB_NAME


def quote_ident(name: str) -> str:
    return '"' + name.replace('"', "") + '"'
