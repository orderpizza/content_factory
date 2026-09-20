"""Run one due-source collection pass without evaluating the shortlist."""

from __future__ import annotations

from pathlib import Path
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[1]


def main() -> None:
    command = [
        sys.executable,
        str(ROOT / "scripts" / "run_detection.py"),
        "--skip-scout",
    ]
    command.extend(sys.argv[1:])
    raise SystemExit(subprocess.call(command, cwd=ROOT))


if __name__ == "__main__":
    main()
