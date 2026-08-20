"""List and global search with bound LIKE. No FTS."""

from __future__ import annotations

from typing import Any

from app.config import AppConfig, read_or_create_schema
from app.crud import (
    CrudError,
    _columns,
    _connect,
    _quote_ident,
    _require_table,
    _row_to_dict,
    _select_sql,
    _tables,
)
from app.log import emit
from app.schema_validate import NAME_RE, SYSTEM_COLUMNS

MAX_Q = 200


def split_query(q: str | None) -> list[str]:
    if q is None:
        return []
    if len(q) > MAX_Q:
        raise CrudError(400, "Query is too long.")
    return [part for part in q.split() if part]


def escape_like(token: str) -> str:
    return token.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def _searchable(schema: dict[str, Any], table_name: str, table: dict[str, Any]) -> list[str]:
    """SQL boolean fragments using alias t. Each uses one bound token."""
    fragments: list[str] = []
    t_ident = _quote_ident(table_name)
    for col in _columns(table):
        name = col["name"]
        if name == "id" or name in SYSTEM_COLUMNS:
            continue
        if col.get("hidden"):
            continue
        if col.get("widget") == "fk":
            fk = col.get("fk") or {}
            target = fk.get("table")
            display = fk.get("display")
            if not NAME_RE.match(str(target or "")) or not NAME_RE.match(str(display or "")):
                continue
            if target not in _tables(schema):
                continue
            fragments.append(
                "EXISTS (SELECT 1 FROM "
                + _quote_ident(str(target))
                + " WHERE "
                + _quote_ident(str(target))
                + "."
                + _quote_ident("id")
                + " = "
                + t_ident
                + "."
                + _quote_ident(name)
                + " AND "
                + _quote_ident(str(target))
                + "."
                + _quote_ident(str(display))
                + " LIKE '%' || ? || '%' ESCAPE '\\' COLLATE NOCASE)"
            )
            continue
        if col.get("type") != "TEXT":
            continue
        fragments.append(
            t_ident
            + "."
            + _quote_ident(name)
            + " LIKE '%' || ? || '%' ESCAPE '\\' COLLATE NOCASE"
        )
    return fragments


def _where_for_tokens(
    schema: dict[str, Any], table_name: str, table: dict[str, Any], tokens: list[str]
) -> tuple[str, list[str]]:
    frags = _searchable(schema, table_name, table)
    if not tokens:
        return "", []
    if not frags:
        return " AND 0", []
    token_clauses = []
    params: list[str] = []
    for token in tokens:
        escaped = escape_like(token)
        or_sql = "(" + " OR ".join(frags) + ")"
        token_clauses.append(or_sql)
        params.extend([escaped] * len(frags))
    return " AND " + " AND ".join(token_clauses), params


def _fk_filter_sql(table: dict[str, Any], filters: dict[str, str]) -> tuple[str, list[int]]:
    if not filters:
        return "", []
    cmap = {c["name"]: c for c in _columns(table)}
    sql = ""
    params: list[int] = []
    for name, raw in filters.items():
        if not NAME_RE.match(name):
            raise CrudError(400, "Bad filter name.")
        col = cmap.get(name)
        if not col or col.get("widget") != "fk":
            raise CrudError(400, f"Cannot filter on {name}.")
        try:
            params.append(int(raw))
        except (TypeError, ValueError):
            raise CrudError(400, f"{name} must be an integer.") from None
        sql += " AND " + _quote_ident(name) + " = ?"
    return sql, params


def list_rows_search(
    cfg: AppConfig,
    table_name: str,
    *,
    q: str | None = None,
    filters: dict[str, str] | None = None,
    limit: int = 50,
    offset: int = 0,
    request_id: str | None = None,
) -> list[dict[str, Any]]:
    schema = read_or_create_schema(cfg.appdir)
    table = _require_table(schema, table_name)
    tokens = split_query(q)
    limit = max(1, min(int(limit), 200))
    offset = max(0, int(offset))
    sql = _select_sql(table_name, table)
    extra, params = _where_for_tokens(schema, table_name, table, tokens)
    filter_sql, filter_params = _fk_filter_sql(table, filters or {})
    if extra or filter_sql:
        sql += " WHERE 1=1" + filter_sql + extra
    sql += " ORDER BY " + _quote_ident("id") + " LIMIT ? OFFSET ?"
    conn = _connect(cfg)
    try:
        cur = conn.execute(sql, tuple(filter_params) + tuple(params) + (limit, offset))
        rows = [_row_to_dict(cur, row) for row in cur.fetchall()]
    finally:
        conn.close()
    emit(
        cfg,
        event="search.list",
        component="search",
        msg="List search finished.",
        level="debug",
        request_id=request_id,
        schema_version=int(schema.get("version") or 0),
        detail={"q_len": 0 if q is None else len(q), "hit_count": len(rows)},
    )
    return rows


def _list_screens(schema: dict[str, Any]) -> list[dict[str, Any]]:
    out = []
    for screen in schema.get("screens") or []:
        if isinstance(screen, dict) and screen.get("type") == "list":
            tname = screen.get("table")
            if isinstance(tname, str) and NAME_RE.match(tname):
                out.append(screen)
    return out


def global_search(
    cfg: AppConfig,
    q: str | None,
    *,
    limit: int = 50,
    request_id: str | None = None,
) -> dict[str, Any]:
    tokens = split_query(q)
    if not tokens:
        emit(
            cfg,
            event="search.global",
            component="search",
            msg="Global search empty query.",
            level="debug",
            request_id=request_id,
            schema_version=int(read_or_create_schema(cfg.appdir).get("version") or 0),
            detail={"q_len": 0 if q is None else len(q), "hit_count": 0},
        )
        return {"hits": []}
    schema = read_or_create_schema(cfg.appdir)
    per_table = max(1, min(int(limit), 50))
    hits: list[dict[str, Any]] = []
    conn = _connect(cfg)
    try:
        for screen in _list_screens(schema):
            if screen.get("nav") is False:
                continue
            tname = screen["table"]
            tables = _tables(schema)
            if tname not in tables:
                continue
            table = tables[tname]
            extra, params = _where_for_tokens(schema, tname, table, tokens)
            label_col = "id"
            cols = screen.get("columns") or []
            if cols and isinstance(cols[0], str) and NAME_RE.match(cols[0]):
                label_col = cols[0]
            sql = (
                "SELECT "
                + _quote_ident("id")
                + " AS id, "
                + _quote_ident(label_col)
                + " AS label FROM "
                + _quote_ident(tname)
                + " WHERE 1=1"
                + extra
                + " ORDER BY "
                + _quote_ident("id")
                + " LIMIT ?"
            )
            cur = conn.execute(sql, tuple(params) + (per_table,))
            for row in cur.fetchall():
                hits.append(
                    {
                        "table": tname,
                        "id": row["id"],
                        "label": row["label"],
                        "screen": screen.get("id"),
                    }
                )
    finally:
        conn.close()
    emit(
        cfg,
        event="search.global",
        component="search",
        msg="Global search finished.",
        level="debug",
        request_id=request_id,
        schema_version=int(schema.get("version") or 0),
        detail={"q_len": 0 if q is None else len(q), "hit_count": len(hits)},
    )
    return {"hits": hits}
