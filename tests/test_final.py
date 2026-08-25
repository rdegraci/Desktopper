"""FINAL-phase acceptance tests."""

import json
import os
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from unittest import mock

from app.config import load_config, read_or_create_schema
from app.crud import insert_row
from app.engine import apply_diff
from app.formulas import evaluate_formula
from app.host_db import ensure_host_tables
from app.import_csv import run_import
from app.notices import list_notices
from app.reminders import create_reminder, fire_due_reminders, get_reminder, snooze_reminder
from app.rules import run_scheduled_rules
from app.schema_validate import ValidationError, validate_diff
from app.server import create_app
from app.sync import apply_events
from app.tick import run_tick


TIME_ENTRIES_DIFF = {
    "summary": "Add time entries.",
    "add_tables": [
        {
            "name": "time_entries",
            "label": "Time",
            "columns": [
                {"name": "hours", "type": "REAL", "label": "Hours", "nullable": False, "widget": "number"},
                {"name": "worked_on", "type": "TEXT", "label": "Date", "nullable": False, "widget": "text"},
            ],
        }
    ],
    "add_screens": [
        {"id": "time_list", "type": "list", "table": "time_entries", "title": "Time", "columns": ["hours"]},
        {"id": "time_form", "type": "form", "table": "time_entries", "title": "Entry"},
    ],
}


class FinalTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.appdir = os.path.join(self.tmp.name, "appdir")
        os.makedirs(self.appdir, exist_ok=True)
        os.environ["DESKTOPPER_APPDIR"] = self.appdir
        self.cfg = load_config()
        ensure_host_tables(self.cfg.appdir)
        apply_diff(self.cfg, TIME_ENTRIES_DIFF)

    def tearDown(self):
        os.environ.pop("DESKTOPPER_APPDIR", None)
        self.tmp.cleanup()

    def test_hours_this_week_formula(self):
        apply_diff(
            self.cfg,
            {
                "summary": "Formula.",
                "add_formulas": [
                    {
                        "id": "hours_this_week",
                        "kind": "aggregate",
                        "result": "REAL",
                        "expr": {
                            "op": "sum",
                            "table": "time_entries",
                            "column": "hours",
                            "filter": {
                                "op": "gte",
                                "left": {"op": "col", "table": "time_entries", "column": "worked_on"},
                                "right": {"op": "week_start", "of": {"op": "now"}},
                            },
                        },
                    }
                ],
            },
        )
        today = datetime.now().strftime("%Y-%m-%d")
        insert_row(self.cfg, "time_entries", {"hours": 2, "worked_on": today})
        insert_row(self.cfg, "time_entries", {"hours": 3, "worked_on": today})
        insert_row(self.cfg, "time_entries", {"hours": 100, "worked_on": "2000-01-01"})
        total = evaluate_formula(self.cfg, "hours_this_week")
        self.assertEqual(total, 5.0)

    def test_schedule_rule_inserts_notice(self):
        apply_diff(
            self.cfg,
            {
                "summary": "Rule.",
                "add_tables": [
                    {
                        "name": "tasks",
                        "label": "Tasks",
                        "columns": [
                            {"name": "due_on", "type": "TEXT", "label": "Due", "nullable": True, "widget": "text"},
                            {
                                "name": "status",
                                "type": "TEXT",
                                "label": "Status",
                                "nullable": False,
                                "widget": "select",
                                "enum": ["open", "done"],
                            },
                        ],
                    }
                ],
                "add_rules": [
                    {
                        "id": "nag_overdue",
                        "enabled": True,
                        "trigger": {"kind": "schedule", "every_seconds": 3600},
                        "table": "tasks",
                        "when": {
                            "op": "and",
                            "args": [
                                {"op": "lt", "left": {"op": "col", "column": "due_on"}, "right": {"op": "now"}},
                                {"op": "neq", "left": {"op": "col", "column": "status"}, "right": {"op": "lit", "value": "done"}},
                            ],
                        },
                        "then": [{"kind": "notify", "title": "Overdue", "body": "Past due."}],
                    }
                ],
            },
        )
        insert_row(
            self.cfg,
            "tasks",
            {"due_on": "2000-01-01", "status": "open"},
        )
        run_scheduled_rules(self.cfg)
        notices = list_notices(self.cfg.appdir)
        self.assertEqual(len(notices), 1)
        run_scheduled_rules(self.cfg)
        self.assertEqual(len(list_notices(self.cfg.appdir)), 1)

    def test_reminder_post_and_snooze(self):
        app = create_app()
        client = app.test_client()
        past = (datetime.now(timezone.utc) - timedelta(minutes=5)).strftime("%Y-%m-%dT%H:%M:%SZ")
        resp = client.post(
            "/api/reminders",
            json={
                "id": "test_once",
                "title": "Test",
                "enabled": True,
                "schedule": {"kind": "once", "at": past},
                "action": {"kind": "notify"},
            },
        )
        self.assertEqual(resp.status_code, 201)
        resp = client.patch(
            "/api/reminders/test_once",
            json={"title": "Updated", "schedule": {"kind": "once", "at": past}},
        )
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.get_json()["title"], "Updated")
        snooze = client.post("/api/reminders/test_once/snooze", json={"minutes": 15})
        self.assertEqual(snooze.status_code, 200)
        self.assertIsNotNone(snooze.get_json().get("next_run_at"))

    def test_cron_and_bad_job_rejected(self):
        schema = read_or_create_schema(self.cfg.appdir)
        with self.assertRaises(ValidationError):
            validate_diff(schema, {"summary": "x", "add_jobs": [{"id": "bad", "kind": "rm -rf", "schedule": {"kind": "interval", "every_seconds": 60}}]})
        with self.assertRaises(ValidationError):
            validate_diff(schema, {"summary": "x", "add_reminders": [{"id": "c", "title": "T", "schedule": {"kind": "once", "at": "2026-01-01T09:00:00", "cron": "* * * * *"}}]})

    def test_guest_forbidden_on_write(self):
        apply_diff(
            self.cfg,
            {
                "summary": "Roles.",
                "add_roles": [{"name": "guest"}],
                "add_grants": [
                    {"id": "g_read", "role": "guest", "table": "time_entries", "action": "read", "allow": True},
                    {"id": "g_no_write", "role": "guest", "table": "time_entries", "action": "update", "allow": False},
                ],
            },
        )
        from app.auth import create_user, login

        create_user(self.cfg, "guest1", "secret", "guest")
        token, _ = login(self.cfg, "guest1", "secret")
        app = create_app()
        client = app.test_client()
        client.set_cookie("desktopper_session", token)
        get_resp = client.get("/api/tables/time_entries")
        self.assertEqual(get_resp.status_code, 200)
        put_resp = client.put("/api/tables/time_entries/1", json={"hours": 9})
        self.assertEqual(put_resp.status_code, 403)

    def test_sync_lww(self):
        apply_diff(self.cfg, {"summary": "sync", "update_sync": {"tables": ["time_entries"]}})
        row = insert_row(self.cfg, "time_entries", {"hours": 1, "worked_on": "2026-01-01"})
        rid = row["id"]
        result = apply_events(
            self.cfg,
            [
                {
                    "replica_id": "remote",
                    "seq": 1,
                    "table": "time_entries",
                    "row_id": rid,
                    "column": "hours",
                    "value": 9,
                    "at": "2026-01-02T00:00:00Z",
                }
            ],
        )
        self.assertEqual(result["applied"], 1)

    def test_csv_import(self):
        apply_diff(
            self.cfg,
            {
                "summary": "profile",
                "add_import_profiles": [
                    {
                        "id": "bank_csv",
                        "table": "time_entries",
                        "encoding": "utf-8",
                        "delimiter": ",",
                        "header_row": 0,
                        "skip_rows": 2,
                        "map": {"Date": "worked_on", "Hours": "hours"},
                        "date_formats": {"worked_on": "%d/%m/%Y"},
                        "duplicate": "skip",
                    }
                ],
            },
        )
        csv_bytes = b"skip\nskip\nDate,Hours\n15/08/2026,2.5\nbad,xx\n16/08/2026,1\n"
        result = run_import(self.cfg, "bank_csv", csv_bytes)
        self.assertEqual(result["ok"], 2)
        self.assertEqual(result["fail"], 1)

    def test_bad_column_type_names_column(self):
        schema = read_or_create_schema(self.cfg.appdir)
        with self.assertRaises(ValidationError) as ctx:
            validate_diff(
                schema,
                {
                    "summary": "x",
                    "add_tables": [
                        {
                            "name": "repositories",
                            "label": "Repos",
                            "columns": [
                                {
                                    "name": "remote_url",
                                    "type": "url",
                                    "label": "URL",
                                    "nullable": False,
                                    "widget": "text",
                                }
                            ],
                        }
                    ],
                },
            )
        self.assertIn("remote_url", str(ctx.exception))
        self.assertIn("url", str(ctx.exception))
        self.assertIn("INTEGER", str(ctx.exception))

    def test_layout_screen_accepted(self):
        schema = read_or_create_schema(self.cfg.appdir)
        diff = {
            "summary": "Dashboard.",
            "app": {"title": "Repos", "home": "repo_dashboard"},
            "add_tables": [
                {
                    "name": "repositories",
                    "label": "Repositories",
                    "columns": [
                        {
                            "name": "name",
                            "type": "TEXT",
                            "label": "Name",
                            "nullable": False,
                            "widget": "text",
                        },
                        {
                            "name": "status",
                            "type": "TEXT",
                            "label": "Status",
                            "nullable": False,
                            "widget": "select",
                            "enum": ["active", "archived"],
                        },
                    ],
                }
            ],
            "add_screens": [
                {
                    "id": "repositories_list",
                    "type": "list",
                    "table": "repositories",
                    "title": "Repositories",
                    "columns": ["name", "status"],
                },
                {
                    "id": "repositories_form",
                    "type": "form",
                    "table": "repositories",
                    "title": "Repository",
                },
                {
                    "id": "repo_dashboard",
                    "type": "layout",
                    "layout_id": "repo_board",
                    "title": "Dashboard",
                },
            ],
            "add_layouts": [
                {
                    "id": "repo_board",
                    "title": "Repo board",
                    "rows": [
                        {
                            "cols": [
                                {
                                    "span": 12,
                                    "widget": "kanban",
                                    "table": "repositories",
                                    "column": "status",
                                    "title_column": "name",
                                }
                            ]
                        }
                    ],
                }
            ],
        }
        validate_diff(schema, diff)
        apply_diff(self.cfg, diff)
        merged = read_or_create_schema(self.cfg.appdir)
        screen = next(s for s in merged["screens"] if s["id"] == "repo_dashboard")
        self.assertEqual(screen["type"], "layout")
        self.assertEqual(screen["layout_id"], "repo_board")
        self.assertEqual(merged["app"]["home"], "repo_dashboard")

    def test_add_screens_unknown_keys_lists_them(self):
        schema = read_or_create_schema(self.cfg.appdir)
        with self.assertRaises(ValidationError) as ctx:
            validate_diff(
                schema,
                {
                    "summary": "x",
                    "add_tables": [
                        {
                            "name": "items",
                            "label": "Items",
                            "columns": [
                                {
                                    "name": "name",
                                    "type": "TEXT",
                                    "label": "Name",
                                    "nullable": False,
                                    "widget": "text",
                                }
                            ],
                        }
                    ],
                    "add_screens": [
                        {
                            "id": "items_list",
                            "type": "list",
                            "table": "items",
                            "title": "Items",
                            "columns": ["name"],
                            "layout_id": "oops",
                        }
                    ],
                },
            )
        self.assertIn("layout_id is only allowed", str(ctx.exception))

    def test_add_columns_merges_once(self):
        schema = read_or_create_schema(self.cfg.appdir)
        apply_diff(
            self.cfg,
            {
                "summary": "One column.",
                "add_columns": [
                    {
                        "table": "time_entries",
                        "column": {
                            "name": "billable",
                            "type": "INTEGER",
                            "label": "Billable",
                            "nullable": True,
                            "widget": "checkbox",
                        },
                    }
                ],
            },
        )
        merged = read_or_create_schema(self.cfg.appdir)
        names = [c["name"] for c in merged["tables"]["time_entries"]["columns"]]
        self.assertEqual(names.count("billable"), 1)

    def test_add_columns_unknown_keys_lists_them(self):
        schema = read_or_create_schema(self.cfg.appdir)
        with self.assertRaises(ValidationError) as ctx:
            validate_diff(
                schema,
                {
                    "summary": "x",
                    "add_tables": [
                        {
                            "name": "items",
                            "label": "Items",
                            "columns": [
                                {
                                    "name": "name",
                                    "type": "TEXT",
                                    "label": "Name",
                                    "nullable": False,
                                    "widget": "text",
                                }
                            ],
                        }
                    ],
                    "add_columns": [
                        {
                            "table": "items",
                            "name": "done",
                            "type": "INTEGER",
                            "widget": "checkbox",
                        }
                    ],
                },
            )
        msg = str(ctx.exception)
        self.assertIn("unknown keys", msg)
        self.assertIn("name", msg)

    def test_update_columns_checkbox_on_integer(self):
        apply_diff(
            self.cfg,
            {
                "summary": "Flag.",
                "add_tables": [
                    {
                        "name": "repos",
                        "label": "Repos",
                        "columns": [
                            {
                                "name": "pinned",
                                "type": "INTEGER",
                                "label": "Pinned",
                                "nullable": False,
                                "widget": "number",
                            }
                        ],
                    }
                ],
            },
        )
        apply_diff(
            self.cfg,
            {
                "summary": "Checkbox.",
                "update_columns": [
                    {"table": "repos", "column": "pinned", "widget": "checkbox", "label": "Pinned"}
                ],
            },
        )
        schema = read_or_create_schema(self.cfg.appdir)
        col = next(c for c in schema["tables"]["repos"]["columns"] if c["name"] == "pinned")
        self.assertEqual(col["widget"], "checkbox")

    def test_text_to_checkbox_requires_new_column(self):
        apply_diff(
            self.cfg,
            {
                "summary": "Repos.",
                "add_tables": [
                    {
                        "name": "repos",
                        "label": "Repos",
                        "columns": [
                            {
                                "name": "url",
                                "type": "TEXT",
                                "label": "Lives online",
                                "nullable": True,
                                "widget": "text",
                            }
                        ],
                    }
                ],
            },
        )
        schema = read_or_create_schema(self.cfg.appdir)
        with self.assertRaises(ValidationError) as ctx:
            validate_diff(
                schema,
                {
                    "summary": "x",
                    "update_columns": [
                        {"table": "repos", "column": "url", "widget": "checkbox"}
                    ],
                },
            )
        self.assertIn("add_columns", str(ctx.exception))

    def test_text_to_checkbox_via_add_and_hide(self):
        apply_diff(
            self.cfg,
            {
                "summary": "Repos.",
                "add_tables": [
                    {
                        "name": "repos",
                        "label": "Repos",
                        "columns": [
                            {
                                "name": "url",
                                "type": "TEXT",
                                "label": "Lives online",
                                "nullable": True,
                                "widget": "text",
                            }
                        ],
                    }
                ],
            },
        )
        schema = read_or_create_schema(self.cfg.appdir)
        diff = {
            "summary": "Checkbox.",
            "add_columns": [
                {
                    "table": "repos",
                    "column": {
                        "name": "lives_online",
                        "type": "INTEGER",
                        "label": "Lives online",
                        "nullable": False,
                        "widget": "checkbox",
                    },
                }
            ],
            "hide_columns": [{"table": "repos", "column": "url"}],
        }
        validate_diff(schema, diff)
        apply_diff(self.cfg, diff)
        merged = read_or_create_schema(self.cfg.appdir)
        url_col = next(c for c in merged["tables"]["repos"]["columns"] if c["name"] == "url")
        live_col = next(c for c in merged["tables"]["repos"]["columns"] if c["name"] == "lives_online")
        self.assertTrue(url_col.get("hidden"))
        self.assertEqual(live_col.get("widget"), "checkbox")

    def test_unknown_layout_widget_rejected(self):
        schema = read_or_create_schema(self.cfg.appdir)
        with self.assertRaises(ValidationError):
            validate_diff(
                schema,
                {
                    "summary": "x",
                    "add_layouts": [
                        {
                            "id": "bad",
                            "title": "Bad",
                            "rows": [{"cols": [{"span": 12, "widget": "chart"}]}],
                        }
                    ],
                },
            )

    def test_formula_system_op_rejected(self):
        schema = read_or_create_schema(self.cfg.appdir)
        with self.assertRaises(ValidationError):
            validate_diff(
                schema,
                {
                    "summary": "x",
                    "add_formulas": [{"id": "bad", "kind": "aggregate", "result": "REAL", "expr": {"op": "system"}}],
                },
            )

    def test_host_tables_exist(self):
        import sqlite3

        from app.db_paths import db_path

        conn = sqlite3.connect(str(db_path(self.cfg.appdir)))
        try:
            cur = conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='_notices'")
            self.assertIsNotNone(cur.fetchone())
        finally:
            conn.close()


if __name__ == "__main__":
    unittest.main()
