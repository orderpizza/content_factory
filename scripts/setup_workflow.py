"""Explicitly extend a validated v1 detection database to workflow schema v2."""

from __future__ import annotations

from argparse import ArgumentParser
from pathlib import Path
import os
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from common.environment import load_environment_file
from database.migrations import SchemaError, migrate_editorial_workflow

ROOT = Path(__file__).resolve().parents[1]


def main() -> None:
    load_environment_file(ROOT / ".env")
    parser = ArgumentParser(description=__doc__)
    parser.add_argument("--database", default=os.getenv("CONTENT_FACTORY_DB_PATH", str(ROOT / "data" / "content.db")))
    args = parser.parse_args()
    try:
        changed = migrate_editorial_workflow(Path(args.database))
    except SchemaError as error:
        raise SystemExit(f"Workflow setup refused: {error}")
    print("Workflow schema: " + ("migrated to v2" if changed else "already current"))


if __name__ == "__main__":
    main()
