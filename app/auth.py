"""Local users, sessions, and grant checks."""

from __future__ import annotations

import hashlib
import hmac
import os
import secrets
import sqlite3
from datetime import datetime, timedelta, timezone
from functools import wraps
from typing import Any, Callable

from flask import g, jsonify, request

from app.config import AppConfig, read_or_create_schema
from app.host_db import connect

SESSION_COOKIE = "desktopper_session"
SESSION_HOURS = 72
OWNER_ROLE = "owner"


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _hash_password(password: str, salt: bytes | None = None) -> str:
    salt = salt or os.urandom(16)
    digest = hashlib.scrypt(password.encode("utf-8"), salt=salt, n=2**14, r=8, p=1)
    return salt.hex() + ":" + digest.hex()


def _verify_password(password: str, stored: str) -> bool:
    try:
        salt_hex, digest_hex = stored.split(":", 1)
        salt = bytes.fromhex(salt_hex)
        digest = hashlib.scrypt(password.encode("utf-8"), salt=salt, n=2**14, r=8, p=1)
        return hmac.compare_digest(digest.hex(), digest_hex)
    except (ValueError, TypeError):
        return False


def _token_hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def ensure_owner(cfg: AppConfig) -> None:
    conn = connect(cfg.appdir)
    try:
        cur = conn.execute("SELECT COUNT(*) FROM _users")
        if int(cur.fetchone()[0]) > 0:
            return
        name = cfg.auth.owner_name.strip() or "admin"
        password = cfg.auth.owner_password.strip()
        if not password:
            password = secrets.token_urlsafe(12)
            print(f"Desktopper owner username (one-time): {name}", flush=True)
            print(f"Desktopper owner password (one-time): {password}", flush=True)
        else:
            print(
                f"Desktopper owner account created: {name!r} (password from conf.yaml or .env)",
                flush=True,
            )
        now = _now_iso()
        conn.execute(
            "INSERT INTO _users (name, password_hash, role, created_at) VALUES (?, ?, ?, ?)",
            (name, _hash_password(password), OWNER_ROLE, now),
        )
        conn.commit()
    finally:
        conn.close()


def list_users(cfg: AppConfig) -> list[dict[str, Any]]:
    conn = connect(cfg.appdir)
    try:
        cur = conn.execute(
            "SELECT id, name, role, created_at FROM _users ORDER BY id"
        )
        return [
            {"id": row[0], "name": row[1], "role": row[2], "created_at": row[3]}
            for row in cur.fetchall()
        ]
    finally:
        conn.close()


def create_user(cfg: AppConfig, name: str, password: str, role: str) -> dict[str, Any]:
    if not name or not password:
        raise ValueError("name and password required")
    if role == OWNER_ROLE:
        raise ValueError("cannot create owner role")
    conn = connect(cfg.appdir)
    try:
        conn.execute(
            "INSERT INTO _users (name, password_hash, role, created_at) VALUES (?, ?, ?, ?)",
            (name, _hash_password(password), role, _now_iso()),
        )
        conn.commit()
        cur = conn.execute("SELECT id, name, role, created_at FROM _users WHERE name = ?", (name,))
        row = cur.fetchone()
        return {"id": row[0], "name": row[1], "role": row[2], "created_at": row[3]}
    except sqlite3.IntegrityError as exc:
        raise ValueError("user exists") from exc
    finally:
        conn.close()


def login(cfg: AppConfig, name: str, password: str) -> tuple[str, dict[str, Any]]:
    conn = connect(cfg.appdir)
    try:
        cur = conn.execute(
            "SELECT id, name, password_hash, role FROM _users WHERE name = ?",
            (name,),
        )
        row = cur.fetchone()
        if not row or not _verify_password(password, row[2]):
            raise ValueError("invalid credentials")
        token = secrets.token_urlsafe(32)
        expires = (datetime.now(timezone.utc) + timedelta(hours=SESSION_HOURS)).strftime(
            "%Y-%m-%dT%H:%M:%SZ"
        )
        conn.execute(
            "INSERT INTO _sessions (token_hash, user_id, expires_at) VALUES (?, ?, ?)",
            (_token_hash(token), row[0], expires),
        )
        conn.commit()
        return token, {"id": row[0], "name": row[1], "role": row[3]}
    finally:
        conn.close()


def logout(cfg: AppConfig, token: str) -> None:
    conn = connect(cfg.appdir)
    try:
        conn.execute("DELETE FROM _sessions WHERE token_hash = ?", (_token_hash(token),))
        conn.commit()
    finally:
        conn.close()


def expire_sessions(cfg: AppConfig) -> int:
    conn = connect(cfg.appdir)
    try:
        cur = conn.execute(
            "DELETE FROM _sessions WHERE expires_at < ?",
            (_now_iso(),),
        )
        conn.commit()
        return cur.rowcount
    finally:
        conn.close()


def current_user(cfg: AppConfig) -> dict[str, Any] | None:
    token = request.cookies.get(SESSION_COOKIE)
    if not token:
        return None
    conn = connect(cfg.appdir)
    try:
        cur = conn.execute(
            """
            SELECT u.id, u.name, u.role FROM _sessions s
            JOIN _users u ON u.id = s.user_id
            WHERE s.token_hash = ? AND s.expires_at >= ?
            """,
            (_token_hash(token), _now_iso()),
        )
        row = cur.fetchone()
        if not row:
            return None
        return {"id": row[0], "name": row[1], "role": row[2]}
    finally:
        conn.close()


def _grants_for_role(schema: dict[str, Any], role: str) -> list[dict[str, Any]]:
    return [
        g
        for g in (schema.get("grants") or [])
        if isinstance(g, dict) and g.get("role") == role and g.get("enabled", True) is not False
    ]


def check_grant(
    cfg: AppConfig,
    *,
    table: str,
    action: str,
    user: dict[str, Any] | None,
) -> bool:
    if user and user.get("role") == OWNER_ROLE:
        return True
    schema = read_or_create_schema(cfg.appdir)
    grants = schema.get("grants") or []
    if not grants:
        return user is not None
    if not user:
        return False
    role = user.get("role")
    role_grants = _grants_for_role(schema, role)
    if not role_grants:
        return False
    for grant in role_grants:
        if grant.get("table") == table and grant.get("action") == action:
            return bool(grant.get("allow", True))
    return False


def filter_columns_for_role(schema: dict[str, Any], table: str, user: dict[str, Any] | None) -> set[str] | None:
    if user and user.get("role") == OWNER_ROLE:
        return None
    role = user.get("role") if user else None
    if not role:
        return set()
    hidden: set[str] = set()
    for grant in _grants_for_role(schema, role):
        if grant.get("table") != table:
            continue
        cols = grant.get("columns")
        if isinstance(cols, dict):
            for col, mode in cols.items():
                if mode == "hide":
                    hidden.add(col)
    return hidden


def require_auth(*, mutating: bool = False) -> Callable:
    def decorator(fn: Callable) -> Callable:
        @wraps(fn)
        def wrapper(*args, **kwargs):
            cfg: AppConfig = g.cfg
            user = current_user(cfg)
            g.user = user
            if mutating and user is None:
                grants = read_or_create_schema(cfg.appdir).get("grants") or []
                if grants:
                    return jsonify({"error": "login required", "error_code": "unauthorized"}), 401
            return fn(*args, **kwargs)

        return wrapper

    return decorator
