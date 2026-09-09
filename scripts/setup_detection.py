"""Explicitly create the detection/dashboard schema and activate its manifest."""

from __future__ import annotations

from argparse import ArgumentParser
from datetime import datetime, timezone
from pathlib import Path
import os
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from common.environment import load_environment_file
from database.migrations import SchemaError, connect, migrate_detection_dashboard, validate_detection_dashboard
from detection.configuration import load_manifest
from detection.store import DetectionStore


ROOT = Path(__file__).resolve().parents[1]


def _backup_legacy_database(path: Path) -> Path | None:
    raise RuntimeError("Unsafe DB/WAL file-moving rebuild is retired; use a new explicitly named --database path. Existing data is unchanged.")


def main() -> None:
    load_environment_file(ROOT / ".env")
    parser = ArgumentParser(description=__doc__)
    parser.add_argument(
        "--database",
        default=os.getenv("CONTENT_FACTORY_DB_PATH", str(ROOT / "data" / "content.db")),
    )
    parser.add_argument(
        "--manifest",
        default=str(ROOT / "config" / "releases" / "detection-dashboard-v1.json"),
    )
    parser.add_argument(
        "--rebuild",
        action="store_true",
        help="Retired unsafe reset flag; refuses without changing the database.",
    )
    args = parser.parse_args()
    database_path = Path(args.database).resolve()
    manifest_path = Path(args.manifest).resolve()
    print(f"Database: {database_path}")
    print(f"Manifest: {manifest_path}")
    manifest = load_manifest(manifest_path)
    if args.rebuild:
        raise SystemExit("--rebuild is retired. Use a new --database path; the existing DB/WAL/SHM are unchanged.")
    try:
        if database_path.is_file():
            connection = connect(database_path, read_only=True)
            try:
                version = int(connection.execute("PRAGMA user_version").fetchone()[0])
                if version in (1, 2, 3):
                    validate_detection_dashboard(connection)
            finally:
                connection.close()
        else:
            version = 0
        changed = False if version in (1, 2, 3) else migrate_detection_dashboard(database_path)
    except SchemaError as error:
        raise SystemExit(f"Setup refused: {error}\nUse a new --database path; never reset to resolve a schema mismatch.")
    with DetectionStore(database_path) as store:
        release_id = store.apply_manifest(manifest)
    print("Schema: " + ("created" if changed else "already current"))
    print(f"Active configuration release: {manifest['release_name']} (id={release_id})")


if __name__ == "__main__":
    main()
