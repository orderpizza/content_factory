"""Explicitly create the detection/dashboard schema and activate its manifest."""

from __future__ import annotations

from argparse import ArgumentParser
from datetime import datetime, timezone
from pathlib import Path
import os
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from common.environment import load_environment_file
from database.migrations import SchemaError, migrate_detection_dashboard
from detection.configuration import load_manifest
from detection.store import DetectionStore


ROOT = Path(__file__).resolve().parents[1]


def _backup_legacy_database(path: Path) -> Path | None:
    if not path.exists():
        return None
    if not path.is_file():
        raise RuntimeError(f"Database path is not a regular file: {path}")
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    backup = path.with_name(f"{path.name}.legacy-{stamp}.bak")
    path.replace(backup)
    for suffix in ("-wal", "-shm"):
        sidecar = Path(str(path) + suffix)
        if sidecar.is_file():
            sidecar.replace(Path(str(backup) + suffix))
    return backup


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
        help="Move an existing development database to a timestamped backup before setup.",
    )
    args = parser.parse_args()
    database_path = Path(args.database).resolve()
    manifest_path = Path(args.manifest).resolve()
    print(f"Database: {database_path}")
    print(f"Manifest: {manifest_path}")
    if args.rebuild:
        backup = _backup_legacy_database(database_path)
        if backup:
            print(f"Legacy database moved to: {backup}")
    try:
        changed = migrate_detection_dashboard(database_path)
    except SchemaError as error:
        raise SystemExit(f"Setup refused: {error}\nUse --rebuild only for an intentionally disposable development database.")
    manifest = load_manifest(manifest_path)
    with DetectionStore(database_path) as store:
        release_id = store.apply_manifest(manifest)
    print("Schema: " + ("created" if changed else "already current"))
    print(f"Active configuration release: {manifest['release_name']} (id={release_id})")


if __name__ == "__main__":
    main()
