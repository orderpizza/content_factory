"""Offline safety regressions for the follow-up audit repairs."""

from copy import deepcopy
from contextlib import redirect_stdout
from datetime import datetime, timedelta, timezone
from pathlib import Path
from io import BytesIO, StringIO
from urllib.error import HTTPError
from urllib.parse import parse_qs, urlsplit
from unittest.mock import patch
import json
import runpy
import tempfile
import unittest

from common.diagnostics import safe_diagnostic
from common.legacy import RetiredOperationError
from database.migrations import connect, migrate_detection_dashboard, migrate_editorial_workflow, migrate_detection_safety
from dashboard import render_detection_dashboard, render_workflow_trace
from dashboard.detection import AUTO_REFRESH_SCRIPT, AUTO_REFRESH_CSP, _worker_freshness
from detection.collector import DetectionCollector
from detection.configuration import ConfigurationError, load_manifest, validate_manifest
from detection.models import CollectedItem, CollectionResult, SourceCollectionError
from detection.normalization import canonical_link
from detection.scout import DetectionScout
from semantic_fixture import upgrade_semantic_fixture
from detection.store import DetectionStore
from posting.agent import BlueskyPublisher
from workflow import AdaptationWorker, DeterminationWorker, IdeaIntakeWorker, PipelineRunner, VisualRenderer, WorkflowStore


ROOT = Path(__file__).resolve().parents[1]


class RemainingRepairTests(unittest.TestCase):
    def test_instagram_probe_uses_root_env_and_current_version_without_leaking_token(self):
        root = Path(self.tmp.name)
        (root / ".env").write_text(
            "INSTAGRAM_USER_ID=123456\nINSTAGRAM_ACCESS_TOKEN=local-fixture-token\n"
            "META_GRAPH_API_VERSION=v24.0\nINSTAGRAM_GRAPH_API_VERSION=v23.0\n",
            encoding="utf-8",
        )
        main = runpy.run_path(str(ROOT / "scripts/test_instagram_credentials.py"))["main"]
        output = StringIO()
        with patch.dict(main.__globals__, {"ROOT": root}), patch.dict("os.environ", {}, clear=True), \
                patch("sys.argv", ["probe"]), patch.dict(main.__globals__) as namespace:
            from unittest.mock import MagicMock
            transport = MagicMock()
            transport.return_value.__enter__.return_value.read.return_value = b'{"id":"123456","username":"fixture"}'
            namespace["urlopen"] = transport
            with redirect_stdout(output):
                main()
            request = transport.call_args.args[0]
            self.assertEqual(urlsplit(request.full_url).path, "/v24.0/123456")
            self.assertEqual(parse_qs(urlsplit(request.full_url).query)["access_token"], ["local-fixture-token"])
            self.assertNotIn("local-fixture-token", output.getvalue())
            transport.side_effect = HTTPError(
                request.full_url, 401, "Unauthorized", {},
                BytesIO(b'{"error":{"code":190,"message":"bad local-fixture-token"}}'),
            )
            with self.assertRaises(SystemExit) as failure:
                main()
            self.assertIn("190", str(failure.exception))
            self.assertNotIn("local-fixture-token", str(failure.exception))

        with patch.dict(main.__globals__, {"ROOT": root}), \
                patch.dict("os.environ", {"INSTAGRAM_ACCESS_TOKEN": "process-fixture-token"}, clear=True), \
                patch("sys.argv", ["probe", "--local-only"]), redirect_stdout(StringIO()) as output:
            main()
            report = json.loads(output.getvalue())
            self.assertEqual(report["token_source"], "process_environment")
            self.assertEqual(report["token_length"], len("process-fixture-token"))
            self.assertFalse(report["network_calls_made"])
            self.assertNotIn("process-fixture-token", output.getvalue())

    def test_dashboard_refresh_is_visibility_gated_and_csp_hashed(self):
        from hashlib import sha256
        from base64 import b64encode
        expected = "'sha256-" + b64encode(sha256(AUTO_REFRESH_SCRIPT.encode()).digest()).decode() + "'"
        self.assertEqual(AUTO_REFRESH_CSP, expected)
        self.assertIn("document.hidden", AUTO_REFRESH_SCRIPT)
        self.assertIn("visibilitychange", AUTO_REFRESH_SCRIPT)
        self.assertIn("clearTimeout(timer)", AUTO_REFRESH_SCRIPT)
        with DetectionStore(self.path, read_only=True) as store:
            html = render_detection_dashboard(store.connection)
        self.assertNotIn("http-equiv='refresh'", html)
        self.assertIn(AUTO_REFRESH_SCRIPT, html)

    def test_idle_worker_state_does_not_mask_old_heartbeat(self):
        at = datetime(2026, 9, 9, 12, tzinfo=timezone.utc)
        worker = {"worker_type": "trend_source_collector", "state": "idle", "last_seen_at": at.isoformat()}
        self.assertEqual(_worker_freshness(worker, at), "fresh heartbeat")
        self.assertEqual(_worker_freshness(worker, at + timedelta(minutes=21)), "late heartbeat")
        self.assertEqual(_worker_freshness(worker, at + timedelta(minutes=46)), "stale heartbeat")

        workflow = {"worker_type": "posting_agent", "state": "idle", "last_seen_at": at.isoformat()}
        self.assertEqual(_worker_freshness(workflow, at + timedelta(seconds=30)), "fresh heartbeat")
        self.assertEqual(_worker_freshness(workflow, at + timedelta(seconds=31)), "late heartbeat")
        self.assertEqual(_worker_freshness(workflow, at + timedelta(seconds=91)), "stale heartbeat")

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / "fixture.db"
        self.manifest = load_manifest(ROOT / "config/releases/detection.json")
        migrate_detection_dashboard(self.path)
        migrate_editorial_workflow(self.path)
        migrate_detection_safety(self.path)
        with DetectionStore(self.path) as store:
            store.apply_manifest(self.manifest)
        upgrade_semantic_fixture(self.path)

    def route(self, store):
        return store.register_capability("english", enabled=True, generation_ready=True, outputs=[{
            "platform": "instagram", "account": "fixture", "content_format": "placeholder", "ready": True,
        }])

    def human(self, store):
        request = store.create_human_idea("Explain a useful learning habit", command_id="idea")
        row = store.connection.execute("SELECT * FROM intake_requests WHERE intake_request_id=?", (request,)).fetchone()
        return row["thread_id"]

    def version(self, store, thread):
        return store.connection.execute("SELECT row_version FROM content_threads WHERE thread_id=?", (thread,)).fetchone()[0]

    def test_expired_claim_cannot_finalize_without_reassignment(self):
        with WorkflowStore(self.path) as store:
            self.human(store)
            row = store.claim("intake_requests", "intake_request_id", "old")
            with store.connection:
                store.connection.execute("UPDATE intake_requests SET lease_expires_at='2000-01-01T00:00:00+00:00'")
            with self.assertRaisesRegex(RuntimeError, "stale claim"):
                store.clarify_intake(row, "Must not persist")
            self.assertEqual(store.connection.execute("SELECT COUNT(*) FROM thread_messages").fetchone()[0], 1)

    def test_expired_local_claim_is_recovered_with_fencing_and_attempt_limit(self):
        with WorkflowStore(self.path) as store:
            self.human(store)
            old = store.claim("intake_requests", "intake_request_id", "old")
            with store.connection:
                store.connection.execute("UPDATE intake_requests SET lease_expires_at='2000-01-01T00:00:00+00:00'")
            new = store.claim("intake_requests", "intake_request_id", "new")
            self.assertGreater(new["claim_version"], old["claim_version"])
            with self.assertRaises(RuntimeError):
                store.clarify_intake(old, "stale")
            with store.connection:
                store.connection.execute("UPDATE intake_requests SET lease_expires_at='2000-01-01T00:00:00+00:00',attempt_count=attempt_limit")
            self.assertIsNone(store.claim("intake_requests", "intake_request_id", "last"))
            self.assertEqual(store.connection.execute("SELECT status FROM intake_requests").fetchone()[0], "failed")

    def test_model_history_prevents_automatic_claim_retry(self):
        with WorkflowStore(self.path) as store:
            self.human(store)
            row = store.claim("intake_requests", "intake_request_id", "old")
            with store.connection:
                store.connection.execute("UPDATE intake_requests SET lease_expires_at='2000-01-01T00:00:00+00:00'")
                store.connection.execute(
                    "INSERT INTO model_invocations(phase,entity_type,entity_id,attempt_ordinal,request_version,prompt_version,schema_version,request_hash,outcome,started_at) "
                    "VALUES ('intake','intake_request',?,1,'fixture','fixture','fixture',?,'started','2000-01-01T00:00:00+00:00')",
                    (row["intake_request_id"], "a" * 64),
                )
            self.assertIsNone(store.claim("intake_requests", "intake_request_id", "new"))
            self.assertEqual(store.connection.execute("SELECT status FROM intake_requests").fetchone()[0], "failed")

    def test_closed_thread_cancellation_commits_without_creating_children(self):
        with WorkflowStore(self.path) as store:
            thread = self.human(store)
            worker = IdeaIntakeWorker(store)
            row = store.claim("intake_requests", "intake_request_id", worker.instance_id)
            with store.connection:
                store.connection.execute("UPDATE content_threads SET status='cancelled' WHERE thread_id=?", (thread,))
            self.assertIsNone(worker._process(row))
            self.assertEqual(store.connection.execute("SELECT status FROM intake_requests").fetchone()[0], "cancelled")
            self.assertEqual(store.connection.execute("SELECT COUNT(*) FROM brief_revisions").fetchone()[0], 0)

    def test_cancellation_fences_every_downstream_finalizer(self):
        stages = [
            ("determination_requests", "determination_request_id", DeterminationWorker, "determination_decisions"),
            ("generation_runs", "generation_run_id", PipelineRunner, "canonical_contents"),
            ("adaptation_runs", "adaptation_run_id", AdaptationWorker, "content_packages"),
            ("render_runs", "render_run_id", lambda s: VisualRenderer(s, Path(self.tmp.name) / "assets"), "review_requests"),
        ]
        with WorkflowStore(self.path) as store:
            self.route(store)
            thread = self.human(store)
            IdeaIntakeWorker(store).run_once()
            for table, key, factory, children in stages:
                with self.subTest(table=table):
                    worker = factory(store)
                    row = store.claim(table, key, worker.instance_id)
                    with store.connection:
                        store.connection.execute("UPDATE content_threads SET status='cancelled' WHERE thread_id=?", (thread,))
                    # Exercise the finalizer directly, without filesystem work.
                    if table == "render_runs":
                        result = store.complete_render(row, {}, {})
                    else:
                        result = worker._process(row)
                    self.assertIsNone(result)
                    self.assertEqual(store.connection.execute(f"SELECT status FROM {table} WHERE {key}=?", (row[key],)).fetchone()[0], "cancelled")
                    self.assertEqual(store.connection.execute(f"SELECT COUNT(*) FROM {children}").fetchone()[0], 0)
                    # Fixture-only restoration to advance the next independent boundary.
                    with store.connection:
                        store.connection.execute("UPDATE content_threads SET status='open' WHERE thread_id=?", (thread,))
                        store.connection.execute(f"UPDATE {table} SET status='pending' WHERE {key}=?", (row[key],))
                    worker.run_once()

    def test_command_versions_receipts_and_input_limits(self):
        with WorkflowStore(self.path) as store:
            thread = self.human(store)
            old = self.version(store, thread)
            IdeaIntakeWorker(store).run_once()
            self.assertGreater(self.version(store, thread), old)
            for version in (None, old):
                with self.assertRaises(ValueError):
                    store.continue_human_thread(thread, "Add a daily example", command_id="reply", expected_row_version=version)
            version = self.version(store, thread)
            reply = store.continue_human_thread(thread, "Add a daily example", command_id="reply", expected_row_version=version)
            self.assertEqual(reply, store.continue_human_thread(thread, "Add a daily example", command_id="reply", expected_row_version=version))
            with self.assertRaises(ValueError):
                store.continue_human_thread(thread, "Different input", command_id="reply", expected_row_version=version)
            with self.assertRaises(ValueError):
                store.create_human_idea("An idea", command_id=" ")

    def test_aggregate_conversation_limit_is_visible_failure_not_stranded_claim(self):
        with WorkflowStore(self.path) as store:
            thread = self.human(store)
            with store.connection:
                for sequence in range(2, 7):
                    message = store.connection.execute("INSERT INTO thread_messages(thread_id,sequence_number,author_kind,body,created_at) VALUES (?,?,'human',?,'2026-09-09')", (thread, sequence, "a" * 8000))
                store.connection.execute("UPDATE intake_requests SET context_json=?", (json.dumps({"kind": "human_conversation", "last_message_id": message.lastrowid}),))
            self.assertIsNone(IdeaIntakeWorker(store).run_once())
            row = store.connection.execute("SELECT status,failure_detail FROM intake_requests").fetchone()
            self.assertEqual(tuple(row), ("failed", "input_too_large"))
            self.assertIn("input_too_large", render_workflow_trace(store.connection))

    def test_fixture_registration_is_idempotent_and_catalog_is_release_scoped(self):
        with WorkflowStore(self.path) as store:
            first = self.route(store)
            self.assertEqual(self.route(store), first)
            with self.assertRaisesRegex(ValueError, "different input"):
                store.register_capability("english", enabled=False, generation_ready=False, outputs=[])
            with DetectionStore(self.path) as detection:
                newer = deepcopy(self.manifest)
                newer["release_name"] = "new-fixture-release"
                detection.apply_manifest(newer)
            self.assertEqual(store.catalog(), [])

    def test_pending_and_clarification_threads_are_visible_once(self):
        with WorkflowStore(self.path) as store:
            store.create_human_idea("maybe", command_id="short")
            self.assertIn("pending", render_workflow_trace(store.connection))
            IdeaIntakeWorker(store).run_once()
            html = render_workflow_trace(store.connection)
            self.assertIn("needs_clarification", html)
            self.assertIn("What topic", html)
            self.assertEqual(html.count("<article>"), 1)

    def test_outer_dashboard_snapshot_is_preserved(self):
        connection = connect(self.path, read_only=True)
        try:
            connection.execute("BEGIN")
            render_detection_dashboard(connection)
            self.assertTrue(connection.in_transaction)
            render_workflow_trace(connection)
        finally:
            connection.close()

    def test_review_commands_never_create_delivery_authorization(self):
        with WorkflowStore(self.path) as store:
            for review_id in (1, -1):
                with self.assertRaisesRegex(ValueError, "does not exist"):
                    store.approve_review(review_id, row_version=1, command_id="approve")
            self.assertEqual(store.connection.execute("SELECT COUNT(*) FROM post_requests").fetchone()[0], 0)

    def test_legacy_publishing_boundary_fails_before_network(self):
        with patch("socket.socket.connect", side_effect=AssertionError("network forbidden")):
            with self.assertRaises(RetiredOperationError):
                BlueskyPublisher("fixture", "secret").publish("text")

    def test_numeric_booleans_and_obsolete_cluster_configuration_are_rejected(self):
        for key in ("trust_weight", "quota_limit"):
            value = deepcopy(self.manifest)
            value["components"]["detection"]["sources"][0][key] = True
            with self.assertRaises(ConfigurationError):
                validate_manifest(value)
        value = deepcopy(self.manifest)
        value["schema_version"] = True
        with self.assertRaises(ConfigurationError):
            validate_manifest(value)
        value = deepcopy(self.manifest)
        value["components"]["detection"]["cluster_aliases"] = []
        with self.assertRaises(ConfigurationError):
            validate_manifest(value)

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
                    store.connection.execute("UPDATE source_collection_attempts SET next_attempt_at=?", (start.isoformat(),))
                collector.run_due(now=start + timedelta(days=1), source_ids={"wikimedia_enwiki_daily_v1"})
            self.assertEqual(calls, ["2026-09-07", "2026-09-07"])

    def test_undated_provider_item_keeps_first_collection_time(self):
        start = datetime(2026, 9, 8, 12, tzinfo=timezone.utc)
        result = CollectionResult(items=(CollectedItem("stable-guid", "Stable item", 1),), events=(), complete=True, response_hash="a" * 64, latency_ms=1)
        with DetectionStore(self.path) as store, patch("detection.collector.collect_source", return_value=result):
            collector = DetectionCollector(store)
            collector.run_due(now=start, source_ids={"nasa_recently_published_rss_v1"})
            collector.run_due(now=start + timedelta(days=1), source_ids={"nasa_recently_published_rss_v1"})
            rows = store.connection.execute("SELECT effective_observed_at FROM trend_observations").fetchall()
            self.assertEqual([r[0] for r in rows], [start.isoformat()] * 2)

    def test_later_contributor_does_not_mutate_completed_observation_or_frozen_replay(self):
        start = datetime(2026, 9, 8, 12, tzinfo=timezone.utc)
        manifest = deepcopy(self.manifest)
        manifest["release_name"] = "duplicate-feed-fixture"
        other = deepcopy(manifest["components"]["detection"]["sources"][0])
        other["stable_id"] = "second_feed"
        manifest["components"]["detection"]["sources"].append(other)
        result = CollectionResult(items=(CollectedItem("guid", "Stable item", 1, canonical_url="https://example.com/story", provider_time=start.isoformat()),), events=(), complete=True, response_hash="a" * 64, latency_ms=1)
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
            collector.run_due(now=start + timedelta(minutes=1), source_ids={"nasa_recently_published_rss_v1"})
            self.assertEqual(tuple(store.connection.execute("SELECT * FROM trend_observations ORDER BY trend_observation_id LIMIT 1").fetchone()), before)
            self.assertEqual(scout._evaluate(run, release, manifest, start, attempts), original)


if __name__ == "__main__":
    unittest.main()
