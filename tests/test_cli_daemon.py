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
        for action in ("start", "stop", "restart", "status", "install", "uninstall"):
            self.assertIn(action, sub.stdout)
        self.assertIn("LaunchDaemon", sub.stdout)

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
        plist = daemon.build_plist(
            Path("/tmp/appdir"),
            9001,
            username="jenkins",
            home=Path("/Users/jenkins"),
        )
        args = plist["ProgramArguments"]
        self.assertEqual(args[1:], ["-m", "app.server", "--port", "9001"])
        self.assertNotIn("--host", args)
        self.assertNotIn("--bind", args)
        self.assertTrue(plist["RunAtLoad"])
        self.assertEqual(plist["Label"], daemon.LABEL)
        self.assertEqual(plist["UserName"], "jenkins")
        self.assertEqual(plist["EnvironmentVariables"]["HOME"], "/Users/jenkins")
        self.assertEqual(
            plist["EnvironmentVariables"]["DESKTOPPER_APPDIR"], "/tmp/appdir"
        )
        self.assertNotIn("ProcessType", plist)
        plistlib.dumps(plist)


class LaunchDaemonTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name)
        self.plist = root / "LaunchDaemons" / f"{daemon.LABEL}.plist"
        self.cfg = _cfg(root)
        patches = [
            mock.patch.object(daemon, "plist_path", return_value=self.plist),
            mock.patch.object(daemon, "_wait", return_value=True),
            mock.patch.object(daemon, "port_open", return_value=False),
            mock.patch.object(
                daemon,
                "installer_identity",
                return_value=("jenkins", 501, Path("/Users/jenkins")),
            ),
            mock.patch.object(daemon.os, "geteuid", return_value=0),
            mock.patch.dict(os.environ, {"SUDO_USER": "jenkins"}, clear=False),
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
        body = plistlib.loads(self.plist.read_bytes())
        self.assertEqual(body["Label"], daemon.LABEL)
        self.assertEqual(body["UserName"], "jenkins")
        self.assertIn(("bootstrap", "system", str(self.plist)), calls)
        self.assertIn(("bootout", f"gui/501/{daemon.LABEL}"), calls)

    def test_reinstall_boots_out_then_bootstraps(self) -> None:
        calls, patch = self._launchctl(loaded=True)
        with patch, contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(daemon.cmd_install(self.cfg), 0)
        verbs = [c[0] for c in calls if c[0] != "print" and not (
            c[0] == "bootout" and c[1].startswith("gui/")
        )]
        self.assertEqual(verbs, ["bootout", "bootstrap"])

    def test_install_requires_root(self) -> None:
        with mock.patch.object(daemon.os, "geteuid", return_value=501), \
                contextlib.redirect_stderr(io.StringIO()) as err:
            self.assertEqual(daemon.run(mock.Mock(action="install", port=None)), 1)
        self.assertIn("sudo desktopper daemon install", err.getvalue())

    def test_uninstall_missing_is_noop_success(self) -> None:
        calls, patch = self._launchctl(loaded=False)
        out = io.StringIO()
        with patch, contextlib.redirect_stdout(out):
            self.assertEqual(daemon.cmd_uninstall(self.cfg), 0)
        self.assertIn("not installed", out.getvalue())
        self.assertNotIn(
            "bootout",
            [c[0] for c in calls if not (c[0] == "bootout" and str(c[1]).startswith("gui/"))],
        )

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

    def test_domain_is_system(self) -> None:
        self.assertEqual(daemon._domain(), "system")
        self.assertEqual(daemon._service(), f"system/{daemon.LABEL}")

    def test_status_reports_stopped(self) -> None:
        out = io.StringIO()
        with mock.patch.object(daemon, "port_open", return_value=False), \
                mock.patch.object(daemon, "agent_pid", return_value=None), \
                mock.patch.object(daemon, "agent_loaded", return_value=False), \
                mock.patch.object(daemon, "daemon_installed", return_value=False), \
                contextlib.redirect_stdout(out):
            self.assertEqual(daemon.cmd_status(self.cfg), 0)
        text = out.getvalue()
        self.assertIn("status:      stopped", text)
        self.assertIn("installed:   no", text)
        self.assertIn(f"http://{self.cfg.bind}:{self.cfg.port}/", text)

    def test_status_reports_running_launchdaemon(self) -> None:
        out = io.StringIO()
        self.plist.parent.mkdir(parents=True)
        self.plist.write_bytes(b"")
        with mock.patch.object(daemon, "port_open", return_value=True), \
                mock.patch.object(daemon, "agent_pid", return_value=4242), \
                mock.patch.object(daemon, "agent_loaded", return_value=True), \
                mock.patch.object(daemon, "daemon_installed", return_value=True), \
                contextlib.redirect_stdout(out):
            self.assertEqual(daemon.cmd_status(self.cfg), 0)
        text = out.getvalue()
        self.assertIn("status:      running", text)
        self.assertIn("pid:         4242", text)
        self.assertIn("managed_by:  launchdaemon", text)
        self.assertIn("installed:   yes", text)
        self.assertIn("loaded:      yes", text)


if __name__ == "__main__":
    unittest.main()
