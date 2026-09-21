"""Storage sampling and verified SQLite online backups for workflow v4."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from hashlib import sha256
from pathlib import Path
from typing import Any
import fcntl
import json
import os
import shutil
import sqlite3
import tempfile
from common.operation_log import emit
from .storage_growth import measure_tables

from database.current import connect, validate_database

from .store import WorkflowStore, canonical, now


def _tree_bytes(root: Path) -> int:
    if not root.exists():
        return 0
    if root.is_file():
        return root.stat().st_size
    total = 0
    for path in root.rglob("*"):
        try:
            if path.is_file() and not path.is_symlink():
                total += path.stat().st_size
        except OSError:
            continue
    return total


class StorageMonitor:
    """Persist storage facts; only downstream production consults admission."""

    def __init__(
        self,
        store: WorkflowStore,
        artifact_root: str | Path,
        backup_root: str | Path,
    ):
        self.store = store
        self.artifact_root = Path(artifact_root).resolve()
        self.backup_root = Path(backup_root).resolve()

    def run_once(self) -> int:
        latest = self.store.connection.execute(
            "SELECT storage_sample_id,sampled_at FROM storage_samples ORDER BY storage_sample_id DESC LIMIT 1"
        ).fetchone()
        moment = datetime.now(timezone.utc).replace(microsecond=0)
        if latest is not None:
            try:
                age = (moment-datetime.fromisoformat(latest['sampled_at'])).total_seconds()
                if 0 <= age < 300:
                    return int(latest['storage_sample_id'])
            except (TypeError, ValueError):
                pass
        usage = shutil.disk_usage(self.store.path.parent)
        ratio = usage.free / usage.total
        if ratio < 0.03 or usage.free < 1 * 1024**3:
            raw = "read_only_emergency"
        elif ratio < 0.08 or usage.free < 5 * 1024**3:
            raw = "storage_critical"
        elif ratio < 0.15 or usage.free < 10 * 1024**3:
            raw = "storage_warning"
        else:
            raw = "normal"
        previous = self.store.connection.execute(
            "SELECT state,summary_json FROM storage_samples ORDER BY storage_sample_id DESC LIMIT 2"
        ).fetchall()
        state = raw
        if raw == "normal" and previous and previous[0]["state"] != "normal":
            prior_raw = json.loads(previous[0]["summary_json"]).get("raw_state")
            if prior_raw != "normal":
                state = previous[0]["state"]
        wal = Path(str(self.store.path) + "-wal")
        summary = {"policy": "storage_safety_v1", "raw_state": raw,
                   "free_ratio": round(ratio, 6), "artifact_root": str(self.artifact_root),
                   "backup_root": str(self.backup_root)}
        day = moment.date().isoformat()
        measured = self.store.connection.execute(
            "SELECT 1 FROM storage_samples WHERE sampled_at>=? AND sampled_at<=? "
            "AND json_type(summary_json,'$.growth')='object' LIMIT 1", (day,moment.isoformat()),
        ).fetchone()
        if not measured:
            summary['growth'] = measure_tables(self.store.connection)
        with self.store.transaction():
            # Multiple local pollers may sample; fence the append after sampling.
            latest = self.store.connection.execute('SELECT storage_sample_id,sampled_at FROM storage_samples ORDER BY storage_sample_id DESC LIMIT 1').fetchone()
            if latest and latest['sampled_at'] >= (moment-timedelta(minutes=5)).isoformat() and latest['sampled_at'] <= moment.isoformat():
                return int(latest['storage_sample_id'])
            sample_id = int(self.store.connection.execute(
                "INSERT INTO storage_samples(state,free_bytes,total_bytes,database_bytes,wal_bytes,"
                "artifact_bytes,backup_bytes,summary_json,sampled_at) VALUES (?,?,?,?,?,?,?,?,?)",
                (state, usage.free, usage.total, self.store.path.stat().st_size,
                 wal.stat().st_size if wal.exists() else 0, _tree_bytes(self.artifact_root),
                 _tree_bytes(self.backup_root), canonical(summary), moment.isoformat()),
            ).lastrowid)
        emit('storage', 'sample', sample_id=sample_id, status=state,
             table_count=len(summary.get('growth', {}).get('tables', {})))
        return sample_id


class MaintenanceService:
    """Run auditable backup/checkpoint/restore verification under one lock."""

    def __init__(self, store: WorkflowStore, backup_root: str | Path):
        self.store = store
        self.backup_root = Path(backup_root).resolve()
        self.backup_root.mkdir(parents=True, exist_ok=True)
        self._lock_handle: Any | None = None

    def acquire(self) -> bool:
        lock = self.backup_root / ".content-factory-maintenance.lock"
        self._lock_handle = lock.open("a+")
        try:
            fcntl.flock(self._lock_handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            return True
        except BlockingIOError:
            return False

    def close(self) -> None:
        if self._lock_handle is not None:
            self._lock_handle.close()
            self._lock_handle = None

    def backup(self) -> Path:
        started = now()
        run_id = self._start("sqlite_backup", started)
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
        final = self.backup_root / f"content-factory-{timestamp}.db"
        temporary = self.backup_root / f".{final.name}.partial"
        try:
            destination = sqlite3.connect(temporary)
            try:
                self.store.connection.backup(destination)
            finally:
                destination.close()
            hasher = sha256()
            with temporary.open("rb") as handle:
                for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                    hasher.update(chunk)
            checksum = hasher.hexdigest()
            check = connect(temporary, read_only=True)
            try:
                if check.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                    raise RuntimeError("backup integrity_check failed")
                validate_database(check)
            finally:
                check.close()
            with temporary.open("rb") as handle:
                os.fsync(handle.fileno())
            os.replace(temporary, final)
            _fsync_directory(self.backup_root)
            self._finish(run_id, "succeeded", {"bytes": final.stat().st_size},
                         backup_path=str(final), checksum=checksum)
            return final
        except Exception as error:
            if temporary.exists():
                temporary.unlink()
            self._finish(run_id, "failed", {}, failure=type(error).__name__)
            raise

    def checkpoint(self) -> tuple[int, int, int]:
        run_id = self._start("wal_checkpoint", now())
        try:
            result = tuple(int(value) for value in self.store.connection.execute(
                "PRAGMA wal_checkpoint(PASSIVE)"
            ).fetchone())
            active = sum(int(self.store.connection.execute(
                f"SELECT COUNT(*) FROM {table} WHERE status IN ('claimed','running','publishing')"
            ).fetchone()[0]) for table in (
                "intake_requests", "determination_requests", "generation_runs", "adaptation_runs", "visual_plan_runs",
                "render_runs", "post_records", "delivery_cleanup_tasks", "reconciliation_requests",
            ))
            truncated = False
            if result[0] == 0 and active == 0:
                truncate = tuple(int(value) for value in self.store.connection.execute(
                    "PRAGMA wal_checkpoint(TRUNCATE)"
                ).fetchone())
                truncated = truncate[0] == 0
            self._finish(run_id, "succeeded", {"passive": result, "active_claims": active,
                                                "truncate_requested": truncated})
            return result
        except Exception as error:
            self._finish(run_id, "failed", {}, failure=type(error).__name__)
            raise

    def verify_restore(self, backup: Path | None = None) -> int:
        run_id = self._start("restore_verify", now())
        try:
            source = backup or self.newest_backup()
            if source is None:
                raise RuntimeError("no completed backup exists")
            ledger = self.store.connection.execute(
                "SELECT checksum FROM maintenance_runs WHERE kind='sqlite_backup' "
                "AND status='succeeded' AND backup_path=? ORDER BY maintenance_run_id DESC LIMIT 1",
                (str(source),),
            ).fetchone()
            if ledger is None or _file_sha256(source) != ledger["checksum"]:
                raise RuntimeError("backup does not match a completed audited checksum")
            with tempfile.TemporaryDirectory(prefix="content-factory-restore-") as directory:
                restored = Path(directory) / "restored.db"
                original = sqlite3.connect(f"file:{source.resolve()}?mode=ro", uri=True)
                target = sqlite3.connect(restored)
                try:
                    original.backup(target)
                finally:
                    original.close()
                    target.close()
                check = connect(restored, read_only=True)
                try:
                    if check.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                        raise RuntimeError("restored backup integrity_check failed")
                    validate_database(check)
                    trace = {
                        "threads": int(check.execute("SELECT COUNT(*) FROM content_threads").fetchone()[0]),
                        "posts": int(check.execute("SELECT COUNT(*) FROM post_records").fetchone()[0]),
                        "migrations": int(check.execute("SELECT COUNT(*) FROM schema_migrations").fetchone()[0]),
                    }
                finally:
                    check.close()
            self._finish(run_id, "succeeded", {"source": str(source), "trace": trace})
            return run_id
        except Exception as error:
            self._finish(run_id, "failed", {}, failure=type(error).__name__)
            raise

    def prune_backups(self) -> list[Path]:
        """Keep newest 14 snapshots plus eight older weekly representatives."""
        run_id = self._start("backup_retention", now())
        try:
            rows = self.store.connection.execute(
                "SELECT backup_path,checksum FROM maintenance_runs WHERE kind='sqlite_backup' "
                "AND status='succeeded' AND backup_path IS NOT NULL AND checksum IS NOT NULL"
            ).fetchall()
            audited = {
                Path(row["backup_path"]).resolve(): row["checksum"] for row in rows
            }
            snapshots = []
            for path in sorted(self.backup_root.glob("content-factory-*.db"), reverse=True):
                resolved = path.resolve()
                if (
                    resolved.parent == self.backup_root and not path.is_symlink()
                    and audited.get(resolved) == _file_sha256(path)
                ):
                    snapshots.append(path)
            keep = set(snapshots[:14])
            weeks: set[tuple[int, int]] = set()
            for path in snapshots[14:]:
                stamp = path.stem.removeprefix("content-factory-")
                try:
                    day = datetime.strptime(stamp, "%Y%m%dT%H%M%S%fZ").date()
                except ValueError:
                    continue
                key = day.isocalendar()[:2]
                if key not in weeks and len(weeks) < 8:
                    weeks.add(key)
                    keep.add(path)
            removed = []
            for path in snapshots:
                if path not in keep:
                    path.unlink()
                    removed.append(path)
            if removed:
                _fsync_directory(self.backup_root)
            self._finish(run_id, "succeeded", {
                "verified_candidates": len(snapshots),
                "removed": [path.name for path in removed],
                "untracked_files_ignored": len(list(self.backup_root.glob("content-factory-*.db")))
                    - len([path for path in snapshots if path.exists()]),
            })
            return removed
        except Exception as error:
            self._finish(run_id, "failed", {}, failure=type(error).__name__)
            raise

    def newest_backup(self) -> Path | None:
        candidates = sorted(self.backup_root.glob("content-factory-*.db"), reverse=True)
        return candidates[0] if candidates else None

    def _start(self, kind: str, started: str) -> int:
        with self.store.transaction():
            return int(self.store.connection.execute(
                "INSERT INTO maintenance_runs(kind,status,summary_json,started_at) "
                "VALUES (?,'running','{}',?)", (kind, started),
            ).lastrowid)

    def _finish(
        self,
        run_id: int,
        status: str,
        summary: dict[str, Any],
        *,
        backup_path: str | None = None,
        checksum: str | None = None,
        failure: str | None = None,
    ) -> None:
        with self.store.transaction():
            self.store.connection.execute(
                "UPDATE maintenance_runs SET status=?,backup_path=?,checksum=?,summary_json=?,"
                "failure_reason=?,completed_at=? WHERE maintenance_run_id=?",
                (status, backup_path, checksum, canonical(summary), failure, now(), run_id),
            )


def _fsync_directory(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _file_sha256(path: Path) -> str:
    hasher = sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            hasher.update(chunk)
    return hasher.hexdigest()
