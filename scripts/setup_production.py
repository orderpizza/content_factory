"""Explicitly migrate a normalized workflow database to production schema v4."""

from __future__ import annotations

from argparse import ArgumentParser
from pathlib import Path
import os
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from common.environment import load_environment_file
from database.migrations import SchemaError, migrate_production_workflow


def main() -> None:
    load_environment_file(ROOT / ".env")
    parser = ArgumentParser(description=__doc__)
    parser.add_argument(
        "--database",
        default=os.getenv("CONTENT_FACTORY_DB_PATH", str(ROOT / "data" / "content.db")),
    )
    args = parser.parse_args()
    try:
        changed = migrate_production_workflow(Path(args.database))
    except SchemaError as error:
        raise SystemExit(f"Production setup refused: {error}")
    print("Production schema: " + ("migrated to v4" if changed else "already current"))


if __name__ == "__main__":
    main()
