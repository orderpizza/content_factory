"""Detection; offline tests use temporary databases and fake providers."""

from common.diagnostics import safe_diagnostic
from common.timestamps import serialize_timestamp
from copy import deepcopy
from database.current import initialize_database
from datetime import datetime, timedelta, timezone
from detection.adapters import _bounded_get, _decode_utf8, _validate_result, collect_source
from detection.collector import DetectionCollector
from detection.configuration import load_manifest, validate_manifest
from detection.models import CollectedItem, CollectionResult, SourceCollectionError
from detection.normalization import canonical_link, canonical_title
from detection.scout import DetectionScout
from detection.store import DetectionStore
from io import BytesIO
from pathlib import Path
from unittest.mock import patch
from urllib.error import HTTPError
import json
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]


class ScoutRecoveryTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.path = Path(self.temporary.name) / "fixture.db"
        initialize_database(self.path)
        with DetectionStore(self.path) as store:
            store.apply_manifest(load_manifest(ROOT / "config/releases/detection.json"))

        self.start = datetime(2026, 9, 8, 12, tzinfo=timezone.utc)

    def collect_fixture(self, store, *, two_sources=False, at=None, activity=100):
        at = at or self.start
        def collect(source):
            items = [CollectedItem(
                "shared", "Shared opportunity", activity,
                source_item_id="shared", rank=1, provider_time=serialize_timestamp(at),
            )]
            items.append(CollectedItem(
                "other", "Other opportunity", 1, rank=100,
                provider_time=serialize_timestamp(at),
            ))
            return CollectionResult(
                items=tuple(items), events=(), complete=True,
                response_hash="a" * 64, latency_ms=1,
            )
        sources = {"hacker_news_top_stories_v1"}
        if two_sources:
            sources.update({"openai_news_rss_v1", "google_ai_rss_v1"})
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
                (serialize_timestamp(self.start + timedelta(seconds=30)),),
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
            ).fetchone()[0], 9)
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


class CollectionAndScoringTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.path = Path(self.temporary.name) / "fixture.db"
        initialize_database(self.path)
        self.manifest = load_manifest(ROOT / "config/releases/detection.json")
        with DetectionStore(self.path) as store:
            store.apply_manifest(self.manifest)

    def test_normalization_equivalence_is_versioned(self):
        for a, b in (("Publisher’s launch", "Publisher's launch"), ("test–flight", "test-flight"), ("A—B", "A-B")):
            self.assertEqual(canonical_title(a, "canonicalization_v2"), canonical_title(b, "canonicalization_v2"))
            self.assertEqual(canonical_title(a), canonical_title(b))
        for path in ("/a/", "/a//b", "/a/%2F/b", "//a///b/"):
            self.assertEqual(canonical_link("https://example.com" + path, "canonicalization_v2"), "https://example.com" + path)
        self.assertEqual(canonical_link("https://example.com/a/./b/../", "canonicalization_v2"), "https://example.com/a/")
        punctuation = CollectionResult((CollectedItem("id", "‘—’", 1),), (), True, "a" * 64, 1)
        self.assertFalse(_validate_result(punctuation, "canonicalization_v2").complete)

    def test_normalized_collection_and_scout_have_matching_identity_versions(self):
        at = datetime(2026, 9, 9, 12, tzinfo=timezone.utc)
        result = CollectionResult(items=(CollectedItem("id", "Publisher’s test–flight", 1, provider_time=serialize_timestamp(at)),),
                                  events=(), complete=True, response_hash="a" * 64, latency_ms=1)
        with DetectionStore(self.path) as store, patch("detection.collector.collect_source", return_value=result):
            DetectionCollector(store).run_due(now=at, source_ids={"openai_news_rss_v1"})
            DetectionScout(store).run(now=at)
            trend = store.connection.execute("SELECT * FROM trends").fetchone()
            candidate = store.connection.execute("SELECT * FROM trend_candidates").fetchone()
            self.assertEqual(trend["canonical_key"], "publisher s test flight")
            self.assertEqual(trend["canonicalization_version"], "canonicalization_v2")
            self.assertEqual(candidate["opportunity_identity"], "trend:canonicalization_v2:publisher s test flight")
            self.assertEqual(candidate["canonicalization_version"], "canonicalization_v2")

    def test_normalized_score_keeps_recency_diagnostic_but_not_weighted(self):
        at = datetime(2026, 9, 9, 12, tzinfo=timezone.utc)
        result = CollectionResult(items=(CollectedItem("id", "A durable topic", 1, provider_time=serialize_timestamp(at)),),
                                  events=(), complete=True, response_hash="a" * 64, latency_ms=1)
        with DetectionStore(self.path) as store, patch("detection.collector.collect_source", return_value=result):
            DetectionCollector(store).run_due(now=at, source_ids={"openai_news_rss_v1"})
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
        result = CollectionResult(items=(CollectedItem("id", "Queued topic", 1, provider_time=serialize_timestamp(at)),),
                                  events=(), complete=True, response_hash="a" * 64, latency_ms=1)
        with DetectionStore(self.path) as store, patch("detection.collector.collect_source", return_value=result):
            DetectionCollector(store).run_due(now=at, source_ids={"openai_news_rss_v1"})
            DetectionScout(store).run(now=at)
            with store.connection:
                store.connection.execute(
                    "UPDATE trend_candidates SET eligibility_status='deferred_by_budget', "
                    "eligibility_reason='selection_budget_exhausted', selected_at=NULL, "
                    "selected_thread_id=NULL, last_seen_at=?",
                    (serialize_timestamp(at - timedelta(days=7)),),
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
        with patch("detection.adapters._bounded_get", return_value=(body, {}, "https://openai.com/feed/", [])):
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
        with patch("detection.adapters._bounded_get", return_value=(body, {}, "https://openai.com/feed/", [])):
            for day in ("2026-09-08", "2026-09-09"):
                row.update(canonicalization_version="canonicalization_v2", collection_day=day)
                keys.append(collect_source(row).items[0].source_item_key)
        self.assertNotEqual(*keys)


class CollectionEvidenceTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / "fixture.db"
        self.manifest = load_manifest(ROOT / "config/releases/detection.json")
        initialize_database(self.path)
        with DetectionStore(self.path) as store:
            store.apply_manifest(self.manifest)

    def test_malformed_links_and_secret_diagnostics(self):
        for url in ("https://example.com:bad/path", "https://[bad/path", "https://user:password@example.com/"):
            self.assertIsNone(canonical_link(url))
        self.assertEqual(canonical_link("https://[2001:4860:4860::8888]/a"), "https://[2001:4860:4860::8888]/a")
        text = safe_diagnostic('Authorization: Bearer SECRET https://example.com/?token=PRIVATE api_key="KEY" password=PASS')
        for secret in ("SECRET", "PRIVATE", "KEY", "PASS"):
            self.assertNotIn(secret, text)

    def test_wikimedia_retry_keeps_original_report_date(self):
        start = datetime(2026, 9, 8, 12, tzinfo=timezone.utc)
        with DetectionStore(self.path) as store:
            collector = DetectionCollector(store)
            calls = []
            def collect(source):
                calls.append(source["report_date"])
                raise SourceCollectionError("transport_error", "fixture")
            with patch("detection.collector.collect_source", side_effect=collect):
                collector.run_due(now=start, source_ids={"wikimedia_enwiki_daily_v1"})
                with store.connection:
                    store.connection.execute("UPDATE source_collection_attempts SET next_attempt_at=?", (serialize_timestamp(start),))
                collector.run_due(now=start + timedelta(days=1), source_ids={"wikimedia_enwiki_daily_v1"})
            self.assertEqual(calls, ["2026-09-07", "2026-09-07"])

    def test_undated_provider_item_keeps_first_collection_time(self):
        start = datetime(2026, 9, 8, 12, tzinfo=timezone.utc)
        result = CollectionResult(items=(CollectedItem("stable-guid", "Stable item", 1),), events=(), complete=True, response_hash="a" * 64, latency_ms=1)
        with DetectionStore(self.path) as store, patch("detection.collector.collect_source", return_value=result):
            collector = DetectionCollector(store)
            collector.run_due(now=start, source_ids={"openai_news_rss_v1"})
            collector.run_due(now=start + timedelta(days=1), source_ids={"openai_news_rss_v1"})
            rows = store.connection.execute("SELECT effective_observed_at FROM trend_observations").fetchall()
            self.assertEqual([r[0] for r in rows], ["2026-09-08T12:00:00"] * 2)

    def test_later_contributor_does_not_mutate_completed_observation_or_frozen_replay(self):
        start = datetime(2026, 9, 8, 12, tzinfo=timezone.utc)
        manifest = deepcopy(self.manifest)
        manifest["release_name"] = "duplicate-feed-fixture"
        other = deepcopy(manifest["components"]["detection"]["sources"][0])
        other["stable_id"] = "second_feed"
        manifest["components"]["detection"]["sources"].append(other)
        result = CollectionResult(items=(CollectedItem("guid", "Stable item", 1, canonical_url="https://example.com/story", provider_time=serialize_timestamp(start)),), events=(), complete=True, response_hash="a" * 64, latency_ms=1)
        with DetectionStore(self.path) as store, patch("detection.collector.collect_source", return_value=result):
            store.apply_manifest(manifest)
            collector = DetectionCollector(store)
            collector.run_due(now=start, source_ids={"second_feed"})
            before = tuple(store.connection.execute("SELECT * FROM trend_observations").fetchone())
            scout = DetectionScout(store)
            release = store.active_release()["configuration_release_id"]
            run = scout._materialize_run(start, release, start)
            claim = scout._claim(run, start)
            attempts = scout._freeze_inputs(run, release, start, claim)
            from detection.semantic import freeze_resolution
            freeze_resolution(store.connection, run, manifest["components"]["detection"]["semantic_resolution"],
                              scout.encoder, owner=scout.instance_id, claim_version=claim)
            original = scout._evaluate(run, release, manifest, start, attempts)
            collector.run_due(now=start + timedelta(minutes=1), source_ids={"openai_news_rss_v1"})
            self.assertEqual(tuple(store.connection.execute("SELECT * FROM trend_observations ORDER BY trend_observation_id LIMIT 1").fetchone()), before)
            self.assertEqual(scout._evaluate(run, release, manifest, start, attempts), original)


class FeedTimestampTests(unittest.TestCase):
    def test_adapter_publication_time_survives_collection_and_repeat_poll(self):
        from common.timestamps import parse_timestamp
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "feed.db"
            initialize_database(path)
            with DetectionStore(path) as store:
                store.apply_manifest(load_manifest(ROOT / "config/releases/detection.json"))
                body = b"<rss><channel><item><guid>dated</guid><title>A dated lesson</title><pubDate>Mon, 21 Sep 2026 12:00:00 +0200</pubDate></item></channel></rss>"
                with patch("detection.adapters._bounded_get", return_value=(body, {}, "https://openai.com/news/rss.xml", [])):
                    collector = DetectionCollector(store)
                    for at in ("2026-09-22T12:00:00", "2026-09-22T13:00:00"):
                        collector.run_due(now=parse_timestamp(at), source_ids={"openai_news_rss_v1"})
                rows = store.connection.execute("SELECT provider_time,effective_observed_at,window_start,payload_json FROM trend_observations").fetchall()
                self.assertEqual(len(rows), 2)
                for row in rows:
                    self.assertEqual(tuple(row)[:3], ("2026-09-21T10:00:00", "2026-09-21T10:00:00", "2026-09-21T00:00:00"))
                    self.assertEqual(json.loads(row["payload_json"])["provider_time_status"], "provider_time_valid")


MANIFEST = ROOT / "config" / "releases" / "detection.json"

class DetectionCollectionTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.database_path = Path(self.directory.name) / "development.db"
        initialize_database(self.database_path)
        with DetectionStore(self.database_path) as store:
            store.apply_manifest(load_manifest(MANIFEST))

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
                    source_item_id="stable-item", provider_time=serialize_timestamp(now),
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
                    now=now, source_ids={"openai_news_rss_v1"}
                )[0]
                store.connection.execute(
                    "UPDATE source_collection_attempts SET next_attempt_at=? "
                    "WHERE source_collection_attempt_id=?",
                    (serialize_timestamp(now - timedelta(seconds=1)), first["attempt_id"]),
                )
                store.connection.commit()
                second = collector.run_due(
                    now=now, source_ids={"openai_news_rss_v1"}
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


DOMAINS = ('english', 'ai_tech', 'psychology')

class ConfiguredFeedTests(unittest.TestCase):
    def test_current_rss_sources_collect_metadata_with_rss_and_atom_fixtures(self):
        manifest = load_manifest(ROOT/'config/releases/detection.json')
        sources = manifest['components']['detection']['sources']
        self.assertEqual({s['source_kind'] for s in sources},
                         {'publisher_feed_collector_v1', 'hacker_news_top_stories_v1', 'wikimedia_enwiki_pageviews_v1'})
        self.assertEqual({s['stable_id'] for s in sources}, {
            'openai_news_rss_v1', 'google_ai_rss_v1', 'nature_psychology_rss_v1',
            'sciencedaily_psychology_rss_v1', 'voa_grammar_rss_v1', 'voa_expressions_rss_v1',
            'cambridge_words_rss_v1', 'hacker_news_top_stories_v1', 'wikimedia_enwiki_daily_v1',
        })
        self.assertTrue(all(s['enabled'] and s['secret_ref'] is None for s in sources))
        self.assertEqual([s['independence_group'] for s in sources if s['stable_id'].startswith('voa_')], ['voa', 'voa'])
        payloads = {
            'rss': b'<rss><channel><item><title>A useful lesson</title><guid>lesson</guid><link>https://example.org/lesson</link><pubDate>Tue, 22 Sep 2026 12:00:00 +0200</pubDate><description>Not copied</description></item></channel></rss>',
            'atom': b'<feed xmlns="http://www.w3.org/2005/Atom"><entry><title>A useful lesson</title><id>lesson</id><link rel="self" href="https://example.org/feed-entry"/><link rel="alternate" href="https://example.org/lesson"/><published>2026-09-22T12:00:00+02:00</published><content>Not copied</content></entry></feed>',
        }
        for source in sources:
            if source['source_kind'] != 'publisher_feed_collector_v1':
                continue
            for format, body in payloads.items():
                with self.subTest(source=source['stable_id'], format=format):
                    variant = deepcopy(manifest)
                    index = sources.index(source)
                    variant['components']['detection']['sources'][index]['delivery_format'] = format
                    validate_manifest(variant)
                    config = variant['components']['detection']['sources'][index]
                    row = {**config, 'config_json': json.dumps(config), 'collection_day': '2026-09-22'}
                    with patch('detection.adapters._bounded_get', return_value=(body, {}, source['endpoint_url'], [])):
                        result = collect_source(row)
                    self.assertTrue(result.complete)
                    self.assertEqual(len(result.items), 1)
                    self.assertEqual(result.items[0].canonical_url, 'https://example.org/lesson')
                    self.assertEqual(result.items[0].provider_time, '2026-09-22T10:00:00')
                    self.assertNotIn('Not copied', json.dumps(result.items[0].payload))

    def test_large_publisher_history_is_bounded_and_newest_first(self):
        manifest = load_manifest(ROOT/'config/releases/detection.json')
        source = next(s for s in manifest['components']['detection']['sources'] if s['stable_id']=='openai_news_rss_v1')
        entries = ''.join(f'<item><title>Lesson {n}</title><guid>{n}</guid><pubDate>2026-09-22T10:{n//60:02}:{n%60:02}+00:00</pubDate></item>' for n in range(105))
        row = {**source, 'config_json': json.dumps(source), 'collection_day': '2026-09-22'}
        with patch('detection.adapters._bounded_get', return_value=(f'<rss><channel>{entries}</channel></rss>'.encode(), {}, source['endpoint_url'], [])):
            result = collect_source(row)
        self.assertTrue(result.complete)
        self.assertEqual(len(result.items), 100)
        self.assertEqual([i.source_item_id for i in result.items], [str(n) for n in reversed(range(5,105))])
        self.assertEqual(result.events[0].disposition, 'excluded_out_of_scope')
