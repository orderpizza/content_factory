"""Selection rules for operator-managed primary SQLite databases."""

from __future__ import annotations

from argparse import ArgumentParser
from datetime import datetime, timezone
from pathlib import Path
import re
import time


_NAME = re.compile(r"^db_(\d{14})\.db$")
_FORMAT = "%Y%m%d%H%M%S"


def new_primary_database_path(directory: str | Path) -> Path:
    """Return an unused path stamped with its UTC creation second."""
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    while True:
        now = datetime.now(timezone.utc)
        stamp = now.strftime(_FORMAT)
        path = directory / f"db_{stamp}.db"
        if not path.exists():
            return path
        # A second-resolution name may already have been created this second.
        time.sleep(max(0.01, 1 - now.microsecond / 1_000_000))


def latest_primary_database_path(directory: str | Path) -> Path:
    """Return the primary database with the newest UTC timestamp in its name."""
    directory = Path(directory)
    matches: list[tuple[str, Path]] = []
    for path in directory.iterdir() if directory.is_dir() else ():
        match = _NAME.fullmatch(path.name)
        if match is None or not path.is_file():
            continue
        stamp = match.group(1)
        try:
            datetime.strptime(stamp, _FORMAT)
        except ValueError:
            continue
        matches.append((stamp, path.resolve()))
    if not matches:
        raise FileNotFoundError(
            f"No primary database matching db_{'YYYYMMDDHHMMSS'}.db in {directory}; "
            "create one with .venv/bin/python scripts/setup_development.py"
        )
    return max(matches, key=lambda item: item[0])[1]


def resolve_primary_database_argument(parser: ArgumentParser, directory: str | Path) -> Path:
    """Select the newest primary DB or report a setup hint via argparse."""
    try:
        return latest_primary_database_path(directory)
    except FileNotFoundError as error:
        parser.error(str(error))
