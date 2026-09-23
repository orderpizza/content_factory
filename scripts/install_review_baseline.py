"""Install or inspect the local review-only Mac Mini launchd baseline.

This script never initializes a database, sends content, or stores secrets in a
LaunchAgent.  The normal workers load credentials from the repository's local
``.env`` file at their own startup.
"""

from __future__ import annotations

from argparse import ArgumentParser
from pathlib import Path
import os
import plistlib
import subprocess
import sys
import time


ROOT = Path(__file__).resolve().parents[1]
LABEL_PREFIX = "com.contentfactory.review"
VENV_ROOT = Path(sys.executable).absolute().parent.parent
VENV_SITE_PACKAGES = VENV_ROOT / "lib" / f"python{sys.version_info.major}.{sys.version_info.minor}" / "site-packages"


def _absolute(path: str) -> Path:
    return Path(path).expanduser().resolve()


def _agent(
    *,
    name: str,
    arguments: list[str],
    log_root: Path,
    keep_alive: bool = False,
    schedule: dict[str, int] | None = None,
) -> dict[str, object]:
    label = f"{LABEL_PREFIX}.{name}"
    agent: dict[str, object] = {
        "Label": label,
        "ProgramArguments": arguments,
        "WorkingDirectory": str(ROOT),
        "EnvironmentVariables": {
            # launchd can resolve a macOS framework-Python venv symlink before
            # Python reads pyvenv.cfg. Keep the pinned venv packages explicit
            # for that launcher path as well as the project source tree.
            "PYTHONPATH": os.pathsep.join((str(ROOT / "src"), str(VENV_SITE_PACKAGES))),
            "VIRTUAL_ENV": str(VENV_ROOT),
            "PATH": os.pathsep.join((str(VENV_ROOT / "bin"), "/usr/bin", "/bin", "/usr/sbin", "/sbin")),
            "CONTENT_FACTORY_LOG_ROOT": str(log_root),
        },
        "ProcessType": "Background",
        "ThrottleInterval": 15,
        "StandardOutPath": str(log_root / f"{name}.stdout.log"),
        "StandardErrorPath": str(log_root / f"{name}.stderr.log"),
    }
    if keep_alive:
        agent["KeepAlive"] = True
    if schedule is not None:
        agent["StartCalendarInterval"] = schedule
    return agent


def build_agents(
    *,
    database: Path,
    artifacts: Path,
    backups: Path,
    log_root: Path,
    port: int,
    backup_hour: int,
    backup_minute: int,
) -> dict[str, dict[str, object]]:
    """Return the closed five-process review baseline as launchd plists."""
    # Preserve the venv launcher path. Resolving it follows its Python-framework
    # symlink and silently drops the virtual environment's installed packages.
    python = str(Path(sys.executable).absolute())
    common = ["--database", str(database)]
    return {
        "detection": _agent(
            name="detection",
            arguments=[
                python, str(ROOT / "scripts" / "run_detection.py"), *common,
                "--poll", "--poll-interval", "30",
            ],
            log_root=log_root,
            keep_alive=True,
        ),
        "workflow": _agent(
            name="workflow",
            arguments=[
                python, str(ROOT / "scripts" / "run_workflow.py"), *common,
                "--artifacts", str(artifacts), "--backups", str(backups),
                "--gemini", "--review-preview", "--poll", "--poll-interval", "5",
            ],
            log_root=log_root,
            keep_alive=True,
        ),
        "dashboard": _agent(
            name="dashboard",
            arguments=[
                python, str(ROOT / "scripts" / "serve_dashboard.py"), *common,
                "--artifacts", str(artifacts), "--host", "127.0.0.1", "--port", str(port),
            ],
            log_root=log_root,
            keep_alive=True,
        ),
        "storage": _agent(
            name="storage",
            arguments=[
                python, str(ROOT / "scripts" / "run_storage_monitor.py"), *common,
                "--artifacts", str(artifacts), "--backups", str(backups),
                "--poll", "--poll-interval", "60",
            ],
            log_root=log_root,
            keep_alive=True,
        ),
        "backup": _agent(
            name="backup",
            arguments=[
                python, str(ROOT / "scripts" / "run_maintenance.py"), *common,
                "--artifacts", str(artifacts), "--backups", str(backups), "--restore-verify",
            ],
            log_root=log_root,
            schedule={"Hour": backup_hour, "Minute": backup_minute},
        ),
    }


def write_agents(agents: dict[str, dict[str, object]], destination: Path) -> list[Path]:
    """Atomically write each agent definition and return its final plist path."""
    destination.mkdir(parents=True, exist_ok=True)
    paths: list[Path] = []
    for name, payload in agents.items():
        path = destination / f"{LABEL_PREFIX}.{name}.plist"
        temporary = path.with_suffix(".plist.tmp")
        with temporary.open("wb") as output:
            plistlib.dump(payload, output, sort_keys=False)
        temporary.replace(path)
        paths.append(path)
    return paths


def _domain() -> str:
    return f"gui/{os.getuid()}"


def load_agents(paths: list[Path]) -> None:
    """Replace only this baseline's matching LaunchAgents with written files."""
    domain = _domain()
    for path in paths:
        # A service-target can leave a kept-alive old process racing the new
        # bootstrap. Passing the exact plist tells launchd to retire that file's
        # existing registration before loading its replacement.
        subprocess.run(["launchctl", "bootout", domain, str(path)], check=False, capture_output=True, text=True)
        time.sleep(0.25)
        result = subprocess.run(
            ["launchctl", "bootstrap", domain, str(path)], check=False,
            capture_output=True, text=True,
        )
        if result.returncode:
            detail = (result.stderr or result.stdout).strip() or f"exit {result.returncode}"
            raise RuntimeError(f"could not load {path.name}: {detail}")


def status_agents() -> int:
    """Print the launchd status of all baseline labels; nonzero means one is absent."""
    domain = _domain()
    healthy = True
    for name in ("detection", "workflow", "dashboard", "storage", "backup"):
        label = f"{LABEL_PREFIX}.{name}"
        result = subprocess.run(
            ["launchctl", "print", f"{domain}/{label}"],
            check=False, capture_output=True, text=True,
        )
        state = "loaded" if result.returncode == 0 else "not loaded"
        print(f"{label}: {state}")
        healthy = healthy and result.returncode == 0
    return 0 if healthy else 1


def main() -> None:
    parser = ArgumentParser(description=__doc__)
    action = parser.add_mutually_exclusive_group(required=True)
    action.add_argument("--install", action="store_true", help="write and load the five review LaunchAgents")
    action.add_argument("--write-only", action="store_true", help="write the five plists without loading them")
    action.add_argument("--status", action="store_true", help="report whether every review LaunchAgent is loaded")
    parser.add_argument("--database", help="existing current-schema database shared by every service")
    parser.add_argument("--artifacts", help="shared review-artifact directory")
    parser.add_argument("--backups", help="shared verified-backup directory")
    parser.add_argument("--log-root", default=str(ROOT / "data" / "logs" / "review-baseline"))
    parser.add_argument("--launch-agent-dir", default=str(Path.home() / "Library" / "LaunchAgents"))
    parser.add_argument("--port", type=int, default=8787)
    parser.add_argument("--backup-hour", type=int, default=3)
    parser.add_argument("--backup-minute", type=int, default=15)
    args = parser.parse_args()
    if args.status:
        raise SystemExit(status_agents())
    if not args.database or not args.artifacts or not args.backups:
        parser.error("--database, --artifacts and --backups are required when writing agents")
    if not 1 <= args.port <= 65535:
        parser.error("--port must be between 1 and 65535")
    if not 0 <= args.backup_hour <= 23 or not 0 <= args.backup_minute <= 59:
        parser.error("backup hour/minute must be a valid local clock time")
    database, artifacts, backups, log_root = (
        _absolute(args.database), _absolute(args.artifacts), _absolute(args.backups), _absolute(args.log_root)
    )
    if not database.is_file():
        parser.error(f"database must already exist; setup is explicit: {database}")
    log_root.mkdir(parents=True, exist_ok=True)
    agents = build_agents(
        database=database, artifacts=artifacts, backups=backups, log_root=log_root,
        port=args.port, backup_hour=args.backup_hour, backup_minute=args.backup_minute,
    )
    paths = write_agents(agents, _absolute(args.launch_agent_dir))
    if args.install:
        try:
            load_agents(paths)
        except (OSError, subprocess.CalledProcessError) as error:
            raise SystemExit(f"LaunchAgent install failed: {error}") from error
        print("Review baseline loaded: " + ", ".join(path.stem for path in paths))
    else:
        print("Review baseline plists written: " + ", ".join(str(path) for path in paths))


if __name__ == "__main__":
    main()
