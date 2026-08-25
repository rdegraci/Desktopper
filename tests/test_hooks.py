import json
import os
import tempfile
import unittest
from pathlib import Path

from app.config import load_config, read_or_create_schema
from app.crud import CrudError, insert_row
from app.engine import apply_diff
from app.hooks import get_hook, read_registry
from app.schema_validate import ValidationError, validate_diff
from app.server import create_app


NOTES_TABLE_DIFF = {
    "summary": "Add notes.",
    "add_tables": [
        {
            "name": "notes",
            "label": "Notes",
            "columns": [
                {
                    "name": "title",
                    "type": "TEXT",
                    "label": "Title",
                    "nullable": False,
                    "widget": "text",
                },
                {
                    "name": "body",
                    "type": "TEXT",
                    "label": "Body",
                    "nullable": True,
                    "widget": "textarea",
                },
            ],
        }
    ],
    "add_screens": [
        {
            "id": "notes_list",
            "type": "list",
            "table": "notes",
            "title": "Notes",
            "columns": ["title"],
        },
        {
            "id": "notes_form",
            "type": "form",
            "table": "notes",
            "title": "Note",
        },
    ],
}

EXPORT_HOOK_CODE = """def run(ctx):
    row = ctx.row
    path = ctx.appdir / "exports" / f"{row['id']}.txt"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(row.get("body") or "", encoding="utf-8")
"""

FAIL_HOOK_CODE = """def run(ctx):
    raise RuntimeError("hook failed on purpose")
"""

UPDATED_HOOK_CODE = """def run(ctx):
    row = ctx.row
    path = ctx.appdir / "exports" / f"{row['id']}-updated.txt"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(row.get("body") or "", encoding="utf-8")
"""


class HooksTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.appdir = Path(self.tmp.name)
        os.environ["DESKTOPPER_APPDIR"] = str(self.appdir)
        (self.appdir / ".env").write_text("LLM_API_KEY=test\n", encoding="utf-8")
        self.cfg = load_config(self.appdir)
        apply_diff(self.cfg, NOTES_TABLE_DIFF)

    def tearDown(self) -> None:
        os.environ.pop("DESKTOPPER_APPDIR", None)
        self.tmp.cleanup()

    def _add_hook_diff(self, code: str = EXPORT_HOOK_CODE) -> None:
        apply_diff(
            self.cfg,
            {
                "summary": "Add export hook.",
                "add_hooks": [
                    {
                        "id": "notes_export",
                        "table": "notes",
                        "on": "create",
                        "code": code,
                    }
                ],
            },
        )

    def test_add_hooks_writes_file_and_registry(self) -> None:
        self._add_hook_diff()
        registry = read_registry(self.appdir)
        self.assertEqual(len(registry["hooks"]), 1)
        self.assertEqual(registry["hooks"][0]["id"], "notes_export")
        hook = get_hook(self.cfg, "notes_export")
        self.assertIn("def run(ctx)", hook["code"])
        path = self.appdir / hook["file"]
        self.assertTrue(path.is_file())

    def test_bad_python_rejected(self) -> None:
        schema = read_or_create_schema(self.appdir)
        with self.assertRaises(ValidationError):
            validate_diff(
                schema,
                {
                    "summary": "bad",
                    "add_hooks": [
                        {
                            "id": "bad_hook",
                            "table": "notes",
                            "on": "create",
                            "code": "def run(ctx\n",
                        }
                    ],
                },
                hooks_registry=read_registry(self.appdir),
            )

    def test_insert_runs_create_hook(self) -> None:
        self._add_hook_diff()
        row = insert_row(
            self.cfg,
            "notes",
            {"title": "Test", "body": "Hello hook"},
        )
        export_path = self.appdir / "exports" / f"{row['id']}.txt"
        self.assertTrue(export_path.is_file())
        self.assertEqual(export_path.read_text(encoding="utf-8"), "Hello hook")

    def test_hook_failure_rolls_back_insert(self) -> None:
        self._add_hook_diff(FAIL_HOOK_CODE)
        with self.assertRaises(CrudError) as ctx:
            insert_row(self.cfg, "notes", {"title": "Fail", "body": "nope"})
        self.assertEqual(ctx.exception.status, 500)
        self.assertIn("notes_export", ctx.exception.msg)

    def test_disable_hooks_skips_execution(self) -> None:
        self._add_hook_diff()
        apply_diff(
            self.cfg,
            {"summary": "Disable.", "disable_hooks": ["notes_export"]},
        )
        row = insert_row(self.cfg, "notes", {"title": "Quiet", "body": "silent"})
        export_path = self.appdir / "exports" / f"{row['id']}.txt"
        self.assertFalse(export_path.is_file())

    def test_update_hooks_replaces_source(self) -> None:
        self._add_hook_diff()
        apply_diff(
            self.cfg,
            {
                "summary": "Update hook.",
                "update_hooks": [{"id": "notes_export", "code": UPDATED_HOOK_CODE}],
            },
        )
        row = insert_row(self.cfg, "notes", {"title": "Up", "body": "v2"})
        old_path = self.appdir / "exports" / f"{row['id']}.txt"
        new_path = self.appdir / "exports" / f"{row['id']}-updated.txt"
        self.assertFalse(old_path.is_file())
        self.assertTrue(new_path.is_file())

    def test_remove_hooks_deletes_file(self) -> None:
        self._add_hook_diff()
        hook = get_hook(self.cfg, "notes_export")
        path = self.appdir / hook["file"]
        self.assertTrue(path.is_file())
        apply_diff(
            self.cfg,
            {"summary": "Remove.", "remove_hooks": ["notes_export"]},
        )
        self.assertFalse(path.is_file())
        self.assertEqual(read_registry(self.appdir)["hooks"], [])

    def test_put_api_saves_hook_code(self) -> None:
        self._add_hook_diff()
        client = create_app().test_client()
        res = client.put(
            "/api/hooks/notes_export",
            json={"code": UPDATED_HOOK_CODE},
        )
        self.assertEqual(res.status_code, 200)
        hook = get_hook(self.cfg, "notes_export")
        self.assertIn("-updated.txt", hook["code"])

    def test_intent_payload_includes_hook_sources(self) -> None:
        self._add_hook_diff()
        captured = {}

        def fake(messages):
            captured["user"] = json.loads(messages[1]["content"])
            return json.dumps({"summary": "noop"})

        client = create_app(llm_complete=fake).test_client()
        res = client.post("/api/intent", json={"text": "Do nothing."})
        self.assertEqual(res.status_code, 200)
        user = captured["user"]
        self.assertIn("hooks", user)
        self.assertIn("hook_sources", user)
        self.assertIn("notes_export", user["hook_sources"])

    def test_intent_returns_hooks_changed(self) -> None:
        self._add_hook_diff()

        def fake(_messages):
            return json.dumps(
                {
                    "summary": "Disable export.",
                    "disable_hooks": ["notes_export"],
                }
            )

        client = create_app(llm_complete=fake).test_client()
        res = client.post("/api/intent", json={"text": "Disable the notes hook."})
        self.assertEqual(res.status_code, 200)
        body = res.get_json()
        self.assertEqual(body["hooks_changed"], [{"id": "notes_export", "action": "disable"}])


class HooksOpsUiTests(unittest.TestCase):
    def setUp(self) -> None:
        self.src = Path("static/js/ops.js").read_text(encoding="utf-8")
        self.html = Path("static/ops.html").read_text(encoding="utf-8")

    def test_ops_hooks_ui(self) -> None:
        self.assertIn("/api/hooks", self.src)
        self.assertIn("hooks-tbody", self.html)
        self.assertIn("hook-code", self.html)
        self.assertIn("confirm-modal", self.html)


if __name__ == "__main__":
    unittest.main()
