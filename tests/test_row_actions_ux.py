"""Edit and Destroy actions on list rows: static contract and API paths."""

from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path

from app.config import load_config, repo_root
from app.engine import apply_diff
from app.host_db import ensure_host_tables
from app.server import create_app

TASKS_DIFF = {
    "summary": "Tasks list.",
    "app": {"title": "Tasks", "home": "tasks_list"},
    "add_tables": [
        {
            "name": "tasks",
            "label": "Tasks",
            "columns": [
                {
                    "name": "title",
                    "type": "TEXT",
                    "label": "Title",
                    "nullable": False,
                    "widget": "text",
                },
            ],
        }
    ],
    "add_screens": [
        {
            "id": "tasks_list",
            "type": "list",
            "table": "tasks",
            "title": "Tasks",
            "columns": ["title"],
        },
        {"id": "tasks_form", "type": "form", "table": "tasks", "title": "Task"},
    ],
}


def _js() -> str:
    return (repo_root() / "static" / "js" / "app.js").read_text(encoding="utf-8")


def _slice(text: str, start: str, end: str) -> str:
    i = text.index(start)
    return text[i : text.index(end, i)]


class RowActionsUxTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.appdir = Path(self.tmp.name) / "appdir"
        self.appdir.mkdir()
        os.environ["DESKTOPPER_APPDIR"] = str(self.appdir)
        self.cfg = load_config()
        ensure_host_tables(self.cfg.appdir)
        apply_diff(self.cfg, TASKS_DIFF)
        self.client = create_app().test_client()

    def tearDown(self) -> None:
        os.environ.pop("DESKTOPPER_APPDIR", None)
        self.tmp.cleanup()

    def test_each_row_has_edit_and_destroy(self) -> None:
        draw_list = _slice(_js(), "function drawList(", "function fieldId(")
        self.assertIn('text: "Actions"', draw_list)
        self.assertIn('text: "Edit"', draw_list)
        self.assertIn('text: "Destroy"', draw_list)
        self.assertIn("openEditModal(tableName, row.id, reloadList)", draw_list)
        # Destroy goes through the confirm modal, never straight to DELETE.
        self.assertIn("confirmDelete(tableName, row.id, reloadList)", draw_list)
        self.assertNotIn('method: "DELETE"', draw_list)
        # Button clicks must not also trigger the row's navigate handler.
        self.assertEqual(draw_list.count("ev.stopPropagation();"), 3)

    def test_edit_modal_prefills_row_and_puts(self) -> None:
        modal = _slice(_js(), "function openRecordModal(", "function drawForm(")
        self.assertIn('rowPath += "/" + rowId', modal)
        self.assertIn("rowId ? api(rowPath)", modal)
        self.assertIn("appendFormFields(form, tableName, screen, cols, results[1]", modal)
        self.assertIn('rowId ? "PUT" : "POST"', modal)
        # Errors stay in the modal; only success hides it.
        self.assertIn(".catch(function (err) {\n          modalError(err.message);", modal)

    def test_confirm_delete_accepts_refresh_callback(self) -> None:
        boot = _slice(_js(), "function boot(", "boot();")
        self.assertIn('typeof info.after === "function"', boot)
        html = self.client.get("/").get_data(as_text=True)
        self.assertIn('id="confirm-modal"', html)
        self.assertIn('id="confirm-ok"', html)

    def test_update_and_delete_api_used_by_row_actions(self) -> None:
        rid = self.client.post("/api/tables/tasks", json={"title": "A"}).get_json()["id"]
        ok = self.client.put(f"/api/tables/tasks/{rid}", json={"title": "B"})
        self.assertEqual(ok.status_code, 200)
        self.assertEqual(self.client.get(f"/api/tables/tasks/{rid}").get_json()["title"], "B")
        bad = self.client.put(f"/api/tables/tasks/{rid}", json={"title": None})
        self.assertGreaterEqual(bad.status_code, 400)
        self.assertIn("error", bad.get_json())
        self.assertEqual(self.client.get(f"/api/tables/tasks/{rid}").get_json()["title"], "B")
        gone = self.client.delete(f"/api/tables/tasks/{rid}")
        self.assertIn(gone.status_code, (200, 204))
        self.assertEqual(self.client.get("/api/tables/tasks").get_json(), [])


if __name__ == "__main__":
    unittest.main()
