"""Ops Settings section restarts the Desktopper daemon."""

from __future__ import annotations

import contextlib
import io
import os
import re
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import yaml

from app import daemon
from app.auth import create_user, ensure_owner, login
from app.config import load_config, repo_root
from app.host_db import ensure_host_tables
from app.server import create_app


class DaemonSettingsApiTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.appdir = Path(self.tmp.name)
        os.environ["DESKTOPPER_APPDIR"] = str(self.appdir)
        (self.appdir / "conf.yaml").write_text(
            yaml.safe_dump(
                {
                    "server": {"bind": "127.0.0.1", "port": 8000},
                    "llm": {"provider": "openai_compatible", "model": "test"},
                    "auth": {"owner": {"name": "admin", "password": "admin"}},
                }
            ),
            encoding="utf-8",
        )
        (self.appdir / ".env").write_text("LLM_API_KEY=\n", encoding="utf-8")
        self.cfg = load_config(self.appdir)
        ensure_host_tables(self.cfg.appdir)
        with contextlib.redirect_stdout(io.StringIO()):
            ensure_owner(self.cfg)
        self.plist = self.appdir / "LaunchAgents" / f"{daemon.LABEL}.plist"
        patches = [
            mock.patch.object(daemon, "plist_path", return_value=self.plist),
            mock.patch.object(daemon, "spawn_restart"),
        ]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)
        self.spawn = daemon.spawn_restart

    def tearDown(self) -> None:
        os.environ.pop("DESKTOPPER_APPDIR", None)
        self.tmp.cleanup()

    def _client(self, user: str | None = "admin", password: str = "admin", port=None):
        client = create_app(port=port).test_client()
        if user:
            token, _ = login(self.cfg, user, password)
            client.set_cookie("desktopper_session", token)
        return client

    def test_status_and_restart_require_owner(self) -> None:
        create_user(self.cfg, "guest1", "secret", "guest")
        for client in (self._client(None), self._client("guest1", "secret")):
            self.assertEqual(client.get("/api/daemon").status_code, 403)
            self.assertEqual(client.post("/api/daemon/restart").status_code, 403)
        self.spawn.assert_not_called()

    def test_status_reports_manager_and_pid(self) -> None:
        with mock.patch.object(daemon, "agent_pid", return_value=os.getpid()):
            body = self._client().get("/api/daemon").get_json()
        self.assertEqual(body["managed_by"], "launchagent")
        self.assertEqual(body["pid"], os.getpid())
        self.assertEqual(body["label"], daemon.LABEL)
        self.assertFalse(body["installed"])

    def test_restart_refused_when_not_daemon(self) -> None:
        with mock.patch.object(daemon, "agent_pid", return_value=None):
            resp = self._client().post("/api/daemon/restart")
        self.assertEqual(resp.status_code, 409)
        self.assertEqual(resp.get_json()["error_code"], "not_daemon")
        self.spawn.assert_not_called()

    def test_restart_spawns_helper_after_response(self) -> None:
        with mock.patch.object(daemon, "agent_pid", return_value=os.getpid()):
            resp = self._client(port=9123).post("/api/daemon/restart")
            self.spawn.assert_not_called()
            self.assertEqual(resp.status_code, 200)
            self.assertEqual(resp.get_json()["managed_by"], "launchagent")
            resp.close()
        self.spawn.assert_called_once()
        appdir, port = self.spawn.call_args.args
        self.assertEqual((appdir.resolve(), port), (self.appdir.resolve(), 9123))

    def test_pidfile_server_counts_as_managed(self) -> None:
        (self.appdir / daemon.PIDFILE_NAME).write_text(f"{os.getpid()}\n")
        with mock.patch.object(daemon, "agent_pid", return_value=None):
            self.assertEqual(daemon.manager_of(self.appdir, os.getpid()), "pidfile")


class DaemonHelperTests(unittest.TestCase):
    def test_agent_pid_parses_launchctl_print(self) -> None:
        out = mock.Mock(returncode=0, stdout="\tstate = running\n\tpid = 4242\n")
        with mock.patch.object(daemon, "_launchctl", return_value=out):
            self.assertEqual(daemon.agent_pid(), 4242)
        out = mock.Mock(returncode=0, stdout="\tstate = not running\n")
        with mock.patch.object(daemon, "_launchctl", return_value=out):
            self.assertIsNone(daemon.agent_pid())
        with mock.patch.object(daemon, "_launchctl", return_value=mock.Mock(returncode=113)):
            self.assertIsNone(daemon.agent_pid())

    def test_spawn_restart_detaches_and_passes_port(self) -> None:
        with tempfile.TemporaryDirectory() as tmp, \
                mock.patch.object(daemon.subprocess, "Popen") as popen:
            daemon.spawn_restart(Path(tmp), 9001)
        cmd = popen.call_args.args[0]
        self.assertEqual(cmd[1:], ["-m", "app.server", "--port", "9001", "daemon", "restart"])
        self.assertTrue(popen.call_args.kwargs["start_new_session"])


class DaemonSettingsMarkupTests(unittest.TestCase):
    def setUp(self) -> None:
        self.html = (repo_root() / "static" / "ops.html").read_text(encoding="utf-8")
        self.js = (repo_root() / "static" / "js" / "ops.js").read_text(encoding="utf-8")

    def test_settings_section_has_restart_control(self) -> None:
        match = re.search(r'<div class="collapse" id="settings-panel">(.*?)\n      </div>\n', self.html, re.S)
        self.assertIsNotNone(match)
        panel = match.group(1)
        self.assertIn('id="daemon-restart"', panel)
        self.assertIn('id="daemon-status"', panel)
        self.assertIn("Settings", self.html[: self.html.index('id="settings-panel"')])

    def test_restart_button_confirms_and_waits_for_new_pid(self) -> None:
        handler = self.js[self.js.index('daemonRestartBtn.addEventListener("click"'):]
        handler = handler[: handler.index("\n  }\n")]
        self.assertIn("window.confirm(", handler)
        self.assertIn('fetch("/api/daemon/restart", { method: "POST"', handler)
        wait = self.js[self.js.index("function waitForRestart"):]
        self.assertIn("data.pid === daemonPid", wait[:600])

    def test_owner_only_ui(self) -> None:
        session = self.js[self.js.index("function loadSession()"):]
        session = session[: session.index("function openUserEditor")]
        self.assertIn("settingsOwnerUiEl.hidden = !isOwner;", session)
        self.assertIn("loadDaemonStatus();", session)


if __name__ == "__main__":
    unittest.main()
