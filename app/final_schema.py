"""FINAL spec objects: validation and schema merge."""

from __future__ import annotations

import copy
import json
from typing import Any

from app.formulas import validate_formula
from app.import_csv import validate_profile
from app.rules import validate_rule
from app.schema_validate import NAME_RE, ValidationError, _is_name

LAYOUT_WIDGETS = frozenset(
    {"metric", "table", "form", "kanban", "calendar", "text", "notices", "reminders"}
)
GRANT_ACTIONS = frozenset({"read", "create", "update", "delete"})
FINAL_DIFF_KEYS = frozenset(
    {
        "add_formulas",
        "add_rules",
        "disable_rules",
        "remove_rules",
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
)


def _reject_cron(obj: Any) -> None:
    if isinstance(obj, dict):
        if "cron" in obj:
            raise ValidationError("cron_forbidden", "cron strings are not allowed.")
        for val in obj.values():
            _reject_cron(val)
    elif isinstance(obj, list):
        for item in obj:
            _reject_cron(item)


def validate_final_diff(schema: dict[str, Any], diff: dict[str, Any]) -> None:
    _reject_cron(diff)
    for item in diff.get("add_formulas") or []:
        validate_formula(item, schema)
    for item in diff.get("add_rules") or []:
        validate_rule(item, schema)
    for rid in diff.get("disable_rules") or []:
        if not _is_name(rid):
            raise ValidationError("bad_rule", "disable_rules ids must be snake_case.")
    existing_rule_ids = {
        item.get("id")
        for item in (schema.get("rules") or [])
        if isinstance(item, dict) and isinstance(item.get("id"), str)
    }
    for rid in diff.get("remove_rules") or []:
        if not _is_name(rid):
            raise ValidationError("bad_rule", "remove_rules ids must be snake_case.")
        if rid not in existing_rule_ids:
            raise ValidationError("bad_rule", f"Rule {rid} does not exist.")
    for item in diff.get("add_reminders") or []:
        from app.reminders import validate_reminder_object

        validate_reminder_object(item)
    for item in diff.get("update_reminders") or []:
        from app.reminders import validate_reminder_object

        validate_reminder_object(item, is_update=True)
    for rid in diff.get("disable_reminders") or []:
        if not _is_name(rid):
            raise ValidationError("bad_reminder", "disable_reminders ids must be snake_case.")
    for item in diff.get("add_jobs") or []:
        from app.jobs import validate_job

        validate_job(item)
    for jid in diff.get("disable_jobs") or []:
        if not _is_name(jid):
            raise ValidationError("bad_job", "disable_jobs ids must be snake_case.")
    for item in diff.get("add_roles") or []:
        if not isinstance(item, dict) or not _is_name(item.get("name")):
            raise ValidationError("bad_role", "Role requires snake_case name.")
    for item in diff.get("add_grants") or []:
        if not isinstance(item, dict):
            raise ValidationError("bad_grant", "Grant must be an object.")
        if not _is_name(item.get("id")):
            raise ValidationError("bad_grant", "Grant id must be snake_case.")
        if item.get("action") not in GRANT_ACTIONS:
            raise ValidationError("bad_grant", "Grant action is invalid.")
        if not _is_name(item.get("table")) or item.get("table") not in (schema.get("tables") or {}):
            raise ValidationError("bad_grant", "Grant table is missing.")
    for item in diff.get("add_import_profiles") or []:
        validate_profile(item, schema)
    for item in diff.get("add_layouts") or []:
        _validate_layout(item)
    sync = diff.get("update_sync")
    if sync is not None:
        if not isinstance(sync, dict):
            raise ValidationError("bad_sync", "update_sync must be an object.")
        tables = sync.get("tables")
        if tables is not None and not isinstance(tables, list):
            raise ValidationError("bad_sync", "sync.tables must be a list.")


def _validate_layout(item: dict[str, Any]) -> None:
    if not isinstance(item, dict) or not _is_name(item.get("id")):
        raise ValidationError("bad_layout", "Layout id must be snake_case.")
    rows = item.get("rows")
    if not isinstance(rows, list):
        raise ValidationError("bad_layout", "Layout rows must be a list.")
    for row in rows:
        if not isinstance(row, dict):
            raise ValidationError("bad_layout", "Layout row must be an object.")
        cols = row.get("cols")
        if not isinstance(cols, list):
            raise ValidationError("bad_layout", "Layout cols must be a list.")
        for col in cols:
            if not isinstance(col, dict):
                raise ValidationError("bad_layout", "Layout col must be an object.")
            widget = col.get("widget")
            if widget not in LAYOUT_WIDGETS:
                raise ValidationError("bad_layout", f"Unknown widget: {widget!r}.")
            span = col.get("span")
            if not isinstance(span, int) or span < 1 or span > 12:
                raise ValidationError("bad_layout", "span must be 1-12.")


def merge_final_schema(schema: dict[str, Any], diff: dict[str, Any]) -> dict[str, Any]:
    out = copy.deepcopy(schema)
    for key, default in (
        ("formulas", []),
        ("rules", []),
        ("roles", []),
        ("grants", []),
        ("import_profiles", []),
        ("layouts", []),
        ("reminders", []),
        ("jobs", []),
    ):
        out.setdefault(key, default if key != "sync" else {"tables": [], "label": "Home"})
    out.setdefault("sync", {"tables": [], "label": "Home"})

    def _upsert_list(target: list, items: list, id_key: str = "id") -> None:
        for item in items:
            found = False
            for idx, existing in enumerate(target):
                if isinstance(existing, dict) and existing.get(id_key) == item.get(id_key):
                    target[idx] = {**existing, **item}
                    found = True
                    break
            if not found:
                new_item = dict(item)
                new_item.setdefault("enabled", True)
                target.append(new_item)

    _upsert_list(out["formulas"], diff.get("add_formulas") or [])
    _upsert_list(out["rules"], diff.get("add_rules") or [])
    _upsert_list(out["roles"], diff.get("add_roles") or [], id_key="name")
    _upsert_list(out["grants"], diff.get("add_grants") or [])
    _upsert_list(out["import_profiles"], diff.get("add_import_profiles") or [])
    _upsert_list(out["layouts"], diff.get("add_layouts") or [])
    _upsert_list(out["reminders"], diff.get("add_reminders") or [])
    for item in diff.get("update_reminders") or []:
        _upsert_list(out["reminders"], [item])
    for rid in diff.get("disable_reminders") or []:
        for rem in out["reminders"]:
            if isinstance(rem, dict) and rem.get("id") == rid:
                rem["enabled"] = False
    _upsert_list(out["jobs"], diff.get("add_jobs") or [])
    for rid in diff.get("disable_rules") or []:
        for rule in out["rules"]:
            if isinstance(rule, dict) and rule.get("id") == rid:
                rule["enabled"] = False
    remove_ids = {str(x) for x in (diff.get("remove_rules") or [])}
    if remove_ids:
        out["rules"] = [
            rule
            for rule in out["rules"]
            if not (isinstance(rule, dict) and rule.get("id") in remove_ids)
        ]
    for jid in diff.get("disable_jobs") or []:
        for job in out["jobs"]:
            if isinstance(job, dict) and job.get("id") == jid:
                job["enabled"] = False
    sync = diff.get("update_sync")
    if isinstance(sync, dict):
        if "tables" in sync:
            out["sync"]["tables"] = list(sync["tables"] or [])
        if "label" in sync:
            out["sync"]["label"] = sync["label"]
    return out


def apply_final_side_effects(cfg, diff: dict[str, Any]) -> None:
    from app.schedule_refresh import refresh_schedules_for_diff

    if any(
        diff.get(k)
        for k in (
            "add_reminders",
            "update_reminders",
            "disable_reminders",
            "add_jobs",
            "disable_jobs",
        )
    ):
        refresh_schedules_for_diff(cfg, diff)
