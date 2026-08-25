"""Validate and evaluate formula expression trees."""

from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta, timezone
from typing import Any

from app.db_paths import db_path, quote_ident as _quote_ident
from app.schema_validate import NAME_RE, ValidationError

ALLOWED_OPS = frozenset(
    {
        "lit",
        "col",
        "now",
        "week_start",
        "eq",
        "neq",
        "lt",
        "lte",
        "gt",
        "gte",
        "and",
        "or",
        "not",
        "add",
        "sub",
        "mul",
        "div",
        "if",
        "sum",
        "count",
        "avg",
        "min",
        "max",
    }
)
MAX_DEPTH = 32
FORMULA_KEYS = {"id", "kind", "table", "result", "expr", "enabled", "store"}


def validate_formula(obj: dict[str, Any], schema: dict[str, Any]) -> None:
    if not isinstance(obj, dict):
        raise ValidationError("bad_formula", "Formula must be an object.")
    extra = set(obj) - FORMULA_KEYS
    if extra:
        raise ValidationError("unknown_key", f"Formula has unknown keys: {sorted(extra)}.")
    fid = obj.get("id")
    if not isinstance(fid, str) or not NAME_RE.match(fid):
        raise ValidationError("bad_formula", "Formula id must be snake_case.")
    kind = obj.get("kind")
    if kind not in ("row", "aggregate"):
        raise ValidationError("bad_formula", "kind must be row or aggregate.")
    if kind == "row":
        table = obj.get("table")
        if not isinstance(table, str) or table not in (schema.get("tables") or {}):
            raise ValidationError("bad_formula", "row formula requires a valid table.")
    expr = obj.get("expr")
    if not isinstance(expr, dict):
        raise ValidationError("bad_formula", "expr is required.")
    _validate_expr(expr, schema, depth=0)


def _validate_expr(node: Any, schema: dict[str, Any], *, depth: int) -> None:
    if depth > MAX_DEPTH:
        raise ValidationError("bad_formula", "Expression too deep.")
    if not isinstance(node, dict):
        raise ValidationError("bad_formula", "Expression nodes must be objects.")
    op = node.get("op")
    if op not in ALLOWED_OPS:
        raise ValidationError("bad_formula", f"Unknown op: {op!r}.")
    if op == "lit":
        if "value" not in node:
            raise ValidationError("bad_formula", "lit requires value.")
        return
    if op == "col":
        col = node.get("column")
        if not isinstance(col, str):
            raise ValidationError("bad_formula", "col requires column.")
        table = node.get("table")
        if table is not None:
            _check_column(schema, table, col)
        return
    if op in ("now",):
        return
    if op == "week_start":
        _validate_expr(node.get("of"), schema, depth=depth + 1)
        return
    if op in ("eq", "neq", "lt", "lte", "gt", "gte", "add", "sub", "mul", "div"):
        _validate_expr(node.get("left"), schema, depth=depth + 1)
        _validate_expr(node.get("right"), schema, depth=depth + 1)
        return
    if op in ("and", "or"):
        args = node.get("args")
        if not isinstance(args, list):
            raise ValidationError("bad_formula", f"{op} requires args list.")
        for arg in args:
            _validate_expr(arg, schema, depth=depth + 1)
        return
    if op == "not":
        _validate_expr(node.get("arg"), schema, depth=depth + 1)
        return
    if op == "if":
        for key in ("test", "then", "else"):
            _validate_expr(node.get(key), schema, depth=depth + 1)
        return
    if op in ("sum", "count", "avg", "min", "max"):
        table = node.get("table")
        if not isinstance(table, str) or table not in (schema.get("tables") or {}):
            raise ValidationError("bad_formula", f"{op} requires valid table.")
        if op != "count":
            col = node.get("column")
            if not isinstance(col, str):
                raise ValidationError("bad_formula", f"{op} requires column.")
            _check_column(schema, table, col)
        filt = node.get("filter")
        if filt is not None:
            _validate_expr(filt, schema, depth=depth + 1)


def _check_column(schema: dict[str, Any], table: str, column: str) -> None:
    tdef = (schema.get("tables") or {}).get(table)
    if not isinstance(tdef, dict):
        raise ValidationError("bad_formula", f"Unknown table {table!r}.")
    names = {c.get("name") for c in (tdef.get("columns") or []) if isinstance(c, dict)}
    names |= {"id", "created_at", "updated_at"}
    if column not in names:
        raise ValidationError("bad_formula", f"Unknown column {table}.{column}.")


def _week_start(dt: datetime) -> datetime:
    monday = dt.date() - timedelta(days=dt.weekday())
    return datetime(monday.year, monday.month, monday.day, tzinfo=dt.tzinfo)


def _normalize_compare(left: Any, right: Any) -> tuple[Any, Any]:
    if isinstance(left, str) and isinstance(right, datetime):
        right = right.strftime("%Y-%m-%d")
        left = left[:10] if len(left) >= 10 else left
    if isinstance(right, str) and isinstance(left, datetime):
        left = left.strftime("%Y-%m-%d")
        right = right[:10] if len(right) >= 10 else right
    return left, right


def eval_expr(
    node: dict[str, Any],
    *,
    schema: dict[str, Any],
    row: dict[str, Any] | None = None,
    conn: sqlite3.Connection | None = None,
    default_tz: str = "UTC",
) -> Any:
    op = node["op"]
    if op == "lit":
        return node.get("value")
    if op == "col":
        if row is not None:
            return row.get(node["column"])
        raise ValueError("col in aggregate context needs SQL compile")
    if op == "now":
        from zoneinfo import ZoneInfo

        return datetime.now(ZoneInfo(default_tz))
    if op == "week_start":
        val = eval_expr(node["of"], schema=schema, row=row, conn=conn, default_tz=default_tz)
        if isinstance(val, datetime):
            return _week_start(val)
        return _week_start(datetime.now(timezone.utc))
    if op in ("eq", "neq", "lt", "lte", "gt", "gte"):
        left = eval_expr(node["left"], schema=schema, row=row, conn=conn, default_tz=default_tz)
        right = eval_expr(node["right"], schema=schema, row=row, conn=conn, default_tz=default_tz)
        left, right = _normalize_compare(left, right)
        if op == "eq":
            return left == right
        if op == "neq":
            return left != right
        if op == "lt":
            return left is not None and right is not None and left < right
        if op == "lte":
            return left is not None and right is not None and left <= right
        if op == "gt":
            return left is not None and right is not None and left > right
        if op == "gte":
            return left is not None and right is not None and left >= right
    if op == "and":
        return all(
            eval_expr(a, schema=schema, row=row, conn=conn, default_tz=default_tz)
            for a in (node.get("args") or [])
        )
    if op == "or":
        args = node.get("args") or []
        return any(eval_expr(a, schema=schema, row=row, conn=conn, default_tz=default_tz) for a in args)
    if op == "not":
        return not eval_expr(node["arg"], schema=schema, row=row, conn=conn, default_tz=default_tz)
    if op == "add":
        l = eval_expr(node["left"], schema=schema, row=row, conn=conn, default_tz=default_tz)
        r = eval_expr(node["right"], schema=schema, row=row, conn=conn, default_tz=default_tz)
        if l is None or r is None:
            return None
        return l + r
    if op == "sub":
        l = eval_expr(node["left"], schema=schema, row=row, conn=conn, default_tz=default_tz)
        r = eval_expr(node["right"], schema=schema, row=row, conn=conn, default_tz=default_tz)
        if l is None or r is None:
            return None
        return l - r
    if op == "mul":
        l = eval_expr(node["left"], schema=schema, row=row, conn=conn, default_tz=default_tz)
        r = eval_expr(node["right"], schema=schema, row=row, conn=conn, default_tz=default_tz)
        if l is None or r is None:
            return None
        return l * r
    if op == "div":
        l = eval_expr(node["left"], schema=schema, row=row, conn=conn, default_tz=default_tz)
        r = eval_expr(node["right"], schema=schema, row=row, conn=conn, default_tz=default_tz)
        if l is None or r is None or r == 0:
            return None
        return l / r
    if op == "if":
        test = eval_expr(node["test"], schema=schema, row=row, conn=conn, default_tz=default_tz)
        branch = node["then"] if test else node["else"]
        return eval_expr(branch, schema=schema, row=row, conn=conn, default_tz=default_tz)
    if op in ("sum", "count", "avg", "min", "max"):
        if conn is None:
            raise ValueError("aggregate requires connection")
        return _eval_aggregate(node, schema=schema, conn=conn, default_tz=default_tz)
    return None


def _filter_sql(node: dict[str, Any], table: str, schema: dict[str, Any], default_tz: str) -> tuple[str, list[Any]]:
    op = node["op"]
    if op == "lit":
        return ("?", [node.get("value")])
    if op == "col":
        return (f"{_quote_ident(node['column'])}", [])
    if op == "eq":
        lsql, lp = _filter_sql(node["left"], table, schema, default_tz)
        rsql, rp = _filter_sql(node["right"], table, schema, default_tz)
        return (f"({lsql} = {rsql})", lp + rp)
    if op == "neq":
        lsql, lp = _filter_sql(node["left"], table, schema, default_tz)
        rsql, rp = _filter_sql(node["right"], table, schema, default_tz)
        return (f"({lsql} != {rsql})", lp + rp)
    if op == "lt":
        lsql, lp = _filter_sql(node["left"], table, schema, default_tz)
        rsql, rp = _filter_sql(node["right"], table, schema, default_tz)
        return (f"({lsql} < {rsql})", lp + rp)
    if op == "lte":
        lsql, lp = _filter_sql(node["left"], table, schema, default_tz)
        rsql, rp = _filter_sql(node["right"], table, schema, default_tz)
        return (f"({lsql} <= {rsql})", lp + rp)
    if op == "gt":
        lsql, lp = _filter_sql(node["left"], table, schema, default_tz)
        rsql, rp = _filter_sql(node["right"], table, schema, default_tz)
        return (f"({lsql} > {rsql})", lp + rp)
    if op == "gte":
        lsql, lp = _filter_sql(node["left"], table, schema, default_tz)
        rsql, rp = _filter_sql(node["right"], table, schema, default_tz)
        return (f"({lsql} >= {rsql})", lp + rp)
    if op == "and":
        parts, params = [], []
        for arg in node.get("args") or []:
            s, p = _filter_sql(arg, table, schema, default_tz)
            parts.append(s)
            params.extend(p)
        return ("(" + " AND ".join(parts) + ")", params)
    if op == "or":
        parts, params = [], []
        for arg in node.get("args") or []:
            s, p = _filter_sql(arg, table, schema, default_tz)
            parts.append(s)
            params.extend(p)
        return ("(" + " OR ".join(parts) + ")", params)
    if op == "now":
        from zoneinfo import ZoneInfo

        return ("?", [datetime.now(ZoneInfo(default_tz)).isoformat()])
    if op == "week_start":
        val = eval_expr(node["of"], schema=schema, conn=None, default_tz=default_tz)
        if isinstance(val, datetime):
            ws = _week_start(val)
        else:
            ws = _week_start(datetime.now(timezone.utc))
        return ("?", [ws.strftime("%Y-%m-%d")])
    raise ValidationError("bad_formula", f"Cannot compile filter op {op!r}.")


def _eval_aggregate(
    node: dict[str, Any],
    *,
    schema: dict[str, Any],
    conn: sqlite3.Connection,
    default_tz: str,
) -> Any:
    table = node["table"]
    op = node["op"]
    where = ""
    params: list[Any] = []
    filt = node.get("filter")
    if filt is not None:
        wsql, params = _filter_sql(filt, table, schema, default_tz)
        where = f" WHERE {wsql}"
    qtable = _quote_ident(table)
    if op == "count":
        sql = f"SELECT COUNT(*) FROM {qtable}{where}"
    else:
        col = _quote_ident(node["column"])
        sql = f"SELECT {op.upper()}({col}) FROM {qtable}{where}"
    cur = conn.execute(sql, params)
    val = cur.fetchone()[0]
    return val


def evaluate_formula(cfg, formula_id: str, schema: dict[str, Any] | None = None) -> Any:
    from app.config import read_or_create_schema

    schema = schema or read_or_create_schema(cfg.appdir)
    formula = None
    for item in schema.get("formulas") or []:
        if isinstance(item, dict) and item.get("id") == formula_id:
            formula = item
            break
    if not formula or formula.get("enabled") is False:
        raise ValidationError("not_found", f"Formula {formula_id!r} not found.")
    expr = formula.get("expr")
    conn = sqlite3.connect(str(db_path(cfg.appdir)))
    try:
        if formula.get("kind") == "aggregate":
            return eval_expr(expr, schema=schema, conn=conn, default_tz=cfg.timezone)
        raise ValidationError("bad_formula", "Only aggregate formulas can be evaluated via API.")
    finally:
        conn.close()


def eval_row_formulas(cfg, table: str, row: dict[str, Any], schema: dict[str, Any]) -> dict[str, Any]:
    out = dict(row)
    for formula in schema.get("formulas") or []:
        if not isinstance(formula, dict) or formula.get("enabled") is False:
            continue
        if formula.get("kind") != "row" or formula.get("table") != table:
            continue
        try:
            out[formula["id"]] = eval_expr(
                formula["expr"],
                schema=schema,
                row=row,
                default_tz=cfg.timezone,
            )
        except Exception:
            out[formula["id"]] = None
    return out
