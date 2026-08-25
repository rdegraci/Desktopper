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
    "update_columns",
    "add_screens",
    "update_screens",
    "update_tables",
    "extend_enums",
    "update_labels",
    "hide_columns",
    "remove_columns",
    "add_hooks",
    "update_hooks",
    "disable_hooks",
    "remove_hooks",
    "add_formulas",
    "add_rules",
    "disable_rules",
    "add_roles",
    "add_grants",
    "add_import_profiles",
    "add_layouts",
    "add_reminders",
    "update_reminders",
    "disable_reminders",
    "add_jobs",
    "disable_jobs",
    "update_sync",
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
UPDATE_COLUMN_KEYS = {"table", "column", "widget", "label", "nullable", "enum"}
UPDATE_COLUMN_PATCH_KEYS = {"widget", "label", "nullable", "enum"}
TABLE_KEYS = {"name", "label", "hidden", "columns", "role"}
UPDATE_TABLE_KEYS = {"name", "role"}
TABLE_ROLES = {"primary", "lookup"}
APP_KEYS = {"title", "prompt", "home"}
SCREEN_KEYS = {
    "id",
    "type",
    "table",
    "title",
    "columns",
    "nav",
    "related",
    "scopes",
    "groups",
    "empty",
    "layout_id",
}
UPDATE_SCREEN_KEYS = {
    "id",
    "title",
    "columns",
    "nav",
    "related",
    "scopes",
    "groups",
    "empty",
    "layout_id",
}
RELATED_KEYS = {"table", "fk", "title", "columns", "empty"}
SCOPE_KEYS = {"id", "label", "column", "value"}
GROUP_KEYS = {"id", "label", "columns"}
SCOPE_FILTER_WIDGETS = {"select", "checkbox", "text", "number", "textarea"}
CRUD_HOOK_EVENTS = frozenset({"create", "update", "delete"})
STARTUP_HOOK_EVENT = "startup"
HOOK_EVENTS = CRUD_HOOK_EVENTS | {STARTUP_HOOK_EVENT}
ADD_HOOK_KEYS = {"id", "table", "on", "code"}
UPDATE_HOOK_KEYS = {"id", "code", "enabled"}


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


def table_role(table: Any) -> str:
    if isinstance(table, dict) and table.get("role") == "lookup":
        return "lookup"
    return "primary"


def _check_table_role(role: Any, *, context: str) -> None:
    if role is None:
        return
    if role not in TABLE_ROLES:
        raise ValidationError(
            "bad_name", f"{context} role must be primary or lookup."
        )


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
        raise ValidationError(
            "bad_name",
            f"{context} column {name!r} has bad type {col_type!r} "
            f"(use INTEGER, REAL, or TEXT).",
        )
    widget = col.get("widget", "text")
    _validate_widget_fits_type(col_type, widget, col, context=context)
    if "nullable" in col and not isinstance(col["nullable"], bool):
        raise ValidationError("bad_name", f"{context} nullable must be a boolean.")
    return col


def _collect_expr_column_refs(
    node: Any, refs: set[tuple[str | None, str]], *, default_table: str | None = None
) -> None:
    if not isinstance(node, dict):
        return
    op = node.get("op")
    if op == "col":
        table = node.get("table") or default_table
        column = node.get("column")
        if isinstance(column, str):
            refs.add((table, column))
    if op in ("sum", "count", "avg", "min", "max"):
        table = node.get("table") or default_table
        column = node.get("column")
        if isinstance(column, str):
            refs.add((table, column))
    for key, val in node.items():
        if key == "op":
            continue
        if isinstance(val, dict):
            _collect_expr_column_refs(val, refs, default_table=default_table)
        elif isinstance(val, list):
            for item in val:
                _collect_expr_column_refs(item, refs, default_table=default_table)


def _column_blocked_by_refs(
    schema: dict[str, Any], diff: dict[str, Any], tname: str, cname: str
) -> str | None:
    ptables = _table_map(schema)
    for tbl, table in ptables.items():
        for col in table.get("columns") or []:
            if col.get("widget") != "fk":
                continue
            fk = col.get("fk") or {}
            if fk.get("table") == tname and fk.get("display") == cname:
                return f"foreign key on {tbl}.{col.get('name')} displays {tname}.{cname}"

    formulas = list(schema.get("formulas") or [])
    for item in diff.get("add_formulas") or []:
        if isinstance(item, dict):
            formulas.append(item)
    for formula in formulas:
        if not isinstance(formula, dict):
            continue
        refs: set[tuple[str | None, str]] = set()
        _collect_expr_column_refs(formula.get("expr"), refs)
        for ref_table, ref_col in refs:
            if ref_col == cname and (ref_table is None or ref_table == tname):
                return f"formula {formula.get('id')} uses {tname}.{cname}"

    rules = list(schema.get("rules") or [])
    for item in diff.get("add_rules") or []:
        if isinstance(item, dict):
            rules.append(item)
    for rule in rules:
        if not isinstance(rule, dict):
            continue
        rule_table = rule.get("table")
        refs = set()
        _collect_expr_column_refs(rule.get("when"), refs, default_table=rule_table)
        for ref_table, ref_col in refs:
            if ref_col == cname and (ref_table is None or ref_table == tname):
                if rule_table == tname or ref_table == tname:
                    return f"rule {rule.get('id')} uses {tname}.{cname}"
        for action in rule.get("then") or []:
            if not isinstance(action, dict):
                continue
            if action.get("kind") == "set_column" and action.get("column") == cname:
                if rule_table == tname:
                    return f"rule {rule.get('id')} sets {tname}.{cname}"
            fields = action.get("fields") or {}
            if action.get("kind") == "create_row" and action.get("table") == tname:
                if cname in fields:
                    return f"rule {rule.get('id')} writes {tname}.{cname}"

    profiles = list(schema.get("import_profiles") or [])
    for item in diff.get("add_import_profiles") or []:
        if isinstance(item, dict):
            profiles.append(item)
    for profile in profiles:
        if not isinstance(profile, dict) or profile.get("table") != tname:
            continue
        mapping = profile.get("map") or {}
        if cname in mapping.values():
            return f"import profile {profile.get('id')} maps to {tname}.{cname}"
    return None


def _validate_widget_fits_type(
    col_type: str, widget: str, col: dict[str, Any], *, context: str
) -> None:
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
        raise ValidationError(
            "bad_name",
            f"{context}: checkbox requires an INTEGER column; "
            f"use add_columns plus hide_columns instead.",
        )
    if widget == "number" and col_type not in ("INTEGER", "REAL"):
        raise ValidationError("bad_name", f"{context} number type is bad.")
    if widget == "textarea" and col_type != "TEXT":
        raise ValidationError("bad_name", f"{context} textarea type must be TEXT.")


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
        entry: dict[str, Any] = {
            "label": item.get("label", name),
            "hidden": bool(item.get("hidden", False)),
            "columns": cols,
        }
        if item.get("role") in TABLE_ROLES:
            entry["role"] = item["role"]
        tables[name] = entry
    projected["tables"] = tables
    for item in diff.get("add_columns") or []:
        tname = item["table"]
        tables[tname].setdefault("columns", []).append(copy.deepcopy(item["column"]))
    for item in diff.get("update_tables") or []:
        if not isinstance(item, dict):
            continue
        tname = item.get("name")
        if tname not in tables:
            continue
        if "role" in item:
            tables[tname]["role"] = item["role"]
    return projected


def validate_diff(
    schema: dict[str, Any],
    diff: Any,
    *,
    hooks_registry: dict[str, Any] | None = None,
) -> None:
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
    update_columns = diff.get("update_columns") or []
    add_screens = diff.get("add_screens") or []
    update_screens = diff.get("update_screens") or []
    update_tables = diff.get("update_tables") or []
    extend_enums = diff.get("extend_enums") or []
    update_labels = diff.get("update_labels") or []
    hide_columns = diff.get("hide_columns") or []
    remove_columns = diff.get("remove_columns") or []
    add_hooks = diff.get("add_hooks") or []
    update_hooks = diff.get("update_hooks") or []
    disable_hooks = diff.get("disable_hooks") or []
    remove_hooks = diff.get("remove_hooks") or []
    for name, val in (
        ("add_tables", add_tables),
        ("add_columns", add_columns),
        ("update_columns", update_columns),
        ("add_screens", add_screens),
        ("update_screens", update_screens),
        ("update_tables", update_tables),
        ("extend_enums", extend_enums),
        ("update_labels", update_labels),
        ("hide_columns", hide_columns),
        ("remove_columns", remove_columns),
        ("add_hooks", add_hooks),
        ("update_hooks", update_hooks),
        ("disable_hooks", disable_hooks),
        ("remove_hooks", remove_hooks),
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
        if "role" in item:
            _check_table_role(item.get("role"), context=f"table {name}")
        columns = item.get("columns") or []
        if not isinstance(columns, list):
            raise ValidationError("bad_name", f"Table {name} columns must be an array.")
        seen_cols: set[str] = set()
        for col in columns:
            cdef = _check_column_def(col, context=f"table {name}")
            if cdef["name"] in seen_cols:
                raise ValidationError("bad_name", f"Duplicate column on {name}.")
            seen_cols.add(cdef["name"])

    for item in update_tables:
        if not isinstance(item, dict):
            raise ValidationError("bad_name", "update_tables items must be objects.")
        extra_ut = set(item.keys()) - UPDATE_TABLE_KEYS
        if extra_ut:
            raise ValidationError("unknown_key", "update_tables item has unknown keys.")
        tname = item.get("name")
        if not _is_name(tname) or tname not in existing:
            raise ValidationError("bad_name", "update_tables name is missing.")
        if tname in new_names:
            raise ValidationError("bad_name", "update_tables cannot target a new table.")
        if "role" not in item:
            raise ValidationError("bad_name", "update_tables must set role.")
        _check_table_role(item.get("role"), context=f"update_tables {tname}")

    for item in add_columns:
        if not isinstance(item, dict):
            raise ValidationError("bad_name", "add_columns items must be objects.")
        extra_c = set(item.keys()) - {"table", "column"}
        if extra_c:
            raise ValidationError(
                "unknown_key",
                f"add_columns item has unknown keys: {sorted(extra_c)} "
                f"(use table and column only).",
            )
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
    layout_ids: set[str] = set()
    for layout in schema.get("layouts") or []:
        if isinstance(layout, dict) and _is_name(layout.get("id")):
            layout_ids.add(layout["id"])
    for layout in diff.get("add_layouts") or []:
        if isinstance(layout, dict) and _is_name(layout.get("id")):
            layout_ids.add(layout["id"])

    new_screen_ids: set[str] = set()
    for item in add_screens:
        if not isinstance(item, dict):
            raise ValidationError("bad_name", "add_screens items must be objects.")
        extra_s = set(item.keys()) - SCREEN_KEYS
        sid = item.get("id")
        if extra_s:
            label = sid if _is_name(sid) else "?"
            raise ValidationError(
                "unknown_key",
                f"add_screens item {label} has unknown keys: {sorted(extra_s)}.",
            )
        if not _is_name(sid):
            raise ValidationError("bad_name", "Screen id is not snake_case.")
        if sid in existing_screen_ids or sid in new_screen_ids:
            raise ValidationError("bad_name", f"Screen id {sid} is not unique.")
        new_screen_ids.add(sid)
        stype = item.get("type")
        if stype not in ("list", "form", "layout"):
            raise ValidationError(
                "bad_name", "Screen type must be list, form, or layout."
            )
        if stype == "layout":
            lid = item.get("layout_id")
            if not _is_name(lid):
                raise ValidationError("bad_name", "Layout screen needs layout_id.")
            if lid not in layout_ids:
                raise ValidationError(
                    "bad_name",
                    f"layout_id {lid} is missing; add it in add_layouts.",
                )
            if item.get("table") is not None:
                raise ValidationError("bad_name", "Layout screens must not set table.")
            for key in ("columns", "related", "scopes", "groups", "empty"):
                if key in item:
                    raise ValidationError(
                        "bad_name", f"{key} is not allowed on layout screens."
                    )
            if "nav" in item and not isinstance(item.get("nav"), bool):
                raise ValidationError("bad_name", "Screen nav must be a boolean.")
            if "title" in item and not isinstance(item.get("title"), str):
                raise ValidationError("bad_name", "Screen title must be a string.")
            continue
        if "layout_id" in item:
            raise ValidationError(
                "bad_name", "layout_id is only allowed on layout screens."
            )
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
        if "groups" in item:
            if stype != "form":
                raise ValidationError("bad_name", "groups is only allowed on form screens.")
            _check_groups(ptables, tname, item.get("groups"))
        if "empty" in item:
            if stype != "list":
                raise ValidationError("bad_name", "empty is only allowed on list screens.")
            if not isinstance(item.get("empty"), str):
                raise ValidationError("bad_name", "Screen empty must be a string.")

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
        if "groups" in item:
            if current.get("type") != "form":
                raise ValidationError("bad_name", "groups is only allowed on form screens.")
            _check_groups(ptables, current.get("table"), item.get("groups"))
        if "empty" in item:
            if current.get("type") != "list":
                raise ValidationError("bad_name", "empty is only allowed on list screens.")
            if not isinstance(item.get("empty"), str):
                raise ValidationError("bad_name", "Screen empty must be a string.")
        if "title" in item and not isinstance(item.get("title"), str):
            raise ValidationError("bad_name", "Screen title must be a string.")
        if "columns" in item:
            if not isinstance(item.get("columns"), list):
                raise ValidationError("bad_name", "Screen columns must be an array.")

    home = None
    if isinstance(diff.get("app"), dict):
        home = diff["app"].get("home")
    if not home:
        home = (schema.get("app") or {}).get("home")
    if home:
        found = screen_by_id.get(home)
        if not found:
            raise ValidationError("bad_name", "app.home must be an existing screen id.")
        home_type = found.get("type")
        if home_type == "layout":
            lid = found.get("layout_id")
            if not _is_name(lid) or lid not in layout_ids:
                raise ValidationError(
                    "bad_name", "app.home layout screen needs a valid layout_id."
                )
        elif home_type == "list":
            home_table = ptables.get(found.get("table"))
            if table_role(home_table) == "lookup":
                raise ValidationError(
                    "bad_name", "app.home must be a primary list screen."
                )
        else:
            raise ValidationError(
                "bad_name", "app.home must be a list or layout screen id."
            )

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

    removed: set[tuple[str, str]] = set()
    for item in remove_columns:
        if not isinstance(item, dict):
            raise ValidationError("bad_name", "remove_columns items must be objects.")
        extra_r = set(item.keys()) - {"table", "column"}
        if extra_r:
            raise ValidationError(
                "unknown_key",
                f"remove_columns item has unknown keys: {sorted(extra_r)}.",
            )
        tname = item.get("table")
        cname = item.get("column")
        if not _is_name(tname) or tname not in ptables:
            raise ValidationError("bad_name", "remove_columns table is missing.")
        if not _is_name(cname):
            raise ValidationError("bad_name", "remove_columns column name is bad.")
        if cname in SYSTEM_COLUMNS:
            raise ValidationError("bad_name", f"Cannot remove system column {cname}.")
        if cname not in _column_map(ptables[tname]):
            raise ValidationError("bad_name", f"remove_columns column {cname} is missing.")
        key = (tname, cname)
        if key in removed:
            raise ValidationError("bad_name", f"remove_columns duplicate {tname}.{cname}.")
        removed.add(key)
        for other in add_columns:
            if (
                isinstance(other, dict)
                and other.get("table") == tname
                and isinstance(other.get("column"), dict)
                and other["column"].get("name") == cname
            ):
                raise ValidationError(
                    "bad_name",
                    f"Cannot add and remove {tname}.{cname} in the same diff.",
                )
        reason = _column_blocked_by_refs(schema, diff, tname, cname)
        if reason:
            raise ValidationError("bad_name", f"Cannot remove {tname}.{cname}: {reason}.")

    for item in update_columns:
        if not isinstance(item, dict):
            raise ValidationError("bad_name", "update_columns items must be objects.")
        extra_uc = set(item.keys()) - UPDATE_COLUMN_KEYS
        if extra_uc:
            raise ValidationError(
                "unknown_key",
                f"update_columns item has unknown keys: {sorted(extra_uc)}.",
            )
        tname = item.get("table")
        cname = item.get("column")
        if not _is_name(tname) or tname not in ptables:
            raise ValidationError("bad_name", "update_columns table is missing.")
        if not _is_name(cname):
            raise ValidationError("bad_name", "update_columns column name is bad.")
        if cname in SYSTEM_COLUMNS:
            raise ValidationError("bad_name", f"Cannot update system column {cname}.")
        col = _column_map(ptables[tname]).get(cname)
        if not col:
            raise ValidationError("bad_name", f"update_columns column {cname} is missing.")
        patches = set(item.keys()) & UPDATE_COLUMN_PATCH_KEYS
        if not patches:
            raise ValidationError(
                "bad_name",
                "update_columns must set widget, label, nullable, or enum.",
            )
        if "label" in item and not isinstance(item.get("label"), str):
            raise ValidationError("bad_name", "update_columns label must be a string.")
        if "nullable" in item and not isinstance(item.get("nullable"), bool):
            raise ValidationError("bad_name", "update_columns nullable must be a boolean.")
        if "widget" in item and item.get("widget") == "fk":
            raise ValidationError(
                "bad_name", "update_columns cannot set widget to fk; use add_columns."
            )
        if "enum" in item:
            enum = item.get("enum")
            if not isinstance(enum, list) or not enum or not all(isinstance(x, str) for x in enum):
                raise ValidationError("bad_name", "update_columns enum must be strings.")
        patched = copy.deepcopy(col)
        if "widget" in item:
            patched["widget"] = item["widget"]
        if "label" in item:
            patched["label"] = item["label"]
        if "nullable" in item:
            patched["nullable"] = item["nullable"]
        if "enum" in item:
            patched["enum"] = copy.deepcopy(item["enum"])
        col_type = patched.get("type")
        if col_type not in ALLOWED_TYPES:
            raise ValidationError("bad_name", f"update_columns {cname} has a bad type.")
        widget = patched.get("widget", "text")
        _validate_widget_fits_type(
            col_type,
            widget,
            patched,
            context=f"update_columns {tname}.{cname}",
        )

    _validate_hooks_diff(
        ptables,
        add_hooks,
        update_hooks,
        disable_hooks,
        remove_hooks,
        hooks_registry or {"hooks": []},
    )

    from app.final_schema import validate_final_diff

    validate_final_diff(_project_schema(schema, diff), diff)


def _check_hook_code(code: Any, *, filename: str) -> None:
    if not isinstance(code, str) or not code.strip():
        raise ValidationError("bad_hook", "Hook code must be a non-empty string.")
    try:
        compile(code, filename, "exec")
    except SyntaxError as exc:
        raise ValidationError("bad_hook", f"Hook code has a syntax error: {exc}") from exc


def _hook_ids(registry: dict[str, Any]) -> set[str]:
    out: set[str] = set()
    for item in registry.get("hooks") or []:
        if isinstance(item, dict) and _is_name(item.get("id")):
            out.add(item["id"])
    return out


def _validate_hooks_diff(
    ptables: dict[str, Any],
    add_hooks: list[Any],
    update_hooks: list[Any],
    disable_hooks: list[Any],
    remove_hooks: list[Any],
    hooks_registry: dict[str, Any],
) -> None:
    existing_ids = _hook_ids(hooks_registry)
    new_ids: set[str] = set()

    for item in add_hooks:
        if not isinstance(item, dict):
            raise ValidationError("bad_hook", "add_hooks items must be objects.")
        extra = set(item.keys()) - ADD_HOOK_KEYS
        if extra:
            raise ValidationError("unknown_key", "add_hooks item has unknown keys.")
        hid = item.get("id")
        tname = item.get("table")
        event = item.get("on")
        if not _is_name(hid):
            raise ValidationError("bad_hook", "Hook id is not snake_case.")
        if hid in existing_ids or hid in new_ids:
            raise ValidationError("bad_hook", f"Hook id {hid} is not unique.")
        new_ids.add(hid)
        if event not in HOOK_EVENTS:
            raise ValidationError(
                "bad_hook", "Hook on must be create, update, delete, or startup."
            )
        if event == STARTUP_HOOK_EVENT:
            if tname and (not _is_name(tname) or tname not in ptables):
                raise ValidationError("bad_hook", f"Hook table {tname} is missing.")
        elif not _is_name(tname) or tname not in ptables:
            raise ValidationError("bad_hook", f"Hook table {tname} is missing.")
        _check_hook_code(item.get("code"), filename=f"{hid}.py")

    for item in update_hooks:
        if not isinstance(item, dict):
            raise ValidationError("bad_hook", "update_hooks items must be objects.")
        extra = set(item.keys()) - UPDATE_HOOK_KEYS
        if extra:
            raise ValidationError("unknown_key", "update_hooks item has unknown keys.")
        hid = item.get("id")
        if not _is_name(hid) or hid not in existing_ids:
            raise ValidationError("bad_hook", f"Hook {hid} does not exist.")
        if "code" not in item:
            raise ValidationError("bad_hook", "update_hooks must include code.")
        _check_hook_code(item.get("code"), filename=f"{hid}.py")
        if "enabled" in item and not isinstance(item.get("enabled"), bool):
            raise ValidationError("bad_hook", "Hook enabled must be a boolean.")

    for hid in disable_hooks:
        if not _is_name(hid) or hid not in existing_ids:
            raise ValidationError("bad_hook", f"Hook {hid} does not exist.")

    for hid in remove_hooks:
        if not _is_name(hid) or hid not in existing_ids:
            raise ValidationError("bad_hook", f"Hook {hid} does not exist.")


def _check_groups(tables: dict[str, Any], form_table: Any, groups: Any) -> None:
    if not isinstance(groups, list):
        raise ValidationError("bad_name", "groups must be an array.")
    if not _is_name(form_table) or form_table not in tables:
        raise ValidationError("bad_name", "groups form table is missing.")
    cmap = _column_map(tables[form_table])
    seen_ids: set[str] = set()
    seen_cols: set[str] = set()
    for item in groups:
        if not isinstance(item, dict):
            raise ValidationError("bad_name", "groups items must be objects.")
        extra = set(item.keys()) - GROUP_KEYS
        if extra:
            raise ValidationError("unknown_key", "groups item has unknown keys.")
        gid = item.get("id")
        if not _is_name(gid):
            raise ValidationError("bad_name", "Group id is not snake_case.")
        if gid in seen_ids:
            raise ValidationError("bad_name", f"Group id {gid} is not unique.")
        seen_ids.add(gid)
        label = item.get("label")
        if not isinstance(label, str) or not label.strip():
            raise ValidationError("bad_name", "Group label is required.")
        columns = item.get("columns")
        if not isinstance(columns, list) or not columns:
            raise ValidationError("bad_name", "Group columns must be a non-empty array.")
        if not all(isinstance(c, str) for c in columns):
            raise ValidationError("bad_name", "Group columns must be names.")
        for cname in columns:
            if cname in SYSTEM_COLUMNS:
                raise ValidationError("bad_name", f"Group must not include {cname}.")
            if cname not in cmap:
                raise ValidationError("bad_name", f"Group column {cname} is missing.")
            if cname in seen_cols:
                raise ValidationError("bad_name", f"Column {cname} is in two groups.")
            seen_cols.add(cname)


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
        if "empty" in item and not isinstance(item.get("empty"), str):
            raise ValidationError("bad_name", "related empty must be a string.")
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
