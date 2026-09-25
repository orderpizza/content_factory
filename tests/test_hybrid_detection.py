"""Deterministic normalized detection regressions; temporary SQLite, no providers."""

from common.timestamps import serialize_timestamp
from copy import deepcopy
from database.current import connect, initialize_database
from datetime import datetime, timedelta, timezone
from detection.adapters import _PinnedHTTPSConnection, _validate_public_https
from detection.collector import DetectionCollector
from detection.configuration import load_manifest
from detection.hybrid import HN, WIKI, activity, health
from detection.models import CollectedItem, CollectionResult, ItemEvent, SourceCollectionError
from detection.scout import DetectionScout
from detection.store import DetectionStore
from pathlib import Path
from unittest.mock import MagicMock, patch
import json
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]


class HybridDetectionTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / "hybrid.db"
        initialize_database(self.path)
        self.manifest = load_manifest(ROOT / "config/releases/detection.json")
        self.at = datetime(2026, 9, 9, 12, tzinfo=timezone.utc)
        with DetectionStore(self.path) as store:
            store.apply_manifest(self.manifest)


    def collect(self, store, source_id, *, at=None, empty=False):
        at = at or self.at
        def result(source):
            provider_time = source["report_date"] + "T00:00:00" if source["source_kind"] == WIKI else serialize_timestamp(at)
            items = () if empty else (CollectedItem("subject", "Shared subject", 100, rank=1, provider_time=provider_time),)
            return CollectionResult(items=items, events=(), complete=True, response_hash="a" * 64, latency_ms=1)
        with patch("detection.collector.collect_source", side_effect=result):
            return DetectionCollector(store).run_due(now=at, source_ids={source_id})

    def test_current_schema_is_idempotent(self):
        self.assertFalse(initialize_database(self.path))
        self.assertFalse(initialize_database(self.path))
        with DetectionStore(self.path) as store:
            self.assertEqual(store.connection.execute("PRAGMA user_version").fetchone()[0], 16)
            self.assertEqual(store.connection.execute("SELECT COUNT(*) FROM schema_migrations").fetchone()[0], 1)

    def test_midday_daily_report_and_live_feed_both_contribute(self):
        with DetectionStore(self.path) as store:
            self.collect(store, "wikimedia_enwiki_daily_v1")
            self.collect(store, "openai_news_rss_v1")
            result = DetectionScout(store).run(now=self.at)
            self.assertEqual(result["candidate_count"], 1)
            row = store.connection.execute("SELECT * FROM trend_candidates").fetchone()
            breakdown = json.loads(row["score_breakdown_json"])
            self.assertEqual(row["score_formula_version"], "attention_v3")
            self.assertEqual(len(breakdown["source_components"]), 2)
            self.assertAlmostEqual(breakdown["breadth"], 2 / 3)
            self.assertEqual(row["last_seen_at"], "2026-09-09T12:00:00")
            for component in breakdown["source_components"]:
                ref = component["prominence_population"]
                population = store.connection.execute(
                    "SELECT * FROM scout_prominence_populations WHERE scout_evaluation_run_id=? AND source_kind=?",
                    (ref["scout_evaluation_run_id"], ref["source_kind"]),
                ).fetchone()
                self.assertEqual(population["population_hash"], ref["population_hash"])
                self.assertEqual(len(json.loads(population["population_json"])), ref["population_size"])

    def test_daily_evidence_age_is_report_end_not_scout_or_collection_time(self):
        with DetectionStore(self.path) as store:
            self.collect(store, "wikimedia_enwiki_daily_v1")
            DetectionScout(store).run(now=self.at)
            first = store.connection.execute("SELECT last_seen_at FROM trend_candidates").fetchone()[0]
            DetectionScout(store).run(now=self.at + timedelta(minutes=15))
            self.assertEqual(first, "2026-09-09T00:00:00")
            self.assertEqual(store.connection.execute("SELECT last_seen_at FROM trend_candidates").fetchone()[0], first)

    def test_empty_new_daily_report_does_not_resurrect_yesterdays_articles(self):
        with DetectionStore(self.path) as store:
            self.collect(store, "wikimedia_enwiki_daily_v1", at=self.at - timedelta(days=1))
            self.collect(store, "wikimedia_enwiki_daily_v1", empty=True)
            self.assertEqual(DetectionScout(store).run(now=self.at)["candidate_count"], 0)

    def test_health_late_and_quota_rules(self):
        source = {"availability_seconds": 100}
        complete = [{"collected_at": serialize_timestamp(self.at), "source_collection_attempt_id": 1}]
        self.assertEqual(health(source, complete, [], self.at + timedelta(seconds=200))[0], "degraded")
        failures = [{"time": serialize_timestamp(self.at + timedelta(seconds=1)), "category": "quota_limited"}]
        self.assertEqual(health(source, complete, failures, self.at + timedelta(seconds=2))[0], "quota_limited")

    def test_repeated_wikimedia_rows_and_hn_rounding(self):
        row = {"activity_contributor": 1, "source_item_key": "article", "window_start": "2026-09-08", "activity": 100, "trend_observation_id": 1}
        self.assertEqual(activity(WIKI, [row, {**row, "trend_observation_id": 2}]), 100)
        value = activity(HN, [{"activity_contributor": 1, "rank": 47, "activity": 87}])
        self.assertEqual(value, round(value, 6))

    def test_empty_healthy_completed_days_are_zero_baselines(self):
        with DetectionStore(self.path) as store:
            for offset in reversed(range(2, 9)):
                at = (self.at - timedelta(days=offset)).replace(hour=23, minute=59)
                self.collect(store, "openai_news_rss_v1", at=at, empty=True)
            self.collect(store, "openai_news_rss_v1")
            DetectionScout(store).run(now=self.at)
            breakdown = json.loads(store.connection.execute("SELECT score_breakdown_json FROM trend_candidates").fetchone()[0])
            source = breakdown["source_components"][0]
            self.assertEqual(source["history_windows"], 7)
            self.assertEqual(source["baseline_values"], [0] * 7)
            self.assertTrue(source["history_ready"])

    def test_compatible_release_retains_history_and_existing_selected_handoff(self):
        with DetectionStore(self.path) as store:
            self.collect(store, "wikimedia_enwiki_daily_v1")
            self.collect(store, "openai_news_rss_v1")
            DetectionScout(store).run(now=self.at)
            count = store.connection.execute("SELECT COUNT(*) FROM content_threads").fetchone()[0]
            newer = deepcopy(self.manifest)
            newer["release_name"] = "compatible-hybrid-fixture"
            store.apply_manifest(newer)
            result = DetectionScout(store).run(now=self.at + timedelta(minutes=15))
            self.assertEqual(result["candidate_count"], 1)
            self.assertEqual(store.connection.execute("SELECT COUNT(*) FROM content_threads").fetchone()[0], count)

    def test_retry_uses_exact_frozen_historical_health(self):
        with DetectionStore(self.path) as store:
            self.collect(store, "openai_news_rss_v1")
            scout = DetectionScout(store)
            with patch.object(scout, "_finalize", side_effect=RuntimeError("fixture after freeze")):
                with self.assertRaises(RuntimeError):
                    scout.run(now=self.at)
            before = store.connection.execute("SELECT snapshot_json FROM scout_frozen_evidence").fetchone()[0]
            with store.connection:
                store.connection.execute("UPDATE scout_evaluation_runs SET next_attempt_at=?", (serialize_timestamp(self.at),))
            self.collect(store, "openai_news_rss_v1", at=self.at + timedelta(minutes=61), empty=True)
            self.assertEqual(scout.run(now=self.at + timedelta(minutes=20))["status"], "completed")
            self.assertEqual(store.connection.execute("SELECT snapshot_json FROM scout_frozen_evidence").fetchone()[0], before)

    def test_partial_response_audit_survives_without_scoring_observations(self):
        result = CollectionResult(items=(CollectedItem("valid", "Valid partial item", 1),),
                                  events=(ItemEvent("rejected_invalid", "missing rank", source_ordinal=2),),
                                  complete=False, response_hash="b" * 64, latency_ms=1)
        with DetectionStore(self.path) as store, patch("detection.collector.collect_source", return_value=result):
            DetectionCollector(store).run_due(now=self.at, source_ids={"openai_news_rss_v1"})
            evidence = store.connection.execute("SELECT * FROM source_execution_evidence").fetchone()
            self.assertEqual(evidence["complete"], 0)
            self.assertEqual(json.loads(evidence["evidence_json"])["items"][0]["title"], "Valid partial item")
            self.assertEqual(store.connection.execute("SELECT COUNT(*) FROM trend_observations").fetchone()[0], 0)

    def test_transport_pins_validated_ip_and_preserves_tls_hostname(self):
        connection = _PinnedHTTPSConnection("example.com", addresses=("93.184.216.34",), expected_host="example.com")
        context = MagicMock()
        connection._context = context
        with patch("socket.create_connection") as create:
            connection.connect()
        self.assertEqual(create.call_args.args[0], ("93.184.216.34", 443))
        self.assertEqual(context.wrap_socket.call_args.kwargs["server_hostname"], "example.com")
        with patch("socket.getaddrinfo", return_value=[(None, None, None, None, ("127.0.0.1", 443))]):
            with self.assertRaises(SourceCollectionError):
                _validate_public_https("https://example.com", {"example.com"})

    def test_read_only_missing_path_does_not_create_file(self):
        missing = self.path.parent / "missing.db"
        import sqlite3
        with self.assertRaises(sqlite3.OperationalError):
            connect(missing, read_only=True)
        self.assertFalse(missing.exists())

    def test_quota_reservations_survive_release_activation(self):
        limited = deepcopy(self.manifest)
        limited["release_name"] = "quota-fixture"
        source = next(s for s in limited["components"]["detection"]["sources"] if s["stable_id"] == "openai_news_rss_v1")
        source["quota_limit"] = 1000
        with DetectionStore(self.path) as store:
            store.apply_manifest(limited)
            self.collect(store, source["stable_id"])
            # Model an already exhausted day without 1,000 fixture executions.
            with store.connection:
                store.connection.execute("UPDATE source_request_executions SET quota_units=1000")
            limited["release_name"] = "quota-fixture-next-release"
            store.apply_manifest(limited)
            with patch("detection.collector.collect_source") as provider:
                DetectionCollector(store).run_due(now=self.at + timedelta(minutes=61), source_ids={source["stable_id"]})
            provider.assert_not_called()
            self.assertEqual(store.connection.execute("SELECT COUNT(*) FROM source_request_executions").fetchone()[0], 1)

    def test_v3_observations_and_population_are_immutable(self):
        import sqlite3
        with DetectionStore(self.path) as store:
            self.collect(store, "openai_news_rss_v1")
            DetectionScout(store).run(now=self.at)
            for query in ("UPDATE trend_observations SET activity=999", "UPDATE scout_prominence_populations SET population_json='[]'"):
                with self.assertRaises(sqlite3.IntegrityError), store.connection:
                    store.connection.execute(query)


if __name__ == "__main__":
    unittest.main()
