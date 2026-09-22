"""Storage and maintenance; offline tests use temporary databases and fake providers."""

from __future__ import annotations
from common.storage import storage_status
from common.timestamps import serialize_timestamp
from dashboard.evidence import render_storage_growth, render_storage_status
from database.current import initialize_database
from datetime import datetime, timedelta, timezone
from detection.configuration import load_manifest
from detection.store import DetectionStore
from pathlib import Path
from workflow import WorkflowStore
from workflow.development import prepare_development_database
from workflow.maintenance import MaintenanceService, StorageMonitor
from workflow.storage_growth import measure_tables
from workflow.store import canonical, now
import json
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]


class StorageObservationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name)/'test.db'
        prepare_development_database(self.path)

    def test_stale_normal_sample_is_not_disk_pressure_and_recovery_is_model_free(self):
        with WorkflowStore(self.path, enforce_storage=True) as store:
            old = serialize_timestamp(datetime.now(timezone.utc)-timedelta(hours=4))
            store.connection.execute('UPDATE storage_samples SET sampled_at=?', (old,))
            store.connection.commit()
            self.assertEqual(storage_status(store.connection)['reason'], 'stale_sample')
            store.create_human_idea('Valid human idea', command_id='stale-accepted')
            self.assertEqual(store.connection.execute('SELECT COUNT(*) FROM intake_requests').fetchone()[0], 1)
            html = render_storage_status(store.connection)
            self.assertIn('does not mean the disk is full', html)
            self.assertIn('run_storage_monitor.py', html)
            StorageMonitor(store, self.temp.name, self.temp.name).run_once()
            store.create_human_idea('Valid human idea', command_id='accepted')
            self.assertEqual(store.connection.execute('SELECT COUNT(*) FROM model_invocations').fetchone()[0], 0)

    def test_future_sample_does_not_remain_cached_and_critical_is_advisory_for_planning(self):
        with WorkflowStore(self.path, enforce_storage=True) as store:
            future = serialize_timestamp(datetime.now(timezone.utc)+timedelta(days=1))
            store.connection.execute('UPDATE storage_samples SET sampled_at=?', (future,))
            store.connection.commit()
            self.assertEqual(storage_status(store.connection)['reason'], 'invalid_sample_time')
            StorageMonitor(store,self.temp.name,self.temp.name).run_once()
            self.assertEqual(storage_status(store.connection)['reason'], 'normal')
            store.connection.execute("UPDATE storage_samples SET state='storage_critical'")
            store.connection.commit()
            store.create_human_idea('Valid human idea', command_id='critical')
            self.assertFalse(store._storage_action_allowed('model'))

    def test_daily_growth_is_numeric_only_and_does_not_change_lineage(self):
        with WorkflowStore(self.path) as store:
            store.create_human_idea('PRIVATE_PAYLOAD_한글', command_id='secret')
            before = store.connection.total_changes
            report = measure_tables(store.connection)
            self.assertEqual(store.connection.total_changes,before)
            self.assertTrue(report['complete'])
            self.assertEqual(report['tables']['content_threads']['rows'], 1)
            self.assertGreater(report['tables']['intake_requests']['json_bytes']['context_json'],0)
            self.assertNotIn('PRIVATE_PAYLOAD', json.dumps(report))
            samples = store.connection.execute('SELECT COUNT(*) FROM storage_samples').fetchone()[0]
            monitor = StorageMonitor(store,self.temp.name,self.temp.name)
            monitor.run_once(); monitor.run_once()
            self.assertEqual(store.connection.execute('SELECT COUNT(*) FROM storage_samples').fetchone()[0], samples)
            self.assertIn('No database rows are deleted', render_storage_growth(store.connection))

    def test_measurement_timeout_leaves_connection_usable(self):
        with WorkflowStore(self.path) as store:
            for n in range(100):
                store.create_human_idea('measurement sample '+str(n),command_id=str(n))
            report = measure_tables(store.connection,max_seconds=0)
            self.assertFalse(report['complete'])
            self.assertEqual(store.connection.execute('SELECT COUNT(*) FROM content_threads').fetchone()[0],100)
            store.create_human_idea('works after timeout', command_id='later')


MANIFEST = ROOT / "config" / "releases" / "detection.json"


class StorageMaintenanceTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.path = Path(self.temporary.name) / "development.db"
        initialize_database(self.path)
        with DetectionStore(self.path) as store:
            store.apply_manifest(load_manifest(MANIFEST))

    def test_storage_state_only_gates_downstream_work(self):
        with WorkflowStore(self.path, enforce_storage=True) as store:
            store.create_human_idea("Planning is allowed.", command_id="missing-storage")
            self.assertFalse(store._storage_action_allowed('model'))
            with store.transaction():
                store.connection.execute(
                    "INSERT INTO storage_samples(state,free_bytes,total_bytes,database_bytes,wal_bytes,"
                    "artifact_bytes,backup_bytes,summary_json,sampled_at) "
                    "VALUES ('storage_warning',10,100,1,0,0,0,?,?)",
                    (canonical({"raw_state": "storage_warning"}), now()),
                )
            request_id = store.create_human_idea(
                "This human idea can wait under warning.", command_id="warning-storage",
            )
            self.assertIsNotNone(store.claim("intake_requests", "intake_request_id", "worker"))
            self.assertFalse(store._storage_action_allowed('model'))
            self.assertEqual(store.connection.execute(
                "SELECT status FROM intake_requests WHERE intake_request_id=?", (request_id,),
            ).fetchone()[0], "pending")

    def test_storage_sample_and_online_backup_restore_are_audited(self):
        backup_root = Path(self.temporary.name) / "backups"
        artifact_root = Path(self.temporary.name) / "artifacts"
        artifact_root.mkdir()
        with WorkflowStore(self.path) as store:
            sample_id = StorageMonitor(store, artifact_root, backup_root).run_once()
            self.assertGreater(sample_id, 0)
            service = MaintenanceService(store, backup_root)
            self.assertTrue(service.acquire())
            try:
                backup = service.backup()
                self.assertTrue(backup.is_file())
                service.checkpoint()
                service.verify_restore(backup)
            finally:
                service.close()
            statuses = store.connection.execute(
                "SELECT kind,status FROM maintenance_runs ORDER BY maintenance_run_id"
            ).fetchall()
            self.assertEqual([(row["kind"], row["status"]) for row in statuses], [
                ("sqlite_backup", "succeeded"), ("wal_checkpoint", "succeeded"),
                ("restore_verify", "succeeded"),
            ])


class MaintenanceTimestampTests(unittest.TestCase):
    def test_overlap_records_use_canonical_timestamps_without_backup(self):
        import runpy
        from unittest.mock import patch
        with tempfile.TemporaryDirectory() as directory:
            path = prepare_development_database(Path(directory) / "maintenance.db")
            main = runpy.run_path(str(ROOT / "scripts/run_maintenance.py"))["main"]
            with patch.dict(main.__globals__, {"load_environment_file": lambda path: None}), patch("sys.argv", ["run_maintenance.py", "--database", str(path), "--backups", directory]), patch.object(MaintenanceService, "acquire", return_value=False), patch.object(MaintenanceService, "backup") as backup:
                main()
                backup.assert_not_called()
            with WorkflowStore(path) as store:
                row = store.connection.execute("SELECT status,started_at,completed_at FROM maintenance_runs").fetchone()
                self.assertEqual(row["status"], "skipped_overlap")
                for name in ("started_at", "completed_at"):
                    self.assertEqual(row[name], serialize_timestamp(row[name]))
