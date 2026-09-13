"""Run v4 storage sampling and verified SQLite maintenance operations."""

from argparse import ArgumentParser
from datetime import datetime
from pathlib import Path
import os
import sqlite3
import sys
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from common.environment import load_environment_file
from database.migrations import SchemaError, validate_production_workflow
from workflow import WorkflowStore
from workflow.maintenance import MaintenanceService, StorageMonitor


def main() -> None:
    load_environment_file(ROOT / ".env")
    parser = ArgumentParser(description=__doc__)
    parser.add_argument("--database", default=os.getenv(
        "CONTENT_FACTORY_DB_PATH", str(ROOT / "data" / "content.db")
    ))
    parser.add_argument("--artifacts", default=os.getenv(
        "CONTENT_FACTORY_ARTIFACT_ROOT", str(ROOT / "data" / "artifacts")
    ))
    parser.add_argument("--backups", default=os.getenv("CONTENT_FACTORY_BACKUP_ROOT"))
    parser.add_argument("--restore-verify", action="store_true")
    parser.add_argument("--prune-backups", action="store_true")
    args = parser.parse_args()
    if not args.backups:
        parser.error("--backups or CONTENT_FACTORY_BACKUP_ROOT is required")
    try:
        with WorkflowStore(args.database) as store:
            validate_production_workflow(store.connection)
            store.heartbeat(
                "maintenance", "maintenance-v1", "polling", "maintenance pass started"
            )
            try:
                service = MaintenanceService(store, args.backups)
                if not service.acquire():
                    with store.transaction():
                        store.connection.execute(
                            "INSERT INTO maintenance_runs(kind,status,summary_json,started_at,completed_at) "
                            "VALUES ('sqlite_backup','skipped_overlap','{}',datetime('now'),datetime('now'))"
                        )
                    store.heartbeat(
                        "maintenance", "maintenance-v1", "idle",
                        "maintenance skipped because another process owns the lock",
                    )
                    service.close()
                    print("Maintenance skipped: another process owns the lock.")
                    return
                try:
                    backup = service.backup()
                    service.checkpoint()
                    if args.prune_backups:
                        removed = service.prune_backups()
                        print(f"Pruned {len(removed)} surplus verified backup(s).")
                    today = datetime.now(ZoneInfo("Asia/Seoul")).date()
                    if args.restore_verify or (today.day <= 7 and today.weekday() == 6):
                        service.verify_restore(backup)
                    StorageMonitor(store, args.artifacts, args.backups).run_once()
                finally:
                    service.close()
            except Exception as error:
                store.heartbeat(
                    "maintenance", "maintenance-v1", "failed",
                    f"maintenance pass failed ({type(error).__name__})",
                )
                raise
            store.heartbeat(
                "maintenance", "maintenance-v1", "completed",
                "verified backup and storage sample completed",
            )
    except (OSError, SchemaError, RuntimeError, sqlite3.Error) as error:
        raise SystemExit(f"Maintenance failed: {error}")
    print(f"Verified online backup: {backup}")


if __name__ == "__main__":
    main()
