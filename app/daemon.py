"""Background service lifecycle: `desktopper daemon start|stop|restart|install|uninstall`."""

from __future__ import annotations

import argparse
import os
import plistlib
import pwd
import re
import signal
import socket
import subprocess
import sys
import time
from pathlib import Path

from app.config import DEFAULT_SUPPORT_NAME, BindRefusedError, load_config
from app.providers import UnknownLlmProviderError

LABEL = "com.desktopper.server"
REPO_ROOT = Path(__file__).resolve().parents[1]
PIDFILE_NAME = "desktopper.pid"
LOGFILE_NAME = "daemon.log"
STOP_TIMEOUT = 10.0
START_TIMEOUT = 15.0
LAUNCH_DAEMONS_DIR = Path("/Library/LaunchDaemons")


def plist_path() -> Path:
    return LAUNCH_DAEMONS_DIR / f"{LABEL}.plist"


def legacy_agent_plist(home: Path) -> Path:
    return home / "Library" / "LaunchAgents" / f"{LABEL}.plist"


def _domain() -> str:
    return "system"


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


def daemon_installed() -> bool:
    return plist_path().is_file()


def manager_of(appdir: Path, pid: int) -> str | None:
    """Return "launchdaemon" or "pidfile" if this daemon module manages `pid`."""
    if agent_pid() == pid:
        return "launchdaemon"
    if daemon_installed() and _read_pid(appdir) == pid:
        return "launchdaemon"
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


def installer_identity() -> tuple[str, int, Path]:
    """Username, uid, and home for the account that owns Desktopper data."""
    if os.geteuid() == 0:
        name = (os.environ.get("SUDO_USER") or "").strip()
        if not name or name == "root":
            raise ValueError(
                "Install with sudo from your user account so SUDO_USER is set, "
                "for example: sudo desktopper daemon install"
            )
    else:
        name = pwd.getpwuid(os.getuid()).pw_name
    info = pwd.getpwnam(name)
    return name, int(info.pw_uid), Path(info.pw_dir)


def default_appdir_for_home(home: Path) -> Path:
    return (home / "Library" / "Application Support" / DEFAULT_SUPPORT_NAME).resolve()


def build_plist(
    appdir: Path,
    port: int | None = None,
    *,
    username: str | None = None,
    home: Path | None = None,
) -> dict:
    if username is None or home is None:
        name, _uid, home_path = installer_identity()
        username = username or name
        home = home or home_path
    env = {
        "PATH": os.environ.get("PATH", "/usr/bin:/bin:/usr/sbin:/sbin"),
        "HOME": str(home),
        # Always pin appdir so launchd does not use root's home.
        "DESKTOPPER_APPDIR": str(appdir),
    }
    log = str(appdir / LOGFILE_NAME)
    return {
        "Label": LABEL,
        "ProgramArguments": server_command(port),
        "WorkingDirectory": str(REPO_ROOT),
        "EnvironmentVariables": env,
        "UserName": username,
        "RunAtLoad": True,
        # KeepAlive off so `daemon stop` actually stops the process.
        "KeepAlive": False,
        "StandardOutPath": log,
        "StandardErrorPath": log,
    }


def _pidfile(appdir: Path) -> Path:
    return appdir / PIDFILE_NAME


def write_pidfile(appdir: Path) -> None:
    _pidfile(appdir).write_text(f"{os.getpid()}\n", encoding="utf-8")


def clear_pidfile(appdir: Path) -> None:
    path = _pidfile(appdir)
    try:
        if int(path.read_text(encoding="utf-8").strip()) == os.getpid():
            path.unlink(missing_ok=True)
    except (OSError, ValueError):
        pass


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
        pid = int(path.read_text(encoding="utf-8").strip())
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


def _remove_legacy_agent(uid: int, home: Path) -> None:
    # Older Desktopper versions used a per-user LaunchAgent that dies on logout.
    _launchctl("bootout", f"gui/{uid}/{LABEL}")
    legacy_agent_plist(home).unlink(missing_ok=True)


def _sudo_hint(action: str) -> str:
    return f"sudo desktopper daemon {action}"


def cmd_start(cfg) -> int:
    if port_open(cfg.bind, cfg.port):
        print(f"Desktopper is already running at {_url(cfg)}")
        return 0
    if daemon_installed():
        if os.geteuid() != 0:
            print(
                "LaunchDaemon is installed. Start it with:\n  "
                + _sudo_hint("start"),
                file=sys.stderr,
            )
            return 1
        proc = _launchctl("kickstart", _service())
        if proc.returncode != 0:
            print(f"launchctl kickstart failed: {proc.stderr.strip()}", file=sys.stderr)
            return 1
        how = f"LaunchDaemon {LABEL}"
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
        _pidfile(cfg.appdir).write_text(f"{proc.pid}\n", encoding="utf-8")
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
    # Prefer signaling the process: LaunchDaemon runs as the installing user, so
    # that user can SIGTERM without root even when launchctl system needs sudo.
    pid = agent_pid()
    if pid is None:
        pid = _read_pid(cfg.appdir)
    if pid is not None:
        try:
            os.kill(pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
        except PermissionError:
            print(
                "Cannot signal the Desktopper process. Try:\n  " + _sudo_hint("stop"),
                file=sys.stderr,
            )
            return 1
        if not _wait(lambda: not _pid_alive(pid), STOP_TIMEOUT):
            try:
                os.kill(pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
        _pidfile(cfg.appdir).unlink(missing_ok=True)
        stopped = True
    elif agent_loaded():
        if os.geteuid() != 0:
            print(
                "LaunchDaemon is loaded. Stop it with:\n  " + _sudo_hint("stop"),
                file=sys.stderr,
            )
            return 1
        proc = _launchctl("kill", "SIGTERM", _service())
        stopped = proc.returncode == 0
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


def cmd_status(cfg) -> int:
    listening = port_open(cfg.bind, cfg.port)
    launch_pid = agent_pid()
    file_pid = _read_pid(cfg.appdir)
    pid = launch_pid if launch_pid is not None else file_pid
    managed = manager_of(cfg.appdir, pid) if pid is not None else None
    if managed is None and listening:
        managed = "other"
    installed = daemon_installed()
    loaded = agent_loaded() if sys.platform == "darwin" else False

    print(f"status:      {'running' if listening else 'stopped'}")
    print(f"url:         {_url(cfg)}")
    print(f"pid:         {pid if pid is not None else '—'}")
    print(f"managed_by:  {managed if managed else '—'}")
    print(f"installed:   {'yes' if installed else 'no'} ({plist_path()})")
    if sys.platform == "darwin":
        print(f"loaded:      {'yes' if loaded else 'no'} ({_service()})")
    print(f"appdir:      {cfg.appdir}")
    print(f"log:         {cfg.appdir / LOGFILE_NAME}")
    return 0


def cmd_install(cfg) -> int:
    # A pidfile-managed instance would hold the port and block the daemon process.
    pid = _read_pid(cfg.appdir)
    if pid is not None:
        rc = cmd_stop(cfg)
        if rc != 0:
            return rc
    try:
        username, uid, home = installer_identity()
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    _remove_legacy_agent(uid, home)
    path = plist_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    plist = build_plist(
        cfg.appdir,
        getattr(cfg, "cli_port", None),
        username=username,
        home=home,
    )
    with path.open("wb") as fh:
        plistlib.dump(plist, fh)
    if agent_loaded():
        # bootout first so launchd reads the refreshed plist.
        _launchctl("bootout", _service())
        _wait(lambda: not agent_loaded(), STOP_TIMEOUT)
        _wait(lambda: not port_open(cfg.bind, cfg.port), STOP_TIMEOUT)
    proc = _launchctl("bootstrap", _domain(), str(path))
    if proc.returncode != 0:
        print(f"launchctl bootstrap failed: {proc.stderr.strip()}", file=sys.stderr)
        return 1
    print(f"Installed LaunchDaemon {path} (runs as {username})")
    if not _wait(lambda: port_open(cfg.bind, cfg.port), START_TIMEOUT):
        print(
            f"LaunchDaemon loaded, but Desktopper is not listening on {_url(cfg)}. "
            f"See {cfg.appdir / LOGFILE_NAME}",
            file=sys.stderr,
        )
        return 1
    print(f"Desktopper started at {_url(cfg)}")
    return 0


def cmd_uninstall(cfg) -> int:
    try:
        _username, uid, home = installer_identity()
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    path = plist_path()
    loaded = agent_loaded()
    legacy = legacy_agent_plist(home)
    if not loaded and not path.exists() and not legacy.exists():
        print(f"LaunchDaemon {LABEL} is not installed. Nothing to do.")
        return 0
    if loaded:
        proc = _launchctl("bootout", _service())
        if proc.returncode != 0 and agent_loaded():
            print(f"launchctl bootout failed: {proc.stderr.strip()}", file=sys.stderr)
            return 1
        _wait(lambda: not port_open(cfg.bind, cfg.port), STOP_TIMEOUT)
    path.unlink(missing_ok=True)
    _remove_legacy_agent(uid, home)
    print(f"Uninstalled LaunchDaemon {LABEL}.")
    return 0


COMMANDS = {
    "start": (cmd_start, "Start the server in the background if it is not running."),
    "stop": (cmd_stop, "Stop the server started by `daemon start` or the LaunchDaemon."),
    "restart": (cmd_restart, "Stop, then start the server."),
    "status": (cmd_status, "Show whether the server is running, its pid, and LaunchDaemon state."),
    "install": (
        cmd_install,
        f"Install the system LaunchDaemon ({LABEL}), load it, and start the server. "
        "Requires sudo. Survives logout. Re-run to refresh the daemon.",
    ),
    "uninstall": (
        cmd_uninstall,
        "Unload and remove the LaunchDaemon (requires sudo), which stops its server. "
        "Does nothing if it is not installed.",
    ),
}


def add_parser(subparsers) -> None:
    daemon = subparsers.add_parser(
        "daemon",
        help="Run Desktopper as a background service (start, stop, restart, status, install, uninstall).",
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
        print("LaunchDaemons need macOS.", file=sys.stderr)
        return 1
    if args.action in ("install", "uninstall"):
        if os.geteuid() != 0:
            print(
                "LaunchDaemon install needs root. Re-run as:\n  "
                + _sudo_hint(args.action),
                file=sys.stderr,
            )
            return 1
        try:
            _username, _uid, home = installer_identity()
        except ValueError as exc:
            print(str(exc), file=sys.stderr)
            return 1
        # Under sudo, Path.home() is root's. Pin the real user's appdir first.
        if not os.environ.get("DESKTOPPER_APPDIR", "").strip():
            os.environ["DESKTOPPER_APPDIR"] = str(default_appdir_for_home(home))
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
