"""Offline event-resolution boundaries; no model downloads or API calls."""

from copy import deepcopy
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch
import json
import sqlite3
import tempfile
import unittest

from database.migrations import SchemaError, migrate_detection_dashboard, migrate_editorial_workflow, migrate_detection_safety, migrate_production_workflow, migrate_semantic_events
from detection.collector import DetectionCollector
from detection.configuration import ConfigurationError, load_manifest, validate_manifest
from detection.hybrid import evaluate
from detection.models import CollectedItem, CollectionResult
from detection.normalization import canonical_title
from detection.scout import DetectionScout
from detection.semantic import resolve, load_resolution
from detection.store import DetectionStore
from semantic_fixture import upgrade_semantic_fixture

ROOT = Path(__file__).resolve().parents[1]
AT = datetime(2026, 9, 14, 12, tzinfo=timezone.utc)


class FakeEncoder:
    def __init__(self, vectors=None):
        self.calls = []
        self.vectors = vectors or {}

    def encode(self, texts, policy):
        self.calls.append(list(texts))
        return [self.vectors.get(t, [1.0] + [0.0] * 383) for t in texts]


def observation(title, index, *, hours=0, source="nasa", group=None):
    return {"canonical_key": canonical_title(title, "canonicalization_v2"), "title": title,
            "trend_id": index, "trend_observation_id": index, "canonical_url": None,
            "effective_observed_at": (AT - timedelta(hours=hours)).isoformat(),
            "window_end": AT.isoformat(), "source_kind": "publisher_feed_collector_v1",
            "independence_group": group or source, "stable_id": source}


class SemanticResolutionTests(unittest.TestCase):
    def setUp(self):
        self.manifest = load_manifest(ROOT / "config/releases/detection.json")
        self.policy = self.manifest["components"]["detection"]["semantic_resolution"]

    def test_paraphrases_link_once_per_lexical_cluster(self):
        rows = [observation("OpenAI launches Atlas browser", 1), observation("OpenAI unveils Atlas web browser", 2)]
        rows += [{**rows[0], "trend_observation_id": i} for i in range(3, 50)]
        encoder = FakeEncoder()
        result = resolve(rows, AT, self.policy, encoder)
        self.assertEqual(result["pairs"][0]["outcome"], "linked")
        self.assertEqual(len({n["resolved_key"] for n in result["clusters"]}), 1)
        self.assertEqual(len(encoder.calls[0]), 2)
        self.assertEqual(result, resolve(list(reversed(rows)), AT, self.policy, FakeEncoder()))

    def test_similarity_never_overrides_conflicting_event_signals(self):
        cases = [
            ("NASA launches Artemis 2 mission", "NASA launches Artemis 3 mission", "numeric_conflict"),
            ("OpenAI launches Atlas browser", "OpenAI launches Orion browser", "entity_conflict"),
            ("OpenAI launches Atlas browser", "OpenAI recalls Atlas browser", "event_conflict"),
            ("OpenAI launches Atlas browser", "OpenAI will not launch Atlas browser", "negation_conflict"),
        ]
        for a, b, reason in cases:
            with self.subTest(reason=reason):
                encoder = FakeEncoder()
                result = resolve([observation(a, 1), observation(b, 2)], AT, self.policy, encoder)
                self.assertEqual(result["pairs"][0]["reason"], reason)
                self.assertEqual(result["pairs"][0]["outcome"], "separate")
                self.assertFalse(encoder.calls)

    def test_uncertainty_time_and_resource_limits_keep_singletons(self):
        a, b = "OpenAI launches Atlas browser", "OpenAI unveils Atlas web browser"
        for rows in ([observation(a, 1), observation(b, 2, hours=30)],
                     [observation("OpenAI Atlas news", 1), observation("OpenAI Atlas overview", 2)]):
            result = resolve(rows, AT, self.policy, FakeEncoder())
            self.assertEqual(len({n["resolved_key"] for n in result["clusters"]}), 2)
        policy = {**self.policy, "max_clusters": 1}
        encoder = FakeEncoder()
        self.assertEqual(resolve([observation(a, 1), observation(b, 2)], AT, policy, encoder)["compared_pairs"], 0)
        self.assertFalse(encoder.calls)
        vector = [0.7, (1 - 0.7 ** 2) ** 0.5] + [0.] * 382
        result = resolve([observation(a, 1), observation(b, 2)], AT, self.policy, FakeEncoder({b: vector}))
        self.assertEqual(result["pairs"][0]["outcome"], "unresolved")

    def test_complete_link_prevents_transitive_bridge(self):
        titles = ["OpenAI launches Atlas browser", "OpenAI unveils Atlas web browser", "OpenAI releases Atlas browser today"]
        vectors = {titles[0]: [1., 0.] + [0.] * 382,
                   titles[1]: [.9, .435889894] + [0.] * 382,
                   titles[2]: [.65, .759934208] + [0.] * 382}
        result = resolve([observation(t, i) for i, t in enumerate(titles, 1)], AT, self.policy, FakeEncoder(vectors))
        self.assertEqual(len({n["resolved_key"] for n in result["clusters"]}), 2)
        self.assertIn("complete_link_or_group_limit", {p["reason"] for p in result["pairs"]})

    def test_reversed_actor_roles_do_not_link(self):
        encoder = FakeEncoder()
        result = resolve([observation("Apple acquires Google", 1), observation("Google acquires Apple", 2)], AT, self.policy, encoder)
        self.assertEqual(result["pairs"][0]["outcome"], "unresolved")
        self.assertEqual(result["pairs"][0]["reason"], "entity_roles_differ")
        self.assertFalse(encoder.calls)

    def test_bad_model_output_and_configuration_fail_closed(self):
        a, b = "OpenAI launches Atlas browser", "OpenAI unveils Atlas web browser"
        with self.assertRaisesRegex(ValueError, "invalid vector"):
            resolve([observation(a, 1), observation(b, 2)], AT, self.policy, FakeEncoder({a: [float("nan")] * 384}))
        for key, value in (("link_threshold", float("nan")), ("max_pairs", True), ("cpu_threads", 999),
                           ("model_revision", "main"), ("separate_threshold", 1.0)):
            with self.subTest(key=key):
                manifest = deepcopy(self.manifest)
                manifest["components"]["detection"]["semantic_resolution"][key] = value
                with self.assertRaises(ConfigurationError):
                    validate_manifest(manifest)


class SemanticScoutTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / "semantic.db"
        for migrate in (migrate_detection_dashboard, migrate_editorial_workflow, migrate_detection_safety):
            migrate(self.path)
        self.manifest = load_manifest(ROOT / "config/releases/detection.json")
        with DetectionStore(self.path) as store:
            store.apply_manifest(self.manifest)
        upgrade_semantic_fixture(self.path)

    def collect(self, store, titles, *, at=AT):
        def response(source):
            title = titles[source["stable_id"]]
            return CollectionResult(items=(CollectedItem(title, title, 100, rank=1, provider_time=at.isoformat()),),
                                    events=(), complete=True, response_hash="a" * 64, latency_ms=1)
        with patch("detection.collector.collect_source", side_effect=response):
            DetectionCollector(store).run_due(now=at, source_ids=set(titles))

    def test_inferred_merge_cannot_manufacture_breadth_or_shortlist_eligibility(self):
        with DetectionStore(self.path) as store:
            self.collect(store, {"nasa_recently_published_rss_v1": "OpenAI launches Atlas browser",
                                 "hacker_news_top_stories_v1": "OpenAI unveils Atlas web browser"})
            result = DetectionScout(store, encoder=FakeEncoder()).run(now=AT)
            self.assertEqual(result["candidate_count"], 1)
            self.assertEqual(result["selected_count"], 0)
            candidate = store.connection.execute("SELECT * FROM trend_candidates").fetchone()
            score = json.loads(candidate["score_breakdown_json"])
            self.assertAlmostEqual(score["breadth"], 1/3)
            self.assertIn("bootstrap_requires_two_independent_groups", candidate["eligibility_reason"])
            self.assertEqual(len(score["source_components"]), 1)
            self.assertEqual(store.connection.execute("SELECT COUNT(*) FROM candidate_observation_memberships").fetchone()[0], 2)
            self.assertEqual(store.connection.execute("SELECT COUNT(*) FROM content_threads").fetchone()[0], 0)

    def test_frozen_replay_uses_no_encoder_and_is_immutable(self):
        with DetectionStore(self.path) as store:
            self.collect(store, {"nasa_recently_published_rss_v1": "OpenAI launches Atlas browser",
                                 "hacker_news_top_stories_v1": "OpenAI unveils Atlas web browser"})
            encoder = FakeEncoder(); scout = DetectionScout(store, encoder=encoder)
            with patch.object(scout, "_finalize", side_effect=RuntimeError("after resolution")):
                with self.assertRaises(RuntimeError): scout.run(now=AT)
            before = load_resolution(store.connection, 1)
            release_id = store.active_release()["configuration_release_id"]
            expected = evaluate(store.connection, 1, release_id, self.manifest)
            self.collect(store, {"nasa_recently_published_rss_v1": "NASA launches Artemis 3 mission"}, at=AT + timedelta(hours=1))
            self.assertEqual(expected, evaluate(store.connection, 1, release_id, self.manifest))
            newer = deepcopy(self.manifest); newer["release_name"] = "changed-threshold"
            newer["components"]["detection"]["semantic_resolution"]["link_threshold"] = .99
            # Freeze is independent even of a later activated resolver policy.
            store.apply_manifest(newer)
            self.assertEqual(expected, evaluate(store.connection, 1, release_id, self.manifest))
            with self.assertRaisesRegex(ValueError, "frozen configuration"):
                evaluate(store.connection, 1, release_id, newer)
            with store.connection:
                store.connection.execute("UPDATE scout_evaluation_runs SET next_attempt_at=?", (AT.isoformat(),))
            store.apply_manifest(self.manifest)
            with patch.object(encoder, "encode", side_effect=AssertionError("replay must not infer")):
                scout.run(now=AT + timedelta(hours=2))
            self.assertEqual(before, load_resolution(store.connection, 1))
            for sql in ("UPDATE scout_event_resolutions SET resolution_json='{}'", "DELETE FROM scout_event_resolutions"):
                with self.assertRaises(sqlite3.IntegrityError), store.connection:
                    store.connection.execute(sql)
            self.assertFalse(migrate_semantic_events(self.path))

    def test_linking_does_not_increase_any_scoring_component(self):
        with DetectionStore(self.path) as store:
            other = "OpenAI unveils Atlas web browser"
            self.collect(store, {"nasa_recently_published_rss_v1": "OpenAI launches Atlas browser",
                                 "hacker_news_top_stories_v1": other})
            separate = FakeEncoder({other: [0., 1.] + [0.] * 382})
            DetectionScout(store, encoder=separate).run(now=AT)
            before = [tuple(r) for r in store.connection.execute("SELECT * FROM topic_snapshots ORDER BY topic_snapshot_id")]
            parts = [json.loads(r[0]) for r in store.connection.execute("SELECT score_breakdown_json FROM trend_candidates")]
            result = DetectionScout(store, encoder=FakeEncoder()).run(now=AT + timedelta(minutes=15))
            self.assertEqual(result["candidate_count"], 1)
            merged = json.loads(store.connection.execute("SELECT score_breakdown_json FROM topic_snapshots ORDER BY topic_snapshot_id DESC LIMIT 1").fetchone()[0])
            for key in ("score", "breadth", "momentum", "prominence", "persistence", "reliability"):
                self.assertLessEqual(merged[key], max(p[key] for p in parts))
            self.assertEqual(before, [tuple(r) for r in store.connection.execute("SELECT * FROM topic_snapshots WHERE topic_snapshot_id<=2 ORDER BY topic_snapshot_id")])

    def test_stale_owner_cannot_persist_resolution(self):
        with DetectionStore(self.path) as store:
            self.collect(store, {"nasa_recently_published_rss_v1": "OpenAI launches Atlas browser",
                                 "hacker_news_top_stories_v1": "OpenAI unveils Atlas web browser"})
            encoder = FakeEncoder()
            original = encoder.encode
            def steal(texts, policy):
                store.connection.execute("UPDATE scout_evaluation_runs SET claim_version=claim_version+1")
                store.connection.commit()
                return original(texts, policy)
            with patch.object(encoder, "encode", side_effect=steal), self.assertRaisesRegex(RuntimeError, "claim lost"):
                DetectionScout(store, encoder=encoder).run(now=AT)
            self.assertEqual(store.connection.execute("SELECT COUNT(*) FROM scout_event_resolutions").fetchone()[0], 0)

    def test_expired_inference_cannot_freeze_or_create_candidates(self):
        with DetectionStore(self.path) as store:
            self.collect(store, {"nasa_recently_published_rss_v1": "OpenAI launches Atlas browser",
                                 "hacker_news_top_stories_v1": "OpenAI unveils Atlas web browser"})
            with patch("detection.semantic.monotonic", side_effect=[0, 601]), self.assertRaisesRegex(RuntimeError, "claim lost"):
                DetectionScout(store, encoder=FakeEncoder()).run(now=AT)
            self.assertEqual(store.connection.execute("SELECT COUNT(*) FROM scout_event_resolutions").fetchone()[0], 0)
            self.assertEqual(store.connection.execute("SELECT COUNT(*) FROM trend_candidates").fetchone()[0], 0)

    def test_selected_event_cannot_seed_again_when_its_root_leaves_the_window(self):
        with DetectionStore(self.path) as store:
            other = "OpenAI unveils Atlas web browser"
            self.collect(store, {"nasa_recently_published_rss_v1": "OpenAI launches Atlas browser",
                                 "hacker_news_top_stories_v1": other})
            scout = DetectionScout(store, encoder=FakeEncoder())
            evaluate_original = scout._evaluate
            def eligible_fixture(*args):
                result = evaluate_original(*args)
                # This test isolates the handoff identity fence; scoring gates
                # and semantic credit are exercised independently above.
                for candidate in result["candidates"]:
                    candidate.update(eligible=True, eligibility_reason="fixture_eligible")
                return result
            with patch.object(scout, "_evaluate", side_effect=eligible_fixture):
                self.assertEqual(scout.run(now=AT)["selected_count"], 1)
                later = AT + timedelta(days=22)
                # Sources are collected in stable-ID order: HN owns the first
                # trend ID/root. Only the NASA wording is observed again.
                survivor = "OpenAI launches Atlas browser"
                self.collect(store, {"nasa_recently_published_rss_v1": survivor,
                                     "hacker_news_top_stories_v1": survivor}, at=later)
                self.assertEqual(scout.run(now=later)["selected_count"], 0)
            self.assertEqual(store.connection.execute("SELECT COUNT(*) FROM content_threads").fetchone()[0], 1)
            self.assertEqual(store.connection.execute("SELECT eligibility_reason FROM trend_candidates ORDER BY trend_candidate_id DESC LIMIT 1").fetchone()[0], "resolved_event_already_owned")

    def test_missing_model_fails_closed_before_scoring(self):
        with DetectionStore(self.path) as store:
            self.collect(store, {"nasa_recently_published_rss_v1": "OpenAI launches Atlas browser",
                                 "hacker_news_top_stories_v1": "OpenAI unveils Atlas web browser"})
            encoder = FakeEncoder()
            with patch.object(encoder, "encode", side_effect=OSError("model unavailable")), self.assertRaises(OSError):
                DetectionScout(store, encoder=encoder).run(now=AT)
            self.assertEqual(store.connection.execute("SELECT COUNT(*) FROM scout_event_resolutions").fetchone()[0], 0)
            self.assertEqual(store.connection.execute("SELECT status FROM scout_evaluation_runs").fetchone()[0], "retry_wait")
            self.assertEqual(store.connection.execute("SELECT COUNT(*) FROM trend_candidates").fetchone()[0], 0)


class SemanticMigrationTests(unittest.TestCase):
    def test_migration_refuses_unfinished_freeze_and_preserves_completed_evidence(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "migration.db"
            for migrate in (migrate_detection_dashboard, migrate_editorial_workflow, migrate_detection_safety):
                migrate(path)
            with DetectionStore(path) as store:
                store.apply_manifest(load_manifest(ROOT / "config/releases/detection.json"))
            migrate_production_workflow(path)
            with DetectionStore(path) as store:
                scout = DetectionScout(store, encoder=FakeEncoder())
                release_id = store.active_release()["configuration_release_id"]
                run_id = scout._materialize_run(AT, release_id, AT)
                claim = scout._claim(run_id, AT)
                scout._freeze_inputs(run_id, release_id, AT, claim)
                before = tuple(store.connection.execute("SELECT * FROM scout_frozen_evidence").fetchone())
                ledger = [tuple(r) for r in store.connection.execute("SELECT * FROM schema_migrations")]
                with self.assertRaisesRegex(SchemaError, "unfinished frozen"):
                    migrate_semantic_events(path)
                self.assertEqual(store.connection.execute("PRAGMA user_version").fetchone()[0], 4)
                self.assertIsNone(store.connection.execute("SELECT name FROM sqlite_master WHERE name='scout_event_resolutions'").fetchone())
                with store.connection:
                    store.connection.execute("UPDATE scout_evaluation_runs SET status='completed' WHERE scout_evaluation_run_id=?", (run_id,))
                self.assertTrue(migrate_semantic_events(path))
                self.assertEqual(before, tuple(store.connection.execute("SELECT * FROM scout_frozen_evidence").fetchone()))
                self.assertEqual(ledger, [tuple(r) for r in store.connection.execute("SELECT * FROM schema_migrations WHERE version<=4")])
                self.assertEqual(store.connection.execute("SELECT COUNT(*) FROM scout_event_resolutions").fetchone()[0], 0)


if __name__ == "__main__":
    unittest.main()
