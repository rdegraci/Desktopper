"""Row-click details modal on list screens: static contract and read API."""

from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path

from app.config import load_config, repo_root
from app.engine import apply_diff
from app.host_db import ensure_host_tables
from app.server import create_app

DIFF = {
    "summary": "Projects and issues.",
    "app": {"title": "Tracker", "home": "projects_list"},
    "add_tables": [
        {
            "name": "projects",
            "label": "Projects",
            "columns": [
                {"name": "name", "type": "TEXT", "label": "Name", "nullable": False, "widget": "text"},
                {"name": "notes", "type": "TEXT", "label": "Notes", "nullable": True, "widget": "textarea"},
            ],
        },
        {
            "name": "issues",
            "label": "Issues",
            "columns": [
                {"name": "title", "type": "TEXT", "label": "Title", "nullable": False, "widget": "text"},
            ],
        },
    ],
    "add_screens": [
        {"id": "projects_list", "type": "list", "table": "projects", "title": "Projects", "columns": ["name"]},
        {"id": "issues_list", "type": "list", "table": "issues", "title": "Issues", "columns": ["title"]},
    ],
}


def _js() -> str:
    return (repo_root() / "static" / "js" / "app.js").read_text(encoding="utf-8")


def _slice(text: str, start: str, end: str) -> str:
    i = text.index(start)
    return text[i : text.index(end, i)]


class DetailsModalUxTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.appdir = Path(self.tmp.name) / "appdir"
        self.appdir.mkdir()
        os.environ["DESKTOPPER_APPDIR"] = str(self.appdir)
        self.cfg = load_config()
        ensure_host_tables(self.cfg.appdir)
        apply_diff(self.cfg, DIFF)
        self.client = create_app().test_client()

    def tearDown(self) -> None:
        os.environ.pop("DESKTOPPER_APPDIR", None)
        self.tmp.cleanup()

    def test_row_click_opens_details_not_form(self) -> None:
        draw_list = _slice(_js(), "function drawList(", "function fieldId(")
        self.assertIn("openDetailsModal(tableName, row.id);", draw_list)
        self.assertNotIn('go("#form/" + tableName + "/" + row.id)', draw_list)
        # Edit and Destroy stay separate actions.
        self.assertIn("openEditModal(tableName, row.id, reloadList)", draw_list)
        self.assertIn("confirmDelete(tableName, row.id, reloadList)", draw_list)

    def test_details_modal_is_read_only(self) -> None:
        fn = _slice(_js(), "function openDetailsModal(", "window.DesktopperApp")
        self.assertNotIn("postJson", fn)
        self.assertNotIn('"PUT"', fn)
        self.assertNotIn("<input", fn)
        # Empty values get a placeholder instead of a blank cell.
        self.assertIn('"\\u2014"', fn)
        helper = _slice(_js(), "function detailsText(", "function openDetailsModal(")
        self.assertIn('value == null || value === ""', helper)

    def test_details_modal_markup_has_ok_dismiss(self) -> None:
        html = self.client.get("/").get_data(as_text=True)
        modal = _slice(html, 'id="details-modal"', "<script")
        self.assertIn('id="details-modal-ok"', modal)
        self.assertIn('data-bs-dismiss="modal"', modal)
        self.assertIn("Ok", modal)
        self.assertNotIn("<form", modal)

    def test_row_read_api_for_projects_and_issues(self) -> None:
        pid = self.client.post("/api/tables/projects", json={"name": "P", "notes": None}).get_json()["id"]
        iid = self.client.post("/api/tables/issues", json={"title": "I"}).get_json()["id"]
        project = self.client.get(f"/api/tables/projects/{pid}").get_json()
        self.assertEqual(project["name"], "P")
        self.assertIsNone(project["notes"])
        self.assertEqual(self.client.get(f"/api/tables/issues/{iid}").get_json()["title"], "I")


if __name__ == "__main__":
    unittest.main()
