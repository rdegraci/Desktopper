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
    "summary": "Projects, issues, and comments.",
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
        {
            "name": "comments",
            "label": "Comments",
            "columns": [
                {
                    "name": "body",
                    "type": "TEXT",
                    "label": "Body",
                    "nullable": False,
                    "widget": "textarea",
                },
                {
                    "name": "issue_id",
                    "type": "INTEGER",
                    "label": "Issue",
                    "nullable": False,
                    "widget": "fk",
                    "fk": {"table": "issues", "column": "id", "display": "title"},
                },
            ],
        },
    ],
    "add_screens": [
        {"id": "projects_list", "type": "list", "table": "projects", "title": "Projects", "columns": ["name"]},
        {"id": "issues_list", "type": "list", "table": "issues", "title": "Issues", "columns": ["title"]},
        {
            "id": "issues_form",
            "type": "form",
            "table": "issues",
            "title": "Issue",
            "related": [
                {
                    "table": "comments",
                    "fk": "issue_id",
                    "title": "Comments",
                    "empty": "No comments yet. Add one.",
                }
            ],
        },
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

    def test_details_modal_shows_info_url(self) -> None:
        fn = _slice(_js(), "function openDetailsModal(", "window.DesktopperApp")
        self.assertIn("appendDetailsInfoUrl(body, tableName, rowId)", fn)
        helpers = _slice(_js(), "function rowInfoUrl(", "function openDetailsModal(")
        self.assertIn('"/info"', helpers)
        self.assertIn('"Info URL"', helpers)

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

    def test_info_api_includes_row_and_related_comments(self) -> None:
        iid = self.client.post("/api/tables/issues", json={"title": "Ship"}).get_json()["id"]
        self.client.post(
            "/api/tables/comments", json={"body": "First note", "issue_id": iid}
        )
        self.client.post(
            "/api/tables/comments", json={"body": "Second note", "issue_id": iid}
        )
        other = self.client.post("/api/tables/issues", json={"title": "Other"}).get_json()["id"]
        self.client.post(
            "/api/tables/comments", json={"body": "Other thread", "issue_id": other}
        )

        res = self.client.get(f"/api/tables/issues/{iid}/info")
        self.assertEqual(res.status_code, 200)
        body = res.get_json()
        self.assertEqual(body["table"], "issues")
        self.assertEqual(body["row"]["title"], "Ship")
        self.assertEqual(body["row"]["id"], iid)
        comments = body["related"]["comments"]
        self.assertEqual([c["body"] for c in comments], ["First note", "Second note"])

        # Projects have no form related block in this fixture.
        pid = self.client.post("/api/tables/projects", json={"name": "Solo"}).get_json()["id"]
        bare = self.client.get(f"/api/tables/projects/{pid}/info").get_json()
        self.assertEqual(bare["table"], "projects")
        self.assertEqual(bare["row"]["name"], "Solo")
        self.assertEqual(bare["related"], {})

        missing = self.client.get("/api/tables/issues/999999/info")
        self.assertEqual(missing.status_code, 404)


if __name__ == "__main__":
    unittest.main()
