"""Header Login control becomes Logout beside the signed-in label."""

from __future__ import annotations

import os
import re
import tempfile
import unittest
from pathlib import Path

from app.config import load_config, repo_root
from app.host_db import ensure_host_tables
from app.server import create_app


class HeaderLogoutUxTests(unittest.TestCase):
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

    def _bind_login_source(self) -> str:
        text = (repo_root() / "static" / "js" / "app.js").read_text(encoding="utf-8")
        start = text.index("function bindLogin()")
        end = text.index("function boot()")
        return text[start:end]

    def test_session_label_and_toggle_share_cluster(self) -> None:
        index = self.client.get("/").get_data(as_text=True)
        match = re.search(r'<div[^>]*id="session-cluster"[^>]*>(.*?)</div>', index, re.S)
        self.assertIsNotNone(match)
        cluster = match.group(1)
        self.assertLess(cluster.index('id="session-user"'), cluster.index('id="login-toggle"'))
        self.assertEqual(index.count('id="session-user"'), 1)
        self.assertEqual(index.count('id="login-toggle"'), 1)

    def test_toggle_label_follows_session(self) -> None:
        src = self._bind_login_source()
        self.assertIn('toggle.textContent = signedIn ? "Logout" : "Login";', src)

    def test_toggle_signs_out_when_signed_in(self) -> None:
        src = self._bind_login_source()
        handler = src[src.index('toggle.addEventListener("click"'):]
        handler = handler[: handler.index("});")]
        self.assertIn("if (signedIn)", handler)
        self.assertIn("signOut();", handler)
        sign_out = src[src.index("function signOut()"):]
        self.assertIn('fetch("/api/logout"', sign_out[:300])
        self.assertIn("applySessionState(null);", sign_out[:300])

    def test_logged_out_hides_label(self) -> None:
        src = self._bind_login_source()
        apply = src[src.index("function applySessionState(user)"):src.index("function loadSession()")]
        self.assertIn("sessionUserEl.hidden = true;", apply)
        self.assertIn('sessionUserEl.textContent = "";', apply)


if __name__ == "__main__":
    unittest.main()
