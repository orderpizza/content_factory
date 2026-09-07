"""Run one due-source collection pass without evaluating the shortlist."""

from __future__ import annotations

from pathlib import Path
import os
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[1]


def main() -> None:
    command = [
        sys.executable,
        str(ROOT / "scripts" / "run_detection.py"),
        "--skip-scout",
    ]
    database = os.getenv("CONTENT_FACTORY_DB_PATH")
    if database:
        command.extend(["--database", database])
    raise SystemExit(subprocess.call(command, cwd=ROOT))


if __name__ == "__main__":
    main()
