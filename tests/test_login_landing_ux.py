"""Login modal and logged-out landing: static contract and public info API."""

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
    "summary": "Issues for public info.",
    "app": {"title": "Board", "home": "issues_list"},
    "add_tables": [
        {
            "name": "issues",
            "label": "Issues",
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
    "add_screens": [
        {
            "id": "issues_list",
            "type": "list",
            "table": "issues",
            "title": "Issues",
            "columns": ["title"],
        },
        {"id": "issues_form", "type": "form", "table": "issues", "title": "Issue"},
    ],
}


def _js() -> str:
    return (repo_root() / "static" / "js" / "app.js").read_text(encoding="utf-8")


def _slice(text: str, start: str, end: str) -> str:
    i = text.index(start)
    return text[i : text.index(end, i)]


class LoginLandingUxTests(unittest.TestCase):
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

    def test_login_modal_markup(self) -> None:
        html = self.client.get("/").get_data(as_text=True)
        self.assertIn('id="login-modal"', html)
        self.assertIn('id="login-form"', html)
        self.assertIn('id="login-name"', html)
        self.assertIn('id="login-password"', html)
        self.assertIn('id="login-modal-ok"', html)
        self.assertIn('id="landing"', html)
        self.assertIn('id="landing-sign-in"', html)
        self.assertIn("Sign in to continue.", html)
        self.assertNotIn('id="login-panel"', html)
        modal = _slice(html, 'id="login-modal"', 'id="confirm-modal"')
        self.assertIn('data-bs-dismiss="modal"', modal)
        self.assertIn("Cancel", modal)

    def test_login_opens_modal_logout_signs_out(self) -> None:
        src = _slice(_js(), "function bindLogin()", "function boot()")
        self.assertIn("openLoginModal();", src)
        self.assertIn("if (sessionSignedIn)", src)
        self.assertIn("signOut();", src)
        self.assertIn("hideLoginModal();", src)
        helpers = _slice(_js(), "function openLoginModal(", "function bindLogin(")
        self.assertIn('getElementById("login-modal")', helpers)
        self.assertIn("Modal.getOrCreateInstance(modalEl).show()", helpers)

    def test_landing_gates_app_until_signed_in(self) -> None:
        js = _js()
        self.assertIn("function enterSignedOutLanding()", js)
        self.assertIn("function enterSignedInApp()", js)
        landing = _slice(js, "function enterSignedOutLanding(", "function enterSignedInApp(")
        self.assertIn('landing.hidden = false', landing)
        self.assertIn("appShell.hidden = true", landing)
        signed_in = _slice(js, "function enterSignedInApp(", "function openLoginModal(")
        self.assertIn("landing.hidden = true", signed_in)
        self.assertIn("appShell.hidden = false", signed_in)
        self.assertIn("drawNav();", signed_in)
        self.assertIn("route();", signed_in)
        boot = _slice(js, "function boot(", "boot();")
        self.assertIn("enterSignedOutLanding();", boot)
        self.assertIn("if (sessionSignedIn)", boot)

    def test_info_api_available_without_session(self) -> None:
        # No desktopper_session cookie: machine readers and LLMs can still fetch.
        created = self.client.post("/api/tables/issues", json={"title": "Public"}).get_json()
        iid = created["id"]
        res = self.client.get(f"/api/tables/issues/{iid}/info")
        self.assertEqual(res.status_code, 200)
        body = res.get_json()
        self.assertEqual(body["table"], "issues")
        self.assertEqual(body["row"]["title"], "Public")
        self.assertEqual(body["related"], {})
        server = (repo_root() / "app" / "server.py").read_text(encoding="utf-8")
        info_fn = _slice(server, "def api_get_info(", "def api_insert(")
        self.assertNotIn("_check_table_access", info_fn)


if __name__ == "__main__":
    unittest.main()
