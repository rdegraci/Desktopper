import contextlib
import io
import os
import plistlib
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from app import daemon, server

REPO = Path(__file__).resolve().parents[1]


def _cfg(appdir: Path):
    return mock.Mock(bind="127.0.0.1", port=8799, appdir=appdir, cli_port=None)


class DaemonArgsTests(unittest.TestCase):
    def test_actions_parse(self) -> None:
        for action in daemon.COMMANDS:
            args = server._parse_args(["daemon", action])
            self.assertEqual((args.command, args.action), ("daemon", action))

    def test_no_subcommand_runs_server(self) -> None:
        self.assertIsNone(server._parse_args([]).command)

    def test_daemon_requires_action(self) -> None:
        with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as ctx:
            server._parse_args(["daemon"])
        self.assertEqual(ctx.exception.code, 2)

    def test_help_documents_daemon_actions(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            env = {**os.environ, "DESKTOPPER_APPDIR": str(Path(tmp) / "appdir")}
            top = subprocess.run(
                [sys.executable, "-m", "app.server", "--help"],
                cwd=REPO, env=env, capture_output=True, text=True, timeout=30,
            )
            sub = subprocess.run(
                [sys.executable, "-m", "app.server", "daemon", "--help"],
                cwd=REPO, env=env, capture_output=True, text=True, timeout=30,
            )
        self.assertIn("daemon", top.stdout)
        for action in ("start", "stop", "restart", "install", "uninstall"):
            self.assertIn(action, sub.stdout)

    def test_main_dispatches_daemon_without_starting_server(self) -> None:
        with mock.patch.object(daemon, "run", return_value=0) as run, \
                mock.patch.object(server, "create_app") as create_app:
            with self.assertRaises(SystemExit) as ctx:
                server.main(["daemon", "stop"])
        self.assertEqual(ctx.exception.code, 0)
        run.assert_called_once()
        create_app.assert_not_called()


class PlistTests(unittest.TestCase):
    def test_plist_runs_server_without_bind_override(self) -> None:
        plist = daemon.build_plist(Path("/tmp/appdir"), 9001)
        args = plist["ProgramArguments"]
        self.assertEqual(args[1:], ["-m", "app.server", "--port", "9001"])
        self.assertNotIn("--host", args)
        self.assertNotIn("--bind", args)
        self.assertTrue(plist["RunAtLoad"])
        self.assertEqual(plist["Label"], daemon.LABEL)
        plistlib.dumps(plist)


class LaunchAgentTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name)
        self.plist = root / "LaunchAgents" / f"{daemon.LABEL}.plist"
        self.cfg = _cfg(root)
        patches = [
            mock.patch.object(daemon, "plist_path", return_value=self.plist),
            mock.patch.object(daemon, "_wait", return_value=True),
            mock.patch.object(daemon, "port_open", return_value=False),
        ]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)

    def _launchctl(self, loaded: bool):
        calls = []

        def fake(*args):
            calls.append(args)
            rc = 0 if (args[0] != "print" or loaded) else 113
            return subprocess.CompletedProcess(["launchctl", *args], rc, "", "")

        return calls, mock.patch.object(daemon, "_launchctl", side_effect=fake)

    def test_install_writes_plist_and_bootstraps(self) -> None:
        calls, patch = self._launchctl(loaded=False)
        with patch, contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(daemon.cmd_install(self.cfg), 0)
        self.assertTrue(self.plist.is_file())
        self.assertEqual(plistlib.loads(self.plist.read_bytes())["Label"], daemon.LABEL)
        self.assertIn(("bootstrap", daemon._domain(), str(self.plist)), calls)

    def test_reinstall_boots_out_then_bootstraps(self) -> None:
        calls, patch = self._launchctl(loaded=True)
        with patch, contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(daemon.cmd_install(self.cfg), 0)
        verbs = [c[0] for c in calls if c[0] != "print"]
        self.assertEqual(verbs, ["bootout", "bootstrap"])

    def test_uninstall_missing_is_noop_success(self) -> None:
        calls, patch = self._launchctl(loaded=False)
        out = io.StringIO()
        with patch, contextlib.redirect_stdout(out):
            self.assertEqual(daemon.cmd_uninstall(self.cfg), 0)
        self.assertIn("not installed", out.getvalue())
        self.assertNotIn("bootout", [c[0] for c in calls])

    def test_uninstall_boots_out_and_removes_plist(self) -> None:
        self.plist.parent.mkdir(parents=True)
        self.plist.write_bytes(b"")
        calls, patch = self._launchctl(loaded=True)
        with patch, contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(daemon.cmd_uninstall(self.cfg), 0)
        self.assertIn(("bootout", daemon._service()), calls)
        self.assertFalse(self.plist.exists())

    def test_start_when_running_does_nothing(self) -> None:
        with mock.patch.object(daemon, "port_open", return_value=True), \
                mock.patch.object(daemon.subprocess, "Popen") as popen, \
                contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(daemon.cmd_start(self.cfg), 0)
        popen.assert_not_called()

    def test_stop_when_not_running_succeeds(self) -> None:
        _, patch = self._launchctl(loaded=False)
        out = io.StringIO()
        with patch, contextlib.redirect_stdout(out):
            self.assertEqual(daemon.cmd_stop(self.cfg), 0)
        self.assertIn("not running", out.getvalue())


if __name__ == "__main__":
    unittest.main()
