"""Explicitly upgrade a supported Content Factory database without resetting it."""

from argparse import ArgumentParser
from pathlib import Path
import os
import sys


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from database.current import SchemaError, migrate_database  # noqa: E402


def main() -> None:
    parser = ArgumentParser(description=__doc__)
    parser.add_argument(
        "--database", default=os.getenv("CONTENT_FACTORY_DB_PATH", str(ROOT / "data" / "development.db"))
    )
    args = parser.parse_args()
    try:
        changed = migrate_database(args.database)
    except (OSError, SchemaError) as error:
        raise SystemExit(f"Migration refused: {error}") from error
    print("Migrated v7 timestamps to UTC-naive v8." if changed else "Database is already current.")


if __name__ == "__main__":
    main()
