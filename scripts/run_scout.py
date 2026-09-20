"""Run one Scout evaluation against persisted collection evidence.

Delegates to the current Detection entrypoint with collection disabled.
CLI arguments, including --database and --poll, are forwarded unchanged.
"""

from __future__ import annotations

from pathlib import Path
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[1]


def main() -> None:
    command = [
        sys.executable,
        str(ROOT / "scripts" / "run_detection.py"),
        "--skip-collection",
    ]
    command.extend(sys.argv[1:])
    raise SystemExit(subprocess.call(command, cwd=ROOT))


if __name__ == "__main__":
    main()
