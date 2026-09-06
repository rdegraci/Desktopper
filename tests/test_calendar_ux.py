"""Layout calendar month-grid: static contract."""

from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path

from app.config import load_config, repo_root
from app.host_db import ensure_host_tables
from app.server import create_app


class CalendarUxTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.appdir = Path(self.tmp.name) / "appdir"
        self.appdir.mkdir()
        os.environ["DESKTOPPER_APPDIR"] = str(self.appdir)
        self.cfg = load_config()
        ensure_host_tables(self.cfg.appdir)
        self.flask_app = create_app()
        self.client = self.flask_app.test_client()

    def tearDown(self) -> None:
        os.environ.pop("DESKTOPPER_APPDIR", None)
        self.tmp.cleanup()

    def test_layout_js_has_month_grid_markers(self) -> None:
        path = repo_root() / "static" / "js" / "layout.js"
        text = path.read_text(encoding="utf-8")
        self.assertIn("calendar-grid", text)
        self.assertIn("calendarMonthMatrix", text)
        self.assertIn("calendarDateKey", text)
        self.assertIn("#form/", text)
        self.assertIn('text: "Prev"', text)
        self.assertIn('text: "Next"', text)
        js = self.client.get("/js/layout.js").get_data(as_text=True)
        self.assertIn("calendar-grid", js)
        self.assertIn("#form/", js)

    def test_layout_css_served_and_linked(self) -> None:
        css_path = repo_root() / "static" / "css" / "layout.css"
        css_text = css_path.read_text(encoding="utf-8")
        self.assertIn(".calendar-grid", css_text)
        css = self.client.get("/css/layout.css")
        self.assertEqual(css.status_code, 200)
        self.assertIn(".calendar-grid", css.get_data(as_text=True))
        index = self.client.get("/").get_data(as_text=True)
        self.assertIn("/css/layout.css", index)


if __name__ == "__main__":
    unittest.main()
