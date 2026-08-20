import json
import os
import sqlite3
import tempfile
import unittest
from pathlib import Path

from app.config import load_config, read_or_create_schema
from app.engine import apply_diff, db_path
from app.log import read_recent_events, setup_logging
from app.schema_validate import ValidationError


class Slice4EngineTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.appdir = Path(self.tmp.name)
        os.environ["DESKTOPPER_APPDIR"] = str(self.appdir)
        self.cfg = load_config(self.appdir)
        setup_logging(self.cfg)

    def tearDown(self) -> None:
        os.environ.pop("DESKTOPPER_APPDIR", None)
        self.tmp.cleanup()

    def test_rejects_drop_and_unknown_keys(self) -> None:
        before = read_or_create_schema(self.appdir)
        self.assertEqual(before["version"], 0)
        with self.assertRaises(ValidationError) as drop_ctx:
            apply_diff(self.cfg, {"drop_tables": ["books"], "summary": "no"})
        self.assertEqual(drop_ctx.exception.error_code, "forbidden_ddl")
        with self.assertRaises(ValidationError) as unk_ctx:
            apply_diff(self.cfg, {"explode": True, "summary": "no"})
        self.assertEqual(unk_ctx.exception.error_code, "unknown_key")
        after = read_or_create_schema(self.appdir)
        self.assertEqual(after["version"], 0)
        events = read_recent_events(self.appdir / self.cfg.logging.file, 50)
        fails = [e for e in events if e.get("event") == "engine.validate.fail"]
        self.assertGreaterEqual(len(fails), 2)
        for event in fails:
            self.assertFalse(event.get("ok"))
            self.assertIn("error_code", event.get("detail") or {})
            self.assertNotIn("LLM_API_KEY", json.dumps(event))

    def test_add_table_insert_add_column_keeps_row(self) -> None:
        apply_diff(
            self.cfg,
            {
                "summary": "Add contacts.",
                "app": {"title": "Rolodex"},
                "add_tables": [
                    {
                        "name": "contacts",
                        "label": "Contacts",
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
                        "id": "contacts_list",
                        "type": "list",
                        "table": "contacts",
                        "title": "Contacts",
                        "columns": ["name"],
                    },
                    {
                        "id": "contacts_form",
                        "type": "form",
                        "table": "contacts",
                        "title": "Contact",
                    },
                ],
            },
        )
        conn = sqlite3.connect(str(db_path(self.appdir)))
        conn.execute(
            "INSERT INTO contacts (name, created_at, updated_at) VALUES (?,?,?)",
            ("Ada", "2026-01-01T00:00:00", "2026-01-01T00:00:00"),
        )
        conn.commit()
        conn.close()
        apply_diff(
            self.cfg,
            {
                "summary": "Add phone.",
                "add_columns": [
                    {
                        "table": "contacts",
                        "column": {
                            "name": "phone",
                            "type": "TEXT",
                            "label": "Phone",
                            "nullable": True,
                            "widget": "text",
                        },
                    }
                ],
            },
        )
        conn = sqlite3.connect(str(db_path(self.appdir)))
        row = conn.execute(
            "SELECT name, phone FROM contacts WHERE name = ?", ("Ada",)
        ).fetchone()
        conn.close()
        self.assertEqual(row[0], "Ada")
        self.assertIsNone(row[1])
        schema = read_or_create_schema(self.appdir)
        self.assertEqual(schema["version"], 2)
        self.assertEqual(schema["app"]["title"], "Rolodex")

    def test_fk_missing_leaves_files_unchanged(self) -> None:
        apply_diff(
            self.cfg,
            {
                "summary": "Books only.",
                "add_tables": [
                    {
                        "name": "books",
                        "label": "Books",
                        "columns": [
                            {
                                "name": "title",
                                "type": "TEXT",
                                "label": "Title",
                                "nullable": False,
                                "widget": "text",
                            }
                        ],
                    }
                ],
            },
        )
        schema_before = (self.appdir / "schema.json").read_text(encoding="utf-8")
        db_before = db_path(self.appdir).read_bytes()
        version_before = read_or_create_schema(self.appdir)["version"]
        with self.assertRaises(ValidationError) as ctx:
            apply_diff(
                self.cfg,
                {
                    "summary": "Bad fk.",
                    "add_columns": [
                        {
                            "table": "books",
                            "column": {
                                "name": "borrower_id",
                                "type": "INTEGER",
                                "label": "Lent to",
                                "nullable": True,
                                "widget": "fk",
                                "fk": {
                                    "table": "people",
                                    "column": "id",
                                    "display": "name",
                                },
                            },
                        }
                    ],
                },
            )
        self.assertEqual(ctx.exception.error_code, "fk_missing")
        self.assertEqual(
            (self.appdir / "schema.json").read_text(encoding="utf-8"),
            schema_before,
        )
        self.assertEqual(db_path(self.appdir).read_bytes(), db_before)
        self.assertEqual(read_or_create_schema(self.appdir)["version"], version_before)


if __name__ == "__main__":
    unittest.main()
