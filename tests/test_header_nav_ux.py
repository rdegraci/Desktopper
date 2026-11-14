"""Header view navigation renders as buttons: static contract."""

from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path

from app.config import load_config, repo_root
from app.host_db import ensure_host_tables
from app.server import create_app


class HeaderNavUxTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.appdir = Path(self.tmp.name) / "appdir"
        self.appdir.mkdir()
        os.environ["DESKTOPPER_APPDIR"] = str(self.appdir)
        self.cfg = load_config()
        ensure_host_tables(self.cfg.appdir)
        self.client = create_app().test_client()

    def tearDown(self) -> None:
        os.environ.pop("DESKTOPPER_APPDIR", None)
        self.tmp.cleanup()

    def _draw_nav_source(self) -> str:
        text = (repo_root() / "static" / "js" / "app.js").read_text(encoding="utf-8")
        start = text.index("function drawNav()")
        end = text.index("function drawEmpty(")
        return text[start:end]

    def test_view_links_are_buttons_with_same_hashes(self) -> None:
        src = self._draw_nav_source()
        self.assertIn("btn btn-sm btn-outline-primary nav-view-btn", src)
        self.assertIn('viewNavButton("#list/" + screen.table', src)
        self.assertIn('viewNavButton("#layout/" + screen.layout_id', src)
        self.assertNotIn('className: "nav-link"', src)

    def test_active_view_is_marked(self) -> None:
        src = self._draw_nav_source()
        self.assertIn("function markActiveNav()", src)
        self.assertIn('"aria-current", "page"', src)
        self.assertIn('"btn-primary"', src)
        js = self.client.get("/js/app.js").get_data(as_text=True)
        route = js[js.index("function route()"):]
        self.assertIn("markActiveNav();", route[:200])

    def test_non_view_header_controls_unchanged(self) -> None:
        index = self.client.get("/").get_data(as_text=True)
        for marker in ('id="ops-link"', 'id="global-search"', 'id="notices-badge"', 'id="login-toggle"', 'id="nav-screens"'):
            self.assertIn(marker, index)


if __name__ == "__main__":
    unittest.main()
