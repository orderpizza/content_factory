"""Current-slice corrections, using temporary SQLite and provider fakes only."""

from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch
from io import BytesIO
from urllib.error import HTTPError
import json
import tempfile
import unittest
import subprocess
import sys
from time import perf_counter
from dashboard import render_detection_dashboard

from database.current import initialize_database, validate_database
from detection.adapters import collect_source, _validate_result, _decode_utf8, _bounded_get
from detection.collector import DetectionCollector
from detection.configuration import load_manifest
from detection.models import CollectedItem, CollectionResult, SourceCollectionError
from detection.normalization import canonical_title, canonical_link
from detection.scout import DetectionScout
from detection.store import DetectionStore

ROOT = Path(__file__).resolve().parents[1]


class CurrentSystemRepairTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.path = Path(self.temporary.name) / "fixture.db"
        initialize_database(self.path)
        self.manifest = load_manifest(ROOT / "config/releases/detection.json")
        with DetectionStore(self.path) as store:
            store.apply_manifest(self.manifest)


    def test_normalization_equivalence_is_versioned(self):
        for a, b in (("NASA’s launch", "NASA's launch"), ("test–flight", "test-flight"), ("A—B", "A-B")):
            self.assertEqual(canonical_title(a, "canonicalization_v2"), canonical_title(b, "canonicalization_v2"))
            self.assertEqual(canonical_title(a), canonical_title(b))
        for path in ("/a/", "/a//b", "/a/%2F/b", "//a///b/"):
            self.assertEqual(canonical_link("https://example.com" + path, "canonicalization_v2"), "https://example.com" + path)
        self.assertEqual(canonical_link("https://example.com/a/./b/../", "canonicalization_v2"), "https://example.com/a/")
        punctuation = CollectionResult((CollectedItem("id", "‘—’", 1),), (), True, "a" * 64, 1)
        self.assertFalse(_validate_result(punctuation, "canonicalization_v2").complete)

    def test_normalized_setup_cli_creates_only_a_new_database(self):
        path = self.path.parent / "new-cli-experiment.db"
        command = [sys.executable, str(ROOT / "scripts/setup_development.py"), "--database", str(path)]
        created = subprocess.run(command, capture_output=True, text=True)
        self.assertEqual(created.returncode, 0, created.stderr)
        with DetectionStore(path) as store:
            self.assertEqual(json.loads(store.active_release()["manifest_json"])["schema_version"], 4)
        before = path.read_bytes()
        refused = subprocess.run(command, capture_output=True, text=True)
        self.assertNotEqual(refused.returncode, 0)
        self.assertIn("already exists", refused.stderr)
        self.assertEqual(before, path.read_bytes())

    def test_normalized_collection_and_scout_have_matching_identity_versions(self):
        at = datetime(2026, 9, 9, 12, tzinfo=timezone.utc)
        result = CollectionResult(items=(CollectedItem("id", "NASA’s test–flight", 1, provider_time=at.isoformat()),),
                                  events=(), complete=True, response_hash="a" * 64, latency_ms=1)
        with DetectionStore(self.path) as store, patch("detection.collector.collect_source", return_value=result):
            DetectionCollector(store).run_due(now=at, source_ids={"nasa_recently_published_rss_v1"})
            DetectionScout(store).run(now=at)
            trend = store.connection.execute("SELECT * FROM trends").fetchone()
            candidate = store.connection.execute("SELECT * FROM trend_candidates").fetchone()
            self.assertEqual(trend["canonical_key"], "nasa s test flight")
            self.assertEqual(trend["canonicalization_version"], "canonicalization_v2")
            self.assertEqual(candidate["opportunity_identity"], "trend:canonicalization_v2:nasa s test flight")
            self.assertEqual(candidate["canonicalization_version"], "canonicalization_v2")

    def test_normalized_score_keeps_recency_diagnostic_but_not_weighted(self):
        at = datetime(2026, 9, 9, 12, tzinfo=timezone.utc)
        result = CollectionResult(items=(CollectedItem("id", "A durable topic", 1, provider_time=at.isoformat()),),
                                  events=(), complete=True, response_hash="a" * 64, latency_ms=1)
        with DetectionStore(self.path) as store, patch("detection.collector.collect_source", return_value=result):
            DetectionCollector(store).run_due(now=at, source_ids={"nasa_recently_published_rss_v1"})
            DetectionScout(store).run(now=at)
            row = store.connection.execute("SELECT score, score_formula_version, score_breakdown_json FROM trend_candidates").fetchone()
            breakdown = json.loads(row["score_breakdown_json"])
            self.assertEqual(row["score_formula_version"], "attention_v3")
            self.assertIn("evidence_recency", breakdown)
            self.assertNotIn("freshness", breakdown)
            expected = round(
                breakdown["momentum"] / 3
                + breakdown["prominence"] * 2 / 9
                + breakdown["breadth"] * 2 / 9
                + breakdown["persistence"] / 9
                + breakdown["reliability"] / 9,
                4,
            )
            self.assertEqual(row["score"], expected)

    def test_semantic_resolution_does_not_change_lexical_canonicalization(self):
        self.assertNotEqual(
            canonical_title("OpenAI launches a browser", "canonicalization_v2"),
            canonical_title("ChatGPT maker enters the browser market", "canonicalization_v2"),
        )

    def test_budget_deferred_candidates_remain_in_the_queue(self):
        at = datetime(2026, 9, 9, 12, tzinfo=timezone.utc)
        result = CollectionResult(items=(CollectedItem("id", "Queued topic", 1, provider_time=at.isoformat()),),
                                  events=(), complete=True, response_hash="a" * 64, latency_ms=1)
        with DetectionStore(self.path) as store, patch("detection.collector.collect_source", return_value=result):
            DetectionCollector(store).run_due(now=at, source_ids={"nasa_recently_published_rss_v1"})
            DetectionScout(store).run(now=at)
            with store.connection:
                store.connection.execute(
                    "UPDATE trend_candidates SET eligibility_status='deferred_by_budget', "
                    "eligibility_reason='selection_budget_exhausted', selected_at=NULL, "
                    "selected_thread_id=NULL, last_seen_at=?",
                    ((at - timedelta(days=7)).isoformat(),),
                )
            DetectionScout(store).run(now=at + timedelta(days=7))
            status = store.connection.execute("SELECT eligibility_status FROM trend_candidates").fetchone()[0]
            self.assertEqual(status, "deferred_by_budget")

    def test_oversized_metadata_is_rejected_not_truncated(self):
        result = CollectionResult(items=(CollectedItem("id", "x" * 513, 1), CollectedItem("good", "Good title", 1)),
                                  events=(), complete=True, response_hash="a" * 64, latency_ms=1)
        checked = _validate_result(result)
        self.assertFalse(checked.complete)
        self.assertEqual([i.title for i in checked.items], ["Good title"])
        self.assertEqual(checked.events[0].disposition, "rejected_oversized")
        for item in (CollectedItem("x" * 1001, "Title", 1), CollectedItem("id", "Title", 1, payload={"large": "x" * 16385})):
            self.assertEqual(_validate_result(CollectionResult((item,), (), True, "a" * 64, 1)).items, ())

    def test_feed_oversize_and_invalid_titles_make_response_incomplete(self):
        with DetectionStore(self.path) as store:
            row = dict(next(s for s in store.enabled_sources() if s["source_kind"] == "publisher_feed_collector_v1"))
        row.update(canonicalization_version="canonicalization_v2", collection_day="2026-09-09")
        body = ("<rss><channel><item><title>" + "x" * 513 + "</title><guid>bad</guid></item><item><title>Good title</title><guid>good</guid></item></channel></rss>").encode()
        with patch("detection.adapters._bounded_get", return_value=(body, {}, "https://www.nasa.gov/feed/", [])):
            result = collect_source(row)
        self.assertFalse(result.complete)
        self.assertEqual([i.source_item_key for i in result.items], ["good"])

    def test_invalid_encoding_and_encoded_xml_entities_are_rejected(self):
        for body in (b"\xff", '<!DOCTYPE rss [<!ENTITY a "b">]><rss/>'.encode("utf-16"), b"hello\x00world"):
            with self.assertRaises(SourceCollectionError):
                _decode_utf8(body)

    def test_malformed_wikimedia_item_does_not_discard_valid_partial_evidence(self):
        with DetectionStore(self.path) as store:
            row = dict(next(s for s in store.enabled_sources() if s["source_kind"] == "wikimedia_enwiki_pageviews_v1"))
        row["report_date"] = "2026-09-08"
        body = json.dumps({"items": [{"year": "2026", "month": "09", "day": "08", "articles": [None, {"article": "Good_title", "views": 10, "rank": 2}]}]}).encode()
        with patch("detection.adapters._bounded_get", return_value=(body, {}, "https://wikimedia.org", [])):
            result = collect_source(row)
        self.assertFalse(result.complete)
        self.assertEqual(len(result.items), 1)
        self.assertEqual(result.events[0].disposition, "rejected_invalid")

    def test_http_snapshot_validation_does_not_scan_foreign_keys(self):
        with DetectionStore(self.path, read_only=True) as store:
            statements = []
            store.connection.set_trace_callback(statements.append)
            validate_database(store.connection, check_foreign_keys=False)
            self.assertFalse(any("foreign_key_check" in sql for sql in statements))
            validate_database(store.connection)
            self.assertTrue(any("foreign_key_check" in sql for sql in statements))

    def test_http_error_stream_is_closed_even_for_redirect_rejection(self):
        body = BytesIO(b"not safe diagnostic content")
        error = HTTPError("https://example.com", 302, "redirect", {}, body)
        with patch("detection.adapters._validate_public_https", return_value=("93.184.216.34",)), patch("detection.adapters.build_opener") as opener:
            opener.return_value.open.side_effect = error
            with self.assertRaises(SourceCollectionError):
                _bounded_get("https://example.com", allowed_hosts=["example.com"])
        self.assertTrue(body.closed)

    def test_title_only_keys_are_day_scoped_in_normalized_release(self):
        with DetectionStore(self.path) as store:
            row = dict(next(s for s in store.enabled_sources() if s["source_kind"] == "publisher_feed_collector_v1"))
        body = b"<rss><channel><item><title>Daily update</title></item></channel></rss>"
        keys = []
        with patch("detection.adapters._bounded_get", return_value=(body, {}, "https://www.nasa.gov/feed/", [])):
            for day in ("2026-09-08", "2026-09-09"):
                row.update(canonicalization_version="canonicalization_v2", collection_day=day)
                keys.append(collect_source(row).items[0].source_item_key)
        self.assertNotEqual(*keys)

    def test_reporting_stays_bounded_with_ten_thousand_operational_rows(self):
        with DetectionStore(self.path) as store:
            with store.connection:
                store.connection.executemany(
                    "INSERT INTO worker_runs(worker_type,instance_id,started_at,status,safe_summary,created_at) VALUES ('fixture','test','2026-09-09T00:00:00+00:00','completed',?,'2026-09-09T00:00:00+00:00')",
                    [(f"load-row-{index}",) for index in range(10_000)],
                )
            started = perf_counter()
            html = render_detection_dashboard(store.connection)
            self.render_seconds = perf_counter() - started
            self.assertEqual(html.count("load-row-"), 50)
            self.assertLess(len(html), 100_000)
            query_plan = store.connection.execute(
                "EXPLAIN QUERY PLAN SELECT * FROM source_collection_attempts WHERE source_instance_id=? ORDER BY scheduled_for LIMIT 1", (1,)
            ).fetchall()
            self.assertTrue(any("INDEX" in row[3] for row in query_plan))


if __name__ == "__main__":
    unittest.main()
