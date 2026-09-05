"""Interactive layout kanban: static contract and status PUT path."""

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
    "summary": "Tasks for kanban.",
    "app": {"title": "Board", "home": "board_screen"},
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
                {
                    "name": "status",
                    "type": "TEXT",
                    "label": "Status",
                    "nullable": False,
                    "widget": "select",
                    "enum": ["unstarted", "started", "done"],
                },
            ],
        }
    ],
    "add_layouts": [
        {
            "id": "task_board",
            "title": "Board",
            "rows": [
                {
                    "cols": [
                        {
                            "span": 12,
                            "widget": "kanban",
                            "table": "tasks",
                            "column": "status",
                            "title_column": "title",
                        }
                    ]
                }
            ],
        }
    ],
    "add_screens": [
        {
            "id": "board_screen",
            "type": "layout",
            "layout_id": "task_board",
            "title": "Board",
        },
        {
            "id": "tasks_list",
            "type": "list",
            "table": "tasks",
            "title": "Tasks",
            "columns": ["title", "status"],
        },
        {
            "id": "tasks_form",
            "type": "form",
            "table": "tasks",
            "title": "Task",
        },
    ],
}


class KanbanUxTests(unittest.TestCase):
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

    def test_layout_js_has_interactive_markers(self) -> None:
        path = repo_root() / "static" / "js" / "layout.js"
        text = path.read_text(encoding="utf-8")
        self.assertIn('draggable: "true"', text)
        self.assertIn('method: "PUT"', text)
        self.assertIn("#form/", text)
        self.assertIn("kanbanEnumValues", text)
        js = self.client.get("/js/layout.js").get_data(as_text=True)
        self.assertIn('method: "PUT"', js)
        app_js = self.client.get("/js/app.js").get_data(as_text=True)
        self.assertIn("DesktopperLayout.render(layout, main, schema)", app_js)

    def test_put_updates_kanban_status_column(self) -> None:
        created = self.client.post(
            "/api/tables/tasks",
            json={"title": "Ship board", "status": "unstarted"},
        )
        self.assertEqual(created.status_code, 201)
        row_id = created.get_json()["id"]

        updated = self.client.put(
            f"/api/tables/tasks/{row_id}",
            json={"status": "started"},
        )
        self.assertEqual(updated.status_code, 200)
        body = updated.get_json()
        self.assertEqual(body["status"], "started")
        self.assertEqual(body["title"], "Ship board")

        schema = self.client.get("/api/schema").get_json()
        status_col = next(
            c for c in schema["tables"]["tasks"]["columns"] if c["name"] == "status"
        )
        self.assertEqual(status_col["enum"], ["unstarted", "started", "done"])


if __name__ == "__main__":
    unittest.main()
