import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch
import json
import os

from common.environment import EnvironmentFileError, load_environment_file
from database.current import (
    SchemaError,
    connect,
    initialize_database,
    initialize_database,
    validate_database,
)
from dashboard import render_detection_dashboard
from detection.adapters import collect_source
from detection.collector import DetectionCollector
from detection.configuration import load_manifest
from detection.models import CollectedItem, CollectionResult, SourceCollectionError
from detection.reporting import summarize_scout
from detection.scout import DetectionScout
from detection.store import DetectionStore
from workflow import DeterminationWorker, WorkflowStore


ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "config" / "releases" / "detection.json"


class DetectionDashboardSliceTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.database_path = Path(self.directory.name) / "development.db"
        initialize_database(self.database_path)
        with DetectionStore(self.database_path) as store:
            store.apply_manifest(load_manifest(MANIFEST))


    def tearDown(self):
        self.directory.cleanup()

    def test_migration_is_idempotent_and_dashboard_connection_is_read_only(self):
        self.assertFalse(initialize_database(self.database_path))
        connection = connect(self.database_path, read_only=True)
        try:
            validate_database(connection)
            with self.assertRaises(Exception):
                connection.execute("CREATE TABLE forbidden(id INTEGER)")
        finally:
            connection.close()

    def test_worker_startup_does_not_create_an_absent_database(self):
        missing = Path(self.directory.name) / "missing.db"
        with self.assertRaises(SchemaError):
            DetectionStore(missing)
        self.assertFalse(missing.exists())

    def test_local_environment_loader_never_overrides_process_values(self):
        environment_file = Path(self.directory.name) / ".env"
        environment_file.write_text(
            "CONTENT_FACTORY_TEST_EXISTING=file-value\n"
            "CONTENT_FACTORY_TEST_NEW='loaded value'\n",
            encoding="utf-8",
        )
        with patch.dict(
            os.environ, {"CONTENT_FACTORY_TEST_EXISTING": "process-value"}, clear=False
        ):
            os.environ.pop("CONTENT_FACTORY_TEST_NEW", None)
            self.assertTrue(load_environment_file(environment_file))
            self.assertEqual(os.environ["CONTENT_FACTORY_TEST_EXISTING"], "process-value")
            self.assertEqual(os.environ["CONTENT_FACTORY_TEST_NEW"], "loaded value")
            os.environ.pop("CONTENT_FACTORY_TEST_NEW", None)

    def test_local_environment_loader_rejects_malformed_lines_without_values(self):
        environment_file = Path(self.directory.name) / ".env"
        environment_file.write_text("not-an-assignment", encoding="utf-8")
        with self.assertRaises(EnvironmentFileError) as raised:
            load_environment_file(environment_file)
        self.assertNotIn("not-an-assignment", str(raised.exception))

    def test_schema_checksum_mismatch_is_rejected(self):
        connection = connect(self.database_path)
        try:
            connection.execute(
                "UPDATE schema_migrations SET checksum=? WHERE version=7", ("0" * 64,)
            )
            connection.commit()
            with self.assertRaises(SchemaError):
                validate_database(connection)
        finally:
            connection.close()

    def test_current_hacker_news_adapter_accounts_for_all_top_100_positions(self):
        with DetectionStore(self.database_path, read_only=True) as store:
            source = store.connection.execute(
                "SELECT * FROM detection_source_instances "
                "WHERE stable_id='hacker_news_top_stories_v1'"
            ).fetchone()

            def fake_get(url, **_kwargs):
                if url.endswith("topstories.json"):
                    body = json.dumps(list(range(1, 101))).encode("utf-8")
                else:
                    item_id = int(url.rsplit("/", 1)[-1].removesuffix(".json"))
                    body = json.dumps({
                        "id": item_id,
                        "type": "story",
                        "title": f"Story {item_id}",
                        "score": 101 - item_id,
                        "time": 1_700_000_000,
                        "url": f"https://example.com/{item_id}",
                    }).encode("utf-8")
                return body, {}, url, []

            with patch("detection.adapters._bounded_get", side_effect=fake_get):
                result = collect_source(source)

        self.assertTrue(result.complete)
        self.assertEqual(len(result.items), 100)
        self.assertEqual(result.events, ())

    def test_retry_recovers_same_attempt_and_audits_each_outbound_execution(self):
        now = datetime.now(timezone.utc).replace(microsecond=0)
        success = CollectionResult(
            items=(
                CollectedItem(
                    "stable-item", "Stable Item", 1.0,
                    source_item_id="stable-item", provider_time=now.isoformat(),
                ),
            ),
            events=(), complete=True, response_hash="b" * 64, latency_ms=3,
        )
        with DetectionStore(self.database_path) as store:
            collector = DetectionCollector(store, instance_id="collector-retry-test")
            with patch(
                "detection.collector.collect_source",
                side_effect=[SourceCollectionError("transport_error", "temporary"), success],
            ):
                first = collector.run_due(
                    now=now, source_ids={"nasa_recently_published_rss_v1"}
                )[0]
                store.connection.execute(
                    "UPDATE source_collection_attempts SET next_attempt_at=? "
                    "WHERE source_collection_attempt_id=?",
                    ((now - timedelta(seconds=1)).isoformat(), first["attempt_id"]),
                )
                store.connection.commit()
                second = collector.run_due(
                    now=now, source_ids={"nasa_recently_published_rss_v1"}
                )[0]
            executions = store.connection.execute(
                "SELECT request_ordinal, status FROM source_request_executions "
                "WHERE source_collection_attempt_id=? ORDER BY request_ordinal",
                (first["attempt_id"],),
            ).fetchall()
            health_count = int(store.connection.execute(
                "SELECT COUNT(*) FROM source_health WHERE source_collection_attempt_id=?",
                (first["attempt_id"],),
            ).fetchone()[0])

        self.assertEqual(first["status"], "retry_wait")
        self.assertEqual(second["status"], "completed")
        self.assertEqual(first["attempt_id"], second["attempt_id"])
        self.assertEqual(
            [(row["request_ordinal"], row["status"]) for row in executions],
            [(1, "failed"), (2, "succeeded")],
        )
        self.assertEqual(health_count, 1)

    def test_youtube_quota_is_reserved_by_utc_request_day_before_outbound_call(self):
        now = datetime.now(timezone.utc).replace(microsecond=0)
        with DetectionStore(self.database_path) as store:
            source = store.connection.execute(
                "SELECT * FROM detection_source_instances "
                "WHERE stable_id='youtube_us_most_popular_v1'"
            ).fetchone()
            store.connection.execute(
                "UPDATE detection_source_instances SET quota_limit=1 "
                "WHERE detection_source_instance_id=?",
                (source["detection_source_instance_id"],),
            )
            prior = store.connection.execute(
                "INSERT INTO source_collection_attempts "
                "(source_instance_id, configuration_release_id, scheduled_for, request_json, "
                "request_hash, item_count, complete, quota_units_reserved, status, "
                "attempt_limit, created_at, completed_at) "
                "VALUES (?,?,?,?,?,0,1,1,'completed',3,?,?)",
                (
                    source["detection_source_instance_id"], source["configuration_release_id"],
                    (now - timedelta(days=1)).isoformat(), "{}", "c" * 64,
                    (now - timedelta(days=1)).isoformat(),
                    (now - timedelta(days=1)).isoformat(),
                ),
            )
            store.connection.execute(
                "INSERT INTO source_request_executions "
                "(source_collection_attempt_id, source_instance_id, request_ordinal, quota_day, "
                "quota_units, status, reserved_at, completed_at) "
                "VALUES (?,?,1,?,1,'succeeded',?,?)",
                (
                    prior.lastrowid, source["detection_source_instance_id"], now.date().isoformat(),
                    now.isoformat(), now.isoformat(),
                ),
            )
            store.connection.commit()
            with patch.dict("os.environ", {"YOUTUBE_API_KEY": "test-key"}), patch(
                "detection.collector.collect_source"
            ) as outbound:
                outcome = DetectionCollector(
                    store, instance_id="collector-quota-test"
                ).run_due(now=now, source_ids={"youtube_us_most_popular_v1"})[0]
            latest = store.connection.execute(
                "SELECT a.failure_category, h.classification "
                "FROM source_collection_attempts a JOIN source_health h "
                "ON h.source_collection_attempt_id=a.source_collection_attempt_id "
                "WHERE a.source_collection_attempt_id=?",
                (outcome["attempt_id"],),
            ).fetchone()

        outbound.assert_not_called()
        self.assertEqual(outcome["status"], "failed")
        self.assertEqual(latest["failure_category"], "quota_limited")
        self.assertEqual(latest["classification"], "quota_limited")

    def test_collection_scout_selection_and_dashboard_feed_share_sqlite_boundary(self):
        now = datetime(2026, 9, 7, 12, 7, tzinfo=timezone.utc)

        collection_time = now
        shared_activity = 1000.0

        def fake_collect(source):
            if source["stable_id"] == "nasa_recently_published_rss_v1":
                items = (
                    CollectedItem(
                        "nasa-shared", "Shared Opportunity", shared_activity,
                        rank=1, source_item_id="nasa-shared",
                        canonical_url="https://www.nasa.gov/shared",
                        provider_time=collection_time.isoformat(),
                    ),
                    CollectedItem(
                        "nasa-other", "Other Topic", 1.0,
                        rank=100, source_item_id="nasa-other",
                        canonical_url="https://www.nasa.gov/other",
                        provider_time=collection_time.isoformat(),
                    ),
                )
            else:
                items = (
                    CollectedItem(
                        "101", "Shared Opportunity", shared_activity,
                        rank=1, source_item_id="101",
                        canonical_url="https://news.ycombinator.com/item?id=101",
                    ),
                    CollectedItem(
                        "102", "Other Topic", 1.0,
                        rank=100, source_item_id="102",
                        canonical_url="https://news.ycombinator.com/item?id=102",
                    ),
                )
            return CollectionResult(
                items=items,
                events=(),
                complete=True,
                response_hash="a" * 64,
                latency_ms=4,
            )

        with DetectionStore(self.database_path) as store:
            with patch("detection.collector.collect_source", side_effect=fake_collect):
                collection_time = now
                shared_activity = 1000.0
                collection = DetectionCollector(store, instance_id="collector-test").run_due(
                    now=now,
                    source_ids={
                        "nasa_recently_published_rss_v1",
                        "hacker_news_top_stories_v1",
                        "youtube_us_most_popular_v1",
                    },
                )
            result = DetectionScout(store, instance_id="scout-test").run(now=now)
            summary = summarize_scout(store, result)
            selected = store.connection.execute(
                "SELECT c.*, t.thread_id, r.revision_id, d.determination_request_id "
                "FROM trend_candidates c "
                "JOIN content_threads t ON t.thread_id=c.selected_thread_id "
                "JOIN brief_revisions r ON r.thread_id=t.thread_id "
                "JOIN determination_requests d ON d.revision_id=r.revision_id "
                "WHERE c.canonical_subject='Shared Opportunity'"
            ).fetchone()

        self.assertEqual([item["status"] for item in collection], ["completed", "completed", "completed"])
        self.assertEqual(result["status"], "completed")
        self.assertEqual(result["selected_count"], 1)
        self.assertEqual(summary["top_clusters"][0]["subject"], "Shared Opportunity")
        self.assertEqual(summary['cluster_count'], result['candidate_count'])
        self.assertNotIn('top_candidates', summary)
        self.assertNotIn("prominence_populations", summary)
        self.assertEqual(selected["eligibility_status"], "selected")
        self.assertIsNotNone(selected["thread_id"])
        self.assertIsNotNone(selected["revision_id"])
        self.assertIsNotNone(selected["determination_request_id"])

        with WorkflowStore(self.database_path) as workflow:
            workflow.register_capability(
                "english",
                enabled=True,
                generation_ready=True,
                outputs=[{
                    "platform": "instagram",
                    "account": "fixture_english",
                    "content_format": "instagram_static_carousel_v2",
                    "ready": True,
                }],
            )
            decision_id = DeterminationWorker(workflow).run_once()
            self.assertIsNotNone(decision_id)
            self.assertEqual(
                workflow.connection.execute(
                    "SELECT COUNT(*) FROM intake_requests"
                ).fetchone()[0],
                0,
            )

        connection = connect(self.database_path, read_only=True)
        try:
            html = render_detection_dashboard(connection)
        finally:
            connection.close()
        self.assertIn("Shared Opportunity", html)
        self.assertIn("Raw Feed Items", html)
        self.assertIn("class='flow-columns'", html)
        self.assertNotIn("<h1>Trend Opportunities</h1>", html)
        self.assertNotIn("Configuration:", html)
        self.assertIn("2026-09-07T12:07:00", html)
        self.assertIn("method='get'", html)
        self.assertNotIn("method='post'", html)

        connection = connect(self.database_path, read_only=True)
        try:
            filtered = render_detection_dashboard(
                connection,
                query="shared opportunity",
                source="hacker_news_top_stories_v1",
                status="selected",
            )
        finally:
            connection.close()
        self.assertIn("1 selected", filtered)
        self.assertIn("1 observation(s)", filtered)
        self.assertNotIn("Other Topic", filtered)


if __name__ == "__main__":
    unittest.main()
