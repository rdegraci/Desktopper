"""Validate additive spec diffs. No SQLite writes."""

from __future__ import annotations

import copy
import re
from typing import Any

ALLOWED_DIFF_KEYS = {
    "summary",
    "app",
    "add_tables",
    "add_columns",
    "add_screens",
    "update_screens",
    "extend_enums",
    "update_labels",
    "hide_columns",
}

FORBIDDEN_KEY_HINTS = ("drop", "rename")

NAME_RE = re.compile(r"^[a-z][a-z0-9_]*$")
ALLOWED_TYPES = {"INTEGER", "REAL", "TEXT"}
ALLOWED_WIDGETS = {"text", "textarea", "select", "number", "checkbox", "fk"}
SYSTEM_COLUMNS = ("id", "created_at", "updated_at")
COLUMN_KEYS = {
    "name",
    "type",
    "label",
    "nullable",
    "widget",
    "enum",
    "fk",
    "hidden",
    "pk",
    "default",
}
TABLE_KEYS = {"name", "label", "hidden", "columns"}
APP_KEYS = {"title", "prompt", "home"}
SCREEN_KEYS = {"id", "type", "table", "title", "columns", "nav", "related", "scopes"}
UPDATE_SCREEN_KEYS = {"id", "title", "columns", "nav", "related", "scopes"}
RELATED_KEYS = {"table", "fk", "title", "columns"}
SCOPE_KEYS = {"id", "label", "column", "value"}
SCOPE_FILTER_WIDGETS = {"select", "checkbox", "text", "number", "textarea"}


class ValidationError(Exception):
    def __init__(self, error_code: str, msg: str) -> None:
        super().__init__(msg)
        self.error_code = error_code
        self.msg = msg


def _is_name(value: Any) -> bool:
    return isinstance(value, str) and bool(NAME_RE.match(value))


def _table_map(schema: dict[str, Any]) -> dict[str, Any]:
    tables = schema.get("tables") or {}
    if not isinstance(tables, dict):
        return {}
    return tables


def _column_map(table: dict[str, Any]) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    for col in table.get("columns") or []:
        if isinstance(col, dict) and isinstance(col.get("name"), str):
            out[col["name"]] = col
    return out


def _check_column_def(col: Any, *, context: str) -> dict[str, Any]:
    if not isinstance(col, dict):
        raise ValidationError("bad_name", f"{context} column must be an object.")
    extra = set(col.keys()) - COLUMN_KEYS
    if extra:
        raise ValidationError("unknown_key", f"{context} has unknown column keys.")
    name = col.get("name")
    if not _is_name(name):
        raise ValidationError("bad_name", f"{context} has a bad column name.")
    if name in SYSTEM_COLUMNS:
        raise ValidationError("bad_name", f"{context} must not declare {name}.")
    col_type = col.get("type")
    if col_type not in ALLOWED_TYPES:
        raise ValidationError("bad_name", f"{context} has a bad type.")
    widget = col.get("widget", "text")
    if widget not in ALLOWED_WIDGETS:
        raise ValidationError("bad_name", f"{context} has a bad widget.")
    if widget == "select":
        enum = col.get("enum")
        if not isinstance(enum, list) or not enum or not all(isinstance(x, str) for x in enum):
            raise ValidationError("bad_name", f"{context} select needs enum strings.")
    if widget == "fk":
        fk = col.get("fk")
        if not isinstance(fk, dict):
            raise ValidationError("bad_name", f"{context} fk widget needs fk object.")
        if not _is_name(fk.get("table")):
            raise ValidationError("bad_name", f"{context} fk table name is bad.")
        if fk.get("column") != "id":
            raise ValidationError("bad_name", f"{context} fk column must be id.")
        if not _is_name(fk.get("display")):
            raise ValidationError("bad_name", f"{context} fk display name is bad.")
        if col_type != "INTEGER":
            raise ValidationError("bad_name", f"{context} fk type must be INTEGER.")
    if widget == "checkbox" and col_type != "INTEGER":
        raise ValidationError("bad_name", f"{context} checkbox type must be INTEGER.")
    if widget == "number" and col_type not in ("INTEGER", "REAL"):
        raise ValidationError("bad_name", f"{context} number type is bad.")
    if widget == "textarea" and col_type != "TEXT":
        raise ValidationError("bad_name", f"{context} textarea type must be TEXT.")
    if "nullable" in col and not isinstance(col["nullable"], bool):
        raise ValidationError("bad_name", f"{context} nullable must be a boolean.")
    return col


def _project_schema(schema: dict[str, Any], diff: dict[str, Any]) -> dict[str, Any]:
    projected = copy.deepcopy(schema)
    tables = _table_map(projected)
    for item in diff.get("add_tables") or []:
        name = item["name"]
        cols = []
        for sys_name, sys_type, pk in (
            ("id", "INTEGER", True),
            ("created_at", "TEXT", False),
            ("updated_at", "TEXT", False),
        ):
            cols.append(
                {
                    "name": sys_name,
                    "type": sys_type,
                    "pk": pk,
                    "nullable": False if pk else True,
                    "hidden": True,
                }
            )
        for col in item.get("columns") or []:
            cols.append(copy.deepcopy(col))
        tables[name] = {
            "label": item.get("label", name),
            "hidden": bool(item.get("hidden", False)),
            "columns": cols,
        }
    projected["tables"] = tables
    for item in diff.get("add_columns") or []:
        tname = item["table"]
        tables[tname].setdefault("columns", []).append(copy.deepcopy(item["column"]))
    return projected


def validate_diff(schema: dict[str, Any], diff: Any) -> None:
    if not isinstance(diff, dict):
        raise ValidationError("invalid_json", "Spec diff must be a JSON object.")
    keys = set(diff.keys())
    for key in keys:
        lower = key.lower()
        if any(h in lower for h in FORBIDDEN_KEY_HINTS):
            raise ValidationError("forbidden_ddl", "Spec diff must not drop or rename.")
    extra = keys - ALLOWED_DIFF_KEYS
    if extra:
        raise ValidationError("unknown_key", "Spec diff has unknown keys.")

    if "app" in diff and diff["app"] is not None:
        if not isinstance(diff["app"], dict):
            raise ValidationError("bad_name", "app must be an object.")
        extra_app = set(diff["app"].keys()) - APP_KEYS
        if extra_app:
            raise ValidationError("unknown_key", "app has unknown keys.")
        home = diff["app"].get("home")
        if home is not None and not _is_name(home):
            raise ValidationError("bad_name", "app.home must be a screen id.")

    add_tables = diff.get("add_tables") or []
    add_columns = diff.get("add_columns") or []
    add_screens = diff.get("add_screens") or []
    update_screens = diff.get("update_screens") or []
    extend_enums = diff.get("extend_enums") or []
    update_labels = diff.get("update_labels") or []
    hide_columns = diff.get("hide_columns") or []
    for name, val in (
        ("add_tables", add_tables),
        ("add_columns", add_columns),
        ("add_screens", add_screens),
        ("update_screens", update_screens),
        ("extend_enums", extend_enums),
        ("update_labels", update_labels),
        ("hide_columns", hide_columns),
    ):
        if not isinstance(val, list):
            raise ValidationError("bad_name", f"{name} must be an array.")

    existing = _table_map(schema)
    new_names: set[str] = set()
    for item in add_tables:
        if not isinstance(item, dict):
            raise ValidationError("bad_name", "add_tables items must be objects.")
        extra_t = set(item.keys()) - TABLE_KEYS
        if extra_t:
            raise ValidationError("unknown_key", "add_tables item has unknown keys.")
        name = item.get("name")
        if not _is_name(name):
            raise ValidationError("bad_name", "Table name is not snake_case.")
        if name in existing or name in new_names:
            raise ValidationError("bad_name", f"Table {name} already exists.")
        new_names.add(name)
        columns = item.get("columns") or []
        if not isinstance(columns, list):
            raise ValidationError("bad_name", f"Table {name} columns must be an array.")
        seen_cols: set[str] = set()
        for col in columns:
            cdef = _check_column_def(col, context=f"table {name}")
            if cdef["name"] in seen_cols:
                raise ValidationError("bad_name", f"Duplicate column on {name}.")
            seen_cols.add(cdef["name"])

    for item in add_columns:
        if not isinstance(item, dict):
            raise ValidationError("bad_name", "add_columns items must be objects.")
        extra_c = set(item.keys()) - {"table", "column"}
        if extra_c:
            raise ValidationError("unknown_key", "add_columns item has unknown keys.")
        tname = item.get("table")
        if not _is_name(tname):
            raise ValidationError("bad_name", "add_columns table name is bad.")
        in_schema = tname in existing
        in_diff = tname in new_names
        if not in_schema and not in_diff:
            raise ValidationError("bad_name", f"Table {tname} is missing.")
        cdef = _check_column_def(item.get("column"), context=f"add_columns {tname}")
        if in_schema:
            cmap = _column_map(existing[tname])
            if cdef["name"] in cmap:
                raise ValidationError("bad_name", f"Column {cdef['name']} already exists.")
        if in_diff:
            for tbl in add_tables:
                if tbl.get("name") == tname:
                    names = [
                        c.get("name")
                        for c in (tbl.get("columns") or [])
                        if isinstance(c, dict)
                    ]
                    if cdef["name"] in names:
                        raise ValidationError("bad_name", f"Column {cdef['name']} already exists.")

    try:
        projected = _project_schema(schema, diff)
    except (KeyError, TypeError) as exc:
        raise ValidationError("bad_name", "Could not project schema.") from exc

    ptables = _table_map(projected)
    for item in add_columns:
        col = item["column"]
        if col.get("widget") != "fk":
            continue
        _check_fk(ptables, col["fk"], context="add_columns")
    for item in add_tables:
        for col in item.get("columns") or []:
            if isinstance(col, dict) and col.get("widget") == "fk":
                _check_fk(ptables, col["fk"], context=f"table {item.get('name')}")

    existing_screen_ids = {
        s.get("id")
        for s in (schema.get("screens") or [])
        if isinstance(s, dict)
    }
    new_screen_ids: set[str] = set()
    for item in add_screens:
        if not isinstance(item, dict):
            raise ValidationError("bad_name", "add_screens items must be objects.")
        extra_s = set(item.keys()) - SCREEN_KEYS
        if extra_s:
            raise ValidationError("unknown_key", "add_screens item has unknown keys.")
        sid = item.get("id")
        if not _is_name(sid):
            raise ValidationError("bad_name", "Screen id is not snake_case.")
        if sid in existing_screen_ids or sid in new_screen_ids:
            raise ValidationError("bad_name", f"Screen id {sid} is not unique.")
        new_screen_ids.add(sid)
        stype = item.get("type")
        if stype not in ("list", "form"):
            raise ValidationError("bad_name", "Screen type must be list or form.")
        tname = item.get("table")
        if tname not in ptables:
            raise ValidationError("bad_name", f"Screen table {tname} is missing.")
        if "nav" in item and not isinstance(item.get("nav"), bool):
            raise ValidationError("bad_name", "Screen nav must be a boolean.")
        if "related" in item:
            if stype != "form":
                raise ValidationError("bad_name", "related is only allowed on form screens.")
            _check_related(ptables, tname, item.get("related"))
        if "scopes" in item:
            if stype != "list":
                raise ValidationError("bad_name", "scopes is only allowed on list screens.")
            _check_scopes(ptables, tname, item.get("scopes"))

    screen_by_id: dict[str, dict[str, Any]] = {}
    for screen in schema.get("screens") or []:
        if isinstance(screen, dict) and _is_name(screen.get("id")):
            screen_by_id[screen["id"]] = copy.deepcopy(screen)
    for item in add_screens:
        screen_by_id[item["id"]] = copy.deepcopy(item)

    for item in update_screens:
        if not isinstance(item, dict):
            raise ValidationError("bad_name", "update_screens items must be objects.")
        extra_u = set(item.keys()) - UPDATE_SCREEN_KEYS
        if extra_u:
            raise ValidationError("unknown_key", "update_screens item has unknown keys.")
        sid = item.get("id")
        if not _is_name(sid) or sid not in screen_by_id:
            raise ValidationError("bad_name", "update_screens id is missing.")
        current = screen_by_id[sid]
        if "nav" in item and not isinstance(item.get("nav"), bool):
            raise ValidationError("bad_name", "Screen nav must be a boolean.")
        if "related" in item:
            if current.get("type") != "form":
                raise ValidationError("bad_name", "related is only allowed on form screens.")
            _check_related(ptables, current.get("table"), item.get("related"))
        if "scopes" in item:
            if current.get("type") != "list":
                raise ValidationError("bad_name", "scopes is only allowed on list screens.")
            _check_scopes(ptables, current.get("table"), item.get("scopes"))
        if "title" in item and not isinstance(item.get("title"), str):
            raise ValidationError("bad_name", "Screen title must be a string.")
        if "columns" in item:
            if not isinstance(item.get("columns"), list):
                raise ValidationError("bad_name", "Screen columns must be an array.")

    home = None
    if isinstance(diff.get("app"), dict):
        home = diff["app"].get("home")
    if home:
        found = screen_by_id.get(home)
        if not found or found.get("type") != "list":
            raise ValidationError("bad_name", "app.home must be a list screen id.")

    for item in extend_enums:
        if not isinstance(item, dict):
            raise ValidationError("bad_name", "extend_enums items must be objects.")
        extra_e = set(item.keys()) - {"table", "column", "add_values"}
        if extra_e:
            raise ValidationError("unknown_key", "extend_enums has unknown keys.")
        tname = item.get("table")
        cname = item.get("column")
        values = item.get("add_values")
        if not _is_name(tname) or not _is_name(cname):
            raise ValidationError("bad_name", "extend_enums names are bad.")
        if not isinstance(values, list) or not values:
            raise ValidationError("bad_name", "extend_enums add_values is empty.")
        if not all(isinstance(v, str) and v for v in values):
            raise ValidationError("bad_name", "extend_enums values must be strings.")
        table = ptables.get(tname)
        if not table:
            raise ValidationError("bad_name", f"Table {tname} is missing.")
        col = _column_map(table).get(cname)
        if not col:
            raise ValidationError("bad_name", f"Column {cname} is missing.")
        if not isinstance(col.get("enum"), list):
            raise ValidationError("bad_name", f"Column {cname} has no enum.")

    for item in update_labels:
        if not isinstance(item, dict):
            raise ValidationError("bad_name", "update_labels items must be objects.")
        extra_u = set(item.keys()) - {"table", "column", "label"}
        if extra_u:
            raise ValidationError("unknown_key", "update_labels has unknown keys.")
        tname = item.get("table")
        if not _is_name(tname) or tname not in ptables:
            raise ValidationError("bad_name", "update_labels table is missing.")
        if "column" in item:
            cname = item.get("column")
            if not _is_name(cname) or cname not in _column_map(ptables[tname]):
                raise ValidationError("bad_name", "update_labels column is missing.")
        if "label" in item and not isinstance(item.get("label"), str):
            raise ValidationError("bad_name", "update_labels label must be a string.")

    for item in hide_columns:
        if not isinstance(item, dict):
            raise ValidationError("bad_name", "hide_columns items must be objects.")
        extra_h = set(item.keys()) - {"table", "column"}
        if extra_h:
            raise ValidationError("unknown_key", "hide_columns has unknown keys.")
        tname = item.get("table")
        cname = item.get("column")
        if not _is_name(tname) or tname not in ptables:
            raise ValidationError("bad_name", "hide_columns table is missing.")
        if cname == "id":
            raise ValidationError("bad_name", "Cannot hide id.")
        if not _is_name(cname) or cname not in _column_map(ptables[tname]):
            raise ValidationError("bad_name", "hide_columns column is missing.")


def _check_scopes(tables: dict[str, Any], list_table: Any, scopes: Any) -> None:
    if not isinstance(scopes, list):
        raise ValidationError("bad_name", "scopes must be an array.")
    if not _is_name(list_table) or list_table not in tables:
        raise ValidationError("bad_name", "scopes list table is missing.")
    cmap = _column_map(tables[list_table])
    seen: set[str] = set()
    for item in scopes:
        if not isinstance(item, dict):
            raise ValidationError("bad_name", "scopes items must be objects.")
        extra = set(item.keys()) - SCOPE_KEYS
        if extra:
            raise ValidationError("unknown_key", "scopes item has unknown keys.")
        sid = item.get("id")
        if not _is_name(sid):
            raise ValidationError("bad_name", "Scope id is not snake_case.")
        if sid in seen:
            raise ValidationError("bad_name", f"Scope id {sid} is not unique.")
        seen.add(sid)
        label = item.get("label")
        if not isinstance(label, str) or not label.strip():
            raise ValidationError("bad_name", "Scope label is required.")
        if "column" not in item:
            if "value" in item:
                raise ValidationError("bad_name", "Scope value needs a column.")
            continue
        cname = item.get("column")
        if not _is_name(cname) or cname not in cmap:
            raise ValidationError("bad_name", "Scope column is missing.")
        col = cmap[cname]
        widget = col.get("widget") or "text"
        if widget not in SCOPE_FILTER_WIDGETS:
            raise ValidationError("bad_name", "Scope column widget is not filterable.")
        if "value" not in item:
            raise ValidationError("bad_name", "Scope filter needs a value.")
        value = item.get("value")
        if widget == "checkbox":
            if value not in (0, 1, True, False):
                raise ValidationError("bad_name", "Scope checkbox value must be 0 or 1.")
        elif widget == "number":
            if not isinstance(value, (int, float)) or isinstance(value, bool):
                raise ValidationError("bad_name", "Scope number value must be a number.")
        elif widget == "select":
            enum = col.get("enum") or []
            if not isinstance(value, str) or value not in enum:
                raise ValidationError("bad_name", "Scope select value must be an enum string.")
        else:
            if not isinstance(value, str):
                raise ValidationError("bad_name", "Scope text value must be a string.")


def _check_related(tables: dict[str, Any], form_table: Any, related: Any) -> None:
    if not isinstance(related, list):
        raise ValidationError("bad_name", "related must be an array.")
    if not _is_name(form_table) or form_table not in tables:
        raise ValidationError("bad_name", "related form table is missing.")
    for item in related:
        if not isinstance(item, dict):
            raise ValidationError("bad_name", "related items must be objects.")
        extra = set(item.keys()) - RELATED_KEYS
        if extra:
            raise ValidationError("unknown_key", "related item has unknown keys.")
        tname = item.get("table")
        fk_name = item.get("fk")
        if not _is_name(tname) or tname not in tables:
            raise ValidationError("bad_name", "related table is missing.")
        if not _is_name(fk_name):
            raise ValidationError("bad_name", "related fk name is bad.")
        col = _column_map(tables[tname]).get(fk_name)
        if not col or col.get("widget") != "fk":
            raise ValidationError("bad_name", "related fk must be an fk column.")
        target = (col.get("fk") or {}).get("table")
        if target != form_table:
            raise ValidationError("bad_name", "related fk must point at the form table.")
        if "title" in item and not isinstance(item.get("title"), str):
            raise ValidationError("bad_name", "related title must be a string.")
        cols = item.get("columns")
        if cols is None:
            continue
        if not isinstance(cols, list) or not all(isinstance(c, str) for c in cols):
            raise ValidationError("bad_name", "related columns must be names.")
        cmap = _column_map(tables[tname])
        for cname in cols:
            if cname not in cmap:
                raise ValidationError("bad_name", f"related column {cname} is missing.")


def _check_fk(tables: dict[str, Any], fk: dict[str, Any], *, context: str) -> None:
    target = fk.get("table")
    display = fk.get("display")
    if target not in tables:
        raise ValidationError("fk_missing", f"{context} fk target {target} is missing.")
    col = _column_map(tables[target]).get(display)
    if not col:
        raise ValidationError("fk_missing", f"{context} fk display {display} is missing.")
    if col.get("type") != "TEXT":
        raise ValidationError("fk_missing", f"{context} fk display must be TEXT.")
