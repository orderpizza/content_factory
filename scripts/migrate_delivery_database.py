"""Validate or explicitly migrate a stopped operator database from v18 to v19."""
import argparse
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from database.migrate_delivery import migrate


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", type=Path, required=True)
    parser.add_argument("--apply", action="store_true", help="default is read-only dry run")
    parser.add_argument("--writers-stopped", action="store_true")
    parser.add_argument("--backup", type=Path)
    args = parser.parse_args()
    if args.apply and not args.writers_stopped:
        parser.error("--apply requires --writers-stopped and an unused --backup path")
    print(migrate(args.database, apply=args.apply, backup=args.backup))


if __name__ == "__main__":
    main()
