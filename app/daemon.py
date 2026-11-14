"""Background service lifecycle: `desktopper daemon start|stop|restart|install|uninstall`."""

from __future__ import annotations

import argparse
import os
import plistlib
import re
import signal
import socket
import subprocess
import sys
import time
from pathlib import Path

from app.config import BindRefusedError, load_config
from app.providers import UnknownLlmProviderError

LABEL = "com.desktopper.server"
REPO_ROOT = Path(__file__).resolve().parents[1]
PIDFILE_NAME = "desktopper.pid"
LOGFILE_NAME = "daemon.log"
STOP_TIMEOUT = 10.0
START_TIMEOUT = 15.0


def plist_path() -> Path:
    return Path.home() / "Library" / "LaunchAgents" / f"{LABEL}.plist"


def _domain() -> str:
    return f"gui/{os.getuid()}"


def _service() -> str:
    return f"{_domain()}/{LABEL}"


def _launchctl(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["launchctl", *args], capture_output=True, text=True)


def agent_loaded() -> bool:
    return _launchctl("print", _service()).returncode == 0


def agent_pid() -> int | None:
    proc = _launchctl("print", _service())
    if proc.returncode != 0:
        return None
    match = re.search(r"^\s*pid = (\d+)\s*$", proc.stdout, re.MULTILINE)
    return int(match.group(1)) if match else None


def manager_of(appdir: Path, pid: int) -> str | None:
    """Return "launchagent" or "pidfile" if this daemon module manages `pid`."""
    if agent_pid() == pid:
        return "launchagent"
    if _read_pid(appdir) == pid:
        return "pidfile"
    return None


def spawn_restart(appdir: Path, port: int | None = None) -> None:
    # A new session keeps the helper alive when restart stops the server that
    # spawned it; launchd also kills the agent's process group on exit.
    cmd = [sys.executable, "-m", "app.server"]
    if port is not None:
        cmd += ["--port", str(port)]
    cmd += ["daemon", "restart"]
    with open(appdir / LOGFILE_NAME, "ab") as log:
        subprocess.Popen(
            cmd,
            cwd=REPO_ROOT,
            stdin=subprocess.DEVNULL,
            stdout=log,
            stderr=log,
            start_new_session=True,
        )


def server_command(port: int | None = None) -> list[str]:
    # No bind is passed: the server takes bind from conf.yaml, and
    # load_config refuses non-loopback binds, so the daemon cannot widen exposure.
    cmd = [sys.executable, "-m", "app.server"]
    if port is not None:
        cmd += ["--port", str(port)]
    return cmd


def build_plist(appdir: Path, port: int | None = None) -> dict:
    env = {"PATH": os.environ.get("PATH", "/usr/bin:/bin:/usr/sbin:/sbin")}
    if os.environ.get("DESKTOPPER_APPDIR", "").strip():
        env["DESKTOPPER_APPDIR"] = str(appdir)
    log = str(appdir / LOGFILE_NAME)
    return {
        "Label": LABEL,
        "ProgramArguments": server_command(port),
        "WorkingDirectory": str(REPO_ROOT),
        "EnvironmentVariables": env,
        "RunAtLoad": True,
        # KeepAlive off so `daemon stop` actually stops the agent's process.
        "KeepAlive": False,
        "ProcessType": "Interactive",
        "StandardOutPath": log,
        "StandardErrorPath": log,
    }


def _pidfile(appdir: Path) -> Path:
    return appdir / PIDFILE_NAME


def _pid_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def _read_pid(appdir: Path) -> int | None:
    path = _pidfile(appdir)
    try:
        pid = int(path.read_text().strip())
    except (OSError, ValueError):
        return None
    if _pid_alive(pid):
        return pid
    path.unlink(missing_ok=True)
    return None


def port_open(bind: str, port: int) -> bool:
    try:
        with socket.create_connection((bind, port), timeout=0.5):
            return True
    except OSError:
        return False


def _wait(pred, timeout: float) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if pred():
            return True
        time.sleep(0.2)
    return pred()


def _url(cfg) -> str:
    return f"http://{cfg.bind}:{cfg.port}/"


def cmd_start(cfg) -> int:
    if port_open(cfg.bind, cfg.port):
        print(f"Desktopper is already running at {_url(cfg)}")
        return 0
    if agent_loaded():
        proc = _launchctl("kickstart", _service())
        if proc.returncode != 0:
            print(f"launchctl kickstart failed: {proc.stderr.strip()}", file=sys.stderr)
            return 1
        how = f"LaunchAgent {LABEL}"
    else:
        log = open(cfg.appdir / LOGFILE_NAME, "ab")
        proc = subprocess.Popen(
            server_command(getattr(cfg, "cli_port", None)),
            cwd=REPO_ROOT,
            stdin=subprocess.DEVNULL,
            stdout=log,
            stderr=log,
            start_new_session=True,
        )
        log.close()
        _pidfile(cfg.appdir).write_text(f"{proc.pid}\n")
        how = f"pid {proc.pid}"
    if not _wait(lambda: port_open(cfg.bind, cfg.port), START_TIMEOUT):
        print(
            f"Desktopper did not start listening on {_url(cfg)}. "
            f"See {cfg.appdir / LOGFILE_NAME}",
            file=sys.stderr,
        )
        return 1
    print(f"Desktopper started ({how}) at {_url(cfg)}")
    return 0


def cmd_stop(cfg) -> int:
    stopped = False
    if agent_loaded():
        proc = _launchctl("kill", "SIGTERM", _service())
        stopped = proc.returncode == 0
    pid = _read_pid(cfg.appdir)
    if pid is not None:
        os.kill(pid, signal.SIGTERM)
        if not _wait(lambda: not _pid_alive(pid), STOP_TIMEOUT):
            os.kill(pid, signal.SIGKILL)
        _pidfile(cfg.appdir).unlink(missing_ok=True)
        stopped = True
    if stopped:
        _wait(lambda: not port_open(cfg.bind, cfg.port), STOP_TIMEOUT)
    if port_open(cfg.bind, cfg.port):
        print(
            f"Something is still listening on {_url(cfg)} that this daemon "
            "does not manage (for example, `desktopper` in a terminal).",
            file=sys.stderr,
        )
        return 1
    print("Desktopper stopped." if stopped else "Desktopper is not running.")
    return 0


def cmd_restart(cfg) -> int:
    rc = cmd_stop(cfg)
    if rc != 0:
        return rc
    return cmd_start(cfg)


def cmd_install(cfg) -> int:
    # A pidfile-managed instance would hold the port and block the agent's process.
    pid = _read_pid(cfg.appdir)
    if pid is not None:
        rc = cmd_stop(cfg)
        if rc != 0:
            return rc
    path = plist_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("wb") as fh:
        plistlib.dump(build_plist(cfg.appdir, getattr(cfg, "cli_port", None)), fh)
    if agent_loaded():
        # bootout first so launchd reads the refreshed plist.
        _launchctl("bootout", _service())
        _wait(lambda: not agent_loaded(), STOP_TIMEOUT)
        _wait(lambda: not port_open(cfg.bind, cfg.port), STOP_TIMEOUT)
    proc = _launchctl("bootstrap", _domain(), str(path))
    if proc.returncode != 0:
        print(f"launchctl bootstrap failed: {proc.stderr.strip()}", file=sys.stderr)
        return 1
    print(f"Installed LaunchAgent {path}")
    if not _wait(lambda: port_open(cfg.bind, cfg.port), START_TIMEOUT):
        print(
            f"LaunchAgent loaded, but Desktopper is not listening on {_url(cfg)}. "
            f"See {cfg.appdir / LOGFILE_NAME}",
            file=sys.stderr,
        )
        return 1
    print(f"Desktopper started at {_url(cfg)}")
    return 0


def cmd_uninstall(cfg) -> int:
    path = plist_path()
    loaded = agent_loaded()
    if not loaded and not path.exists():
        print(f"LaunchAgent {LABEL} is not installed. Nothing to do.")
        return 0
    if loaded:
        proc = _launchctl("bootout", _service())
        if proc.returncode != 0 and agent_loaded():
            print(f"launchctl bootout failed: {proc.stderr.strip()}", file=sys.stderr)
            return 1
        _wait(lambda: not port_open(cfg.bind, cfg.port), STOP_TIMEOUT)
    path.unlink(missing_ok=True)
    print(f"Uninstalled LaunchAgent {LABEL}.")
    return 0


COMMANDS = {
    "start": (cmd_start, "Start the server in the background if it is not running."),
    "stop": (cmd_stop, "Stop the server started by `daemon start` or the LaunchAgent."),
    "restart": (cmd_restart, "Stop, then start the server."),
    "install": (
        cmd_install,
        f"Install the per-user LaunchAgent ({LABEL}), load it, and start the server. "
        "Re-run to refresh the agent.",
    ),
    "uninstall": (
        cmd_uninstall,
        "Unload and remove the LaunchAgent, which stops its server. "
        "Does nothing if it is not installed.",
    ),
}


def add_parser(subparsers) -> None:
    daemon = subparsers.add_parser(
        "daemon",
        help="Run Desktopper as a background service (start, stop, restart, install, uninstall).",
        description=(
            "Manage Desktopper as a background service. The server binds to "
            "server.bind in conf.yaml; non-loopback binds are refused."
        ),
    )
    actions = daemon.add_subparsers(dest="action", metavar="ACTION", required=True)
    for name, (_, help_text) in COMMANDS.items():
        actions.add_parser(name, help=help_text, description=help_text)


def run(args: argparse.Namespace) -> int:
    if args.action in ("install", "uninstall") and sys.platform != "darwin":
        print("LaunchAgents need macOS.", file=sys.stderr)
        return 1
    try:
        cfg = load_config()
    except (BindRefusedError, UnknownLlmProviderError) as exc:
        print(str(exc), file=sys.stderr)
        return 1
    port = getattr(args, "port", None)
    if port is not None:
        cfg.port = port
    cfg.cli_port = port
    return COMMANDS[args.action][0](cfg)
