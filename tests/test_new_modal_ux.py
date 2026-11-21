"""New-row modal on list screens: static contract and create API path."""

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


class NewModalUxTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.appdir = Path(self.tmp.name) / "appdir"
        self.appdir.mkdir()
        os.environ["DESKTOPPER_APPDIR"] = str(self.appdir)
        self.cfg = load_config()
        ensure_host_tables(self.cfg.appdir)
        apply_diff(self.cfg, TASKS_DIFF)
        self.flask_app = create_app()
        self.client = self.flask_app.test_client()

    def tearDown(self) -> None:
        os.environ.pop("DESKTOPPER_APPDIR", None)
        self.tmp.cleanup()

    def test_index_has_new_modal_with_cancel_and_ok(self) -> None:
        html = self.client.get("/").get_data(as_text=True)
        self.assertIn('id="new-modal"', html)
        self.assertIn('id="new-modal-form"', html)
        self.assertIn('id="new-modal-error"', html)
        self.assertIn('id="new-modal-ok">Ok<', html)
        start = html.index('id="new-modal"')
        modal = html[start : html.index("</script>", start)]
        self.assertIn('data-bs-dismiss="modal"', modal)
        self.assertIn("Cancel", modal)

    def test_list_new_button_opens_modal_not_form_route(self) -> None:
        text = (repo_root() / "static" / "js" / "app.js").read_text(encoding="utf-8")
        start = text.index("function drawList(")
        end = text.index("function fieldId(", start)
        draw_list = text[start:end]
        self.assertIn("openNewModal(tableName", draw_list)
        self.assertNotIn('go("#form/" + tableName);', draw_list)
        # Row click opens the read-only details modal, not the form route.
        self.assertIn("openDetailsModal(tableName, row.id);", draw_list)

    def test_modal_and_form_share_field_rendering(self) -> None:
        js = self.client.get("/js/app.js").get_data(as_text=True)
        start = js.index("function openNewModal(")
        end = js.index("function drawForm(", start)
        modal_fn = js[start:end]
        self.assertIn("appendFormFields(form, tableName, screen, cols", modal_fn)
        self.assertIn('var rowPath = "/api/tables/"', modal_fn)
        self.assertIn('postJson(rowPath, rowId ? "PUT" : "POST", body)', modal_fn)
        form_fn = js[end:]
        self.assertIn("appendFormFields(form, tableName, screen, cols, row, fkMap)", form_fn)

    def test_create_api_used_by_modal(self) -> None:
        ok = self.client.post("/api/tables/tasks", json={"title": "From modal"})
        self.assertEqual(ok.status_code, 201)
        rows = self.client.get("/api/tables/tasks").get_json()
        self.assertEqual([r["title"] for r in rows], ["From modal"])
        bad = self.client.post("/api/tables/tasks", json={"title": None})
        self.assertGreaterEqual(bad.status_code, 400)
        self.assertIn("error", bad.get_json())
        rows = self.client.get("/api/tables/tasks").get_json()
        self.assertEqual(len(rows), 1)


if __name__ == "__main__":
    unittest.main()
