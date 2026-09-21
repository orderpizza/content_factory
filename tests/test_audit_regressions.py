"""Offline regressions for the September repository audit; never use live state."""

from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch
import importlib
import runpy
import sqlite3
import tempfile
import unittest

from database.current import (
    SchemaError, connect, initialize_database,
)
from dashboard import render_detection_dashboard
from detection.collector import DetectionCollector
from detection.configuration import load_manifest
from detection.models import CollectedItem, CollectionResult
from detection.scout import DetectionScout
from detection.store import DetectionStore
from workflow import IdeaIntakeWorker, WorkflowStore


ROOT = Path(__file__).resolve().parents[1]


class AuditRegressionTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.path = Path(self.temporary.name) / "audit.db"
        initialize_database(self.path)
        with DetectionStore(self.path) as store:
            store.apply_manifest(load_manifest(ROOT / "config/releases/detection.json"))

        self.start = datetime(2026, 9, 8, 12, tzinfo=timezone.utc)

    def collect_fixture(self, store, *, two_sources=False, at=None, activity=100):
        at = at or self.start
        def collect(source):
            items = [CollectedItem(
                "shared", "Shared audit opportunity", activity,
                source_item_id="shared", rank=1, provider_time=at.isoformat(),
            )]
            items.append(CollectedItem(
                "other", "Other audit opportunity", 1, rank=100,
                provider_time=at.isoformat(),
            ))
            return CollectionResult(
                items=tuple(items), events=(), complete=True,
                response_hash="a" * 64, latency_ms=1,
            )
        sources = {"hacker_news_top_stories_v1"}
        if two_sources:
            sources.update({"nasa_recently_published_rss_v1", "youtube_us_most_popular_v1"})
        with patch("detection.collector.collect_source", side_effect=collect):
            DetectionCollector(store).run_due(now=at, source_ids=sources)

    def retry_after_freeze(self, store, scout):
        with patch.object(scout, "_finalize", side_effect=RuntimeError("injected after freeze")):
            with self.assertRaisesRegex(RuntimeError, "injected"):
                scout.run(now=self.start)
        # Set the due time explicitly: the worker's failure clock is wall time.
        with store.connection:
            store.connection.execute(
                "UPDATE scout_evaluation_runs SET next_attempt_at=?",
                ((self.start + timedelta(seconds=30)).isoformat(),),
            )
        return store.connection.execute(
            "SELECT input_frozen_at,input_hash FROM scout_evaluation_runs"
        ).fetchone()

    def test_scout_recovers_a_frozen_empty_input_without_refreezing(self):
        with DetectionStore(self.path) as store:
            scout = DetectionScout(store)
            before = tuple(self.retry_after_freeze(store, scout))
            result = scout.run(now=self.start + timedelta(minutes=20))
            self.assertEqual(result["status"], "completed")
            self.assertEqual(result["candidate_count"], 0)
            self.assertEqual(store.connection.execute(
                "SELECT COUNT(*) FROM scout_evaluation_inputs"
            ).fetchone()[0], 4)
            self.assertEqual(tuple(store.connection.execute(
                "SELECT input_frozen_at,input_hash FROM scout_evaluation_runs"
            ).fetchone()), before)

    def test_scout_retry_uses_original_evaluation_clock(self):
        with DetectionStore(self.path) as store:
            self.collect_fixture(store)
            scout = DetectionScout(store)
            self.retry_after_freeze(store, scout)
            with patch.object(scout, "_evaluate", wraps=scout._evaluate) as evaluate:
                result = scout.run(now=self.start + timedelta(minutes=20))
            self.assertEqual(result["status"], "completed")
            self.assertEqual(evaluate.call_args.args[3], self.start)

    def test_stale_scout_cannot_freeze_inputs(self):
        with DetectionStore(self.path) as store:
            scout = DetectionScout(store, instance_id="old")
            release_id = store.active_release()["configuration_release_id"]
            run_id = scout._materialize_run(self.start, release_id, self.start)
            old_version = scout._claim(run_id, self.start)
            newer = DetectionScout(store, instance_id="new")
            self.assertIsNotNone(newer._claim(run_id, self.start + timedelta(minutes=11)))
            with self.assertRaisesRegex(RuntimeError, "claim"):
                scout._freeze_inputs(run_id, release_id, self.start, old_version)
            self.assertEqual(store.connection.execute(
                "SELECT COUNT(*) FROM scout_evaluation_inputs"
            ).fetchone()[0], 0)

    def test_read_only_connection_encodes_hash_and_unicode_in_paths(self):
        directory = Path(self.temporary.name) / "audit # 한글 %"
        path = directory / "development.db"
        initialize_database(path)
        connection = connect(path, read_only=True)
        try:
            self.assertEqual(connection.execute("PRAGMA user_version").fetchone()[0], 7)
            with self.assertRaises(sqlite3.OperationalError):
                connection.execute("CREATE TABLE forbidden(id INTEGER)")
        finally:
            connection.close()

    def test_failed_store_validation_closes_its_connection(self):
        for module_name, class_name, validator in (
            ("detection.store", "DetectionStore", "validate_database"),
            ("workflow.store", "WorkflowStore", "validate_database"),
        ):
            with self.subTest(module=module_name):
                module = importlib.import_module(module_name)
                connection = MagicMock()
                with patch.object(module, "connect", return_value=connection), patch.object(
                    module, validator, side_effect=SchemaError("synthetic invalid schema")
                ):
                    with self.assertRaises(SchemaError):
                        getattr(module, class_name)(self.path)
                connection.close.assert_called_once_with()

    def test_dashboard_counts_one_candidate_after_thread_continuation(self):
        initialize_database(self.path)
        with DetectionStore(self.path) as store:
            for days in range(7, 0, -1):
                self.collect_fixture(store, two_sources=True, at=self.start - timedelta(days=days), activity=1)
            self.collect_fixture(store, two_sources=True, activity=1000)
            self.assertEqual(DetectionScout(store).run(now=self.start)["selected_count"], 1)
        with WorkflowStore(self.path) as store:
            IdeaIntakeWorker(store).run_once()
            thread_id = store.connection.execute("SELECT thread_id FROM content_threads").fetchone()[0]
            store.continue_human_thread(thread_id, "Please include a useful example", command_id="reply", expected_row_version=store.connection.execute("SELECT row_version FROM content_threads WHERE thread_id=?", (thread_id,)).fetchone()[0])
        connection = connect(self.path, read_only=True)
        try:
            html = render_detection_dashboard(connection)
        finally:
            connection.close()
        self.assertIn("1 selected", html)
        self.assertNotIn("2 selected", html)

    def test_utility_imports_do_not_open_databases_or_load_environment(self):
        with patch("database.current.connect") as connection, patch("common.environment.load_environment_file") as environment:
            for name in ("dashboard.py",):
                runpy.run_path(str(ROOT / "scripts" / name), run_name="audit_import")
            connection.assert_not_called()
            environment.assert_not_called()

    def test_v2_composition_entrypoints_load_environment_before_resolving_settings(self):
        import os
        for name, arguments in (
            ("create_local_idea.py", ["A local fixture idea"]),
            ("enable_placeholder_route.py", ["--confirm-local-placeholder"]),
            ("run_workflow.py", []),
        ):
            with self.subTest(script=name), patch.dict(os.environ, {}, clear=True):
                module = runpy.run_path(str(ROOT / "scripts" / name), run_name="audit_import")
                worker_store = MagicMock()
                def load(_path):
                    os.environ["CONTENT_FACTORY_DB_PATH"] = str(self.path)
                    os.environ["CONTENT_FACTORY_ARTIFACT_ROOT"] = str(Path(self.temporary.name) / "configured")
                with patch.dict(module["main"].__globals__, {
                    "load_environment_file": load, "WorkflowStore": worker_store,
                }), patch("sys.argv", [name, *arguments]), patch("builtins.print"):
                    if name == "run_workflow.py":
                        factories = {key: MagicMock() for key in (
                            "IdeaIntakeWorker", "DeterminationWorker", "PipelineRunner",
                            "AdaptationWorker", "VisualPlanner", "VisualRenderer", "PostingAgent", "StorageMonitor",
                        )}
                        with patch.dict(module["main"].__globals__, factories):
                            module["main"]()
                        self.assertEqual(factories["VisualRenderer"].call_args.args[1], os.environ["CONTENT_FACTORY_ARTIFACT_ROOT"])
                    else:
                        module["main"]()
                self.assertEqual(worker_store.call_args.args[0], str(self.path))


if __name__ == "__main__":
    unittest.main()
