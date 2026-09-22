"""Dashboard; offline tests use temporary databases and fake providers."""

from common.timestamps import serialize_timestamp
from dashboard import render_detection_dashboard, render_workflow_trace
from dashboard.detection import _worker_freshness, render_detection_dashboard
from dashboard.refresh import AUTO_REFRESH_CSP, AUTO_REFRESH_SCRIPT
from database.current import connect, initialize_database
from datetime import datetime, timedelta, timezone
from detection.collector import DetectionCollector
from detection.configuration import load_manifest
from detection.models import CollectedItem, CollectionResult
from detection.reporting import summarize_scout
from detection.scout import DetectionScout
from detection.store import DetectionStore
from http.server import ThreadingHTTPServer
from pathlib import Path
from test_gemini_workflow import FakeGeminiClient, brief
from threading import Thread
from time import perf_counter
from unittest.mock import patch
from urllib.request import urlopen
from workflow import DeterminationWorker, GeminiDeterminationWorker, GeminiIntakeWorker, IdeaIntakeWorker, WorkflowStore
from workflow.development import prepare_development_database
import json
import runpy
import tempfile
import test_gemini_workflow as fixtures
import unittest


ROOT = Path(__file__).resolve().parents[1]


class DashboardRefreshTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name)/'test.db'
        prepare_development_database(self.path)

    def _server(self):
        module = runpy.run_path(str(ROOT/'scripts/serve_dashboard.py'))
        handler = type('TestDashboard', (module['DashboardHandler'],), {'database_path':str(self.path)})
        server = ThreadingHTTPServer(('127.0.0.1',0),handler)
        thread = Thread(target=server.serve_forever,daemon=True)
        thread.start()
        def close():
            server.shutdown(); server.server_close(); thread.join()
        self.addCleanup(close)
        return f'http://127.0.0.1:{server.server_port}'

    def test_snapshot_is_bounded_read_only_same_origin_and_terminology_is_correct(self):
        url = self._server()
        with WorkflowStore(self.path) as store:
            before = store.connection.execute('SELECT COUNT(*) FROM storage_samples').fetchone()[0]
            with urlopen(url+'/snapshot?view=threads') as response:
                self.assertEqual(response.headers.get_content_type(),'application/json')
                self.assertIn("connect-src 'self'",response.headers['Content-Security-Policy'])
                payload = json.load(response)
            self.assertNotIn('<script>',payload['html'])
            self.assertIn('Storage observation (advisory for planning)',payload['html'])
            self.assertEqual(store.connection.execute('SELECT COUNT(*) FROM storage_samples').fetchone()[0], before)
            self.assertEqual(store.connection.execute('SELECT COUNT(*) FROM model_invocations').fetchone()[0], 0)
            html = render_detection_dashboard(store.connection)
            self.assertIn('Raw Feed Items',html)
            self.assertIn('<h2>Clusters</h2>',html)
            self.assertNotIn('Detection candidates',html)
            self.assertIn('Opportunities<b>',html)
            self.assertIn('ContentJobs<b>',html)

    def test_browser_refresh_preserves_draft_focus_details_scroll_and_shows_new_state(self):
        from playwright.sync_api import sync_playwright
        with WorkflowStore(self.path) as store:
            store.create_human_idea('Teach a clear business idiom',command_id='browser')
            GeminiIntakeWorker(store,FakeGeminiClient(brief())).run_once()
        url = self._server()
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            try:
                page = browser.new_page(viewport={'width':1280,'height':800})
                errors=[]; navigations=[]
                page.on('pageerror',lambda error: errors.append(str(error)))
                page.on('request',lambda request: navigations.append(request.url) if request.resource_type=='document' else None)
                page.clock.install()
                page.goto(url+'/?thread_id=1')
                page.locator('details').first.evaluate('(e)=>{e.open=true; window.evidence=e;}')
                textarea = page.locator('textarea').last
                textarea.fill('UNSUBMITTED draft remains unchanged')
                textarea.focus()
                page.evaluate('window.draft=document.activeElement; window.scrollTo(0,250); window.scrollBefore=scrollY')
                with WorkflowStore(self.path) as store:
                    GeminiDeterminationWorker(store,FakeGeminiClient(fixtures.GeminiWorkflowTests.decision(store.catalog()))).run_once()
                with page.expect_response('**/snapshot?thread_id=1'):
                    page.clock.run_for(10050)
                page.wait_for_function("() => document.getElementById('refresh-status').textContent.startsWith('Updated at')")
                self.assertIn('ContentJob #1',page.locator('main').inner_text())
                self.assertEqual(textarea.input_value(),'UNSUBMITTED draft remains unchanged')
                self.assertTrue(page.evaluate('document.activeElement===window.draft'))
                self.assertTrue(page.evaluate('window.evidence.isConnected && window.evidence.open'))
                self.assertLess(abs(page.evaluate('scrollY-window.scrollBefore')),3)
                self.assertEqual(len(navigations),1)
                self.assertEqual(errors,[])
                # A transient polling failure never erases the usable snapshot.
                page.route('**/snapshot?thread_id=1',lambda route: route.fulfill(status=503,body='unavailable'),times=1)
                page.clock.run_for(10050)
                page.wait_for_function("() => document.getElementById('refresh-status').textContent.startsWith('Update unavailable')")
                self.assertEqual(textarea.input_value(),'UNSUBMITTED draft remains unchanged')
                with page.expect_response('**/snapshot?thread_id=1'):
                    page.clock.run_for(10050)
                page.wait_for_function("() => document.getElementById('refresh-status').textContent.startsWith('Updated at')")
                # A closed target preserves the unsent draft but disables stale submission.
                with WorkflowStore(self.path) as store:
                    store.connection.execute("UPDATE content_threads SET status='closed',row_version=row_version+1 WHERE thread_id=1")
                    store.connection.commit()
                with page.expect_response('**/snapshot?thread_id=1'):
                    page.clock.run_for(10050)
                page.wait_for_function("() => document.querySelector('[data-stale-draft]') !== null")
                self.assertEqual(textarea.input_value(),'UNSUBMITTED draft remains unchanged')
                self.assertTrue(textarea.locator('..').locator('button').is_disabled())
                self.assertEqual(len(navigations),1)
            finally:
                browser.close()


class OpportunityCountTests(unittest.TestCase):
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


class BoundedDashboardTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.path = Path(self.temporary.name) / "fixture.db"
        initialize_database(self.path)
        self.manifest = load_manifest(ROOT / "config/releases/detection.json")
        with DetectionStore(self.path) as store:
            store.apply_manifest(self.manifest)

    def test_reporting_stays_bounded_with_ten_thousand_operational_rows(self):
        with DetectionStore(self.path) as store:
            with store.connection:
                store.connection.executemany(
                    "INSERT INTO worker_runs(worker_type,instance_id,started_at,status,safe_summary,created_at) VALUES ('fixture','test','2026-09-09T00:00:00','completed',?,'2026-09-09T00:00:00')",
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


class DashboardSnapshotTests(unittest.TestCase):
    def test_dashboard_refresh_is_visibility_gated_and_csp_hashed(self):
        from hashlib import sha256
        from base64 import b64encode
        expected = "'sha256-" + b64encode(sha256(AUTO_REFRESH_SCRIPT.encode()).digest()).decode() + "'"
        self.assertEqual(AUTO_REFRESH_CSP, expected)
        self.assertIn("document.hidden", AUTO_REFRESH_SCRIPT)
        self.assertIn("visibilitychange", AUTO_REFRESH_SCRIPT)
        self.assertIn("clearTimeout(timeout)", AUTO_REFRESH_SCRIPT)
        self.assertNotIn("location.reload", AUTO_REFRESH_SCRIPT)
        self.assertIn("fetch('/snapshot'", AUTO_REFRESH_SCRIPT)
        with DetectionStore(self.path, read_only=True) as store:
            html = render_detection_dashboard(store.connection)
        self.assertNotIn("http-equiv='refresh'", html)
        self.assertIn(AUTO_REFRESH_SCRIPT, html)

    def test_idle_worker_state_does_not_mask_old_heartbeat(self):
        at = datetime(2026, 9, 9, 12, tzinfo=timezone.utc)
        worker = {"worker_type": "trend_source_collector", "state": "idle", "last_seen_at": serialize_timestamp(at)}
        self.assertEqual(_worker_freshness(worker, at), "fresh heartbeat")
        self.assertEqual(_worker_freshness(worker, at + timedelta(minutes=21)), "late heartbeat")
        self.assertEqual(_worker_freshness(worker, at + timedelta(minutes=46)), "stale heartbeat")

        workflow = {"worker_type": "posting_agent", "state": "idle", "last_seen_at": serialize_timestamp(at)}
        self.assertEqual(_worker_freshness(workflow, at + timedelta(seconds=30)), "fresh heartbeat")
        self.assertEqual(_worker_freshness(workflow, at + timedelta(seconds=31)), "late heartbeat")
        self.assertEqual(_worker_freshness(workflow, at + timedelta(seconds=91)), "stale heartbeat")

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / "fixture.db"
        self.manifest = load_manifest(ROOT / "config/releases/detection.json")
        initialize_database(self.path)
        with DetectionStore(self.path) as store:
            store.apply_manifest(self.manifest)

    def test_pending_and_clarification_threads_are_visible_once(self):
        with WorkflowStore(self.path) as store:
            store.create_human_idea("maybe", command_id="short")
            self.assertIn("pending", render_workflow_trace(store.connection))
            IdeaIntakeWorker(store).run_once()
            html = render_workflow_trace(store.connection)
            self.assertIn("needs_clarification", html)
            self.assertIn("What topic", html)
            self.assertEqual(html.count("<article "), 1)

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


MANIFEST = ROOT / "config" / "releases" / "detection.json"

class DetectionDashboardTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.database_path = Path(self.directory.name) / "development.db"
        initialize_database(self.database_path)
        with DetectionStore(self.database_path) as store:
            store.apply_manifest(load_manifest(MANIFEST))

    def test_collection_scout_selection_and_dashboard_feed_share_sqlite_boundary(self):
        now = datetime(2026, 9, 7, 12, 7, tzinfo=timezone.utc)

        collection_time = now
        shared_activity = 1000.0

        def fake_collect(source):
            if source["stable_id"] == "openai_news_rss_v1":
                items = (
                    CollectedItem(
                        "publisher-shared", "Shared Opportunity", shared_activity,
                        rank=1, source_item_id="publisher-shared",
                        canonical_url="https://openai.com/shared",
                        provider_time=serialize_timestamp(collection_time),
                    ),
                    CollectedItem(
                        "publisher-other", "Other Topic", 1.0,
                        rank=100, source_item_id="publisher-other",
                        canonical_url="https://openai.com/other",
                        provider_time=serialize_timestamp(collection_time),
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
                        "openai_news_rss_v1",
                        "hacker_news_top_stories_v1",
                        "google_ai_rss_v1",
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

        connection = connect(self.database_path)
        try:
            connection.execute("UPDATE trend_candidates SET score=CASE canonical_subject WHEN 'Other Topic' THEN .95 ELSE .80 END")
            connection.commit()
            html = render_detection_dashboard(connection)
        finally:
            connection.close()
        self.assertIn("Shared Opportunity", html)
        self.assertIn("Raw Feed Items", html)
        self.assertIn("class='stage-tabs'", html)
        self.assertIn("class='stage-table'", html)
        self.assertIn("stage=clusters", html)
        self.assertIn("cluster_sort=score_desc", html)
        self.assertNotIn("<h1>Trend Opportunities</h1>", html)
        self.assertNotIn("Configuration:", html)
        self.assertNotIn("Detection → Determination", html)
        self.assertNotIn("Which layer owns each status?", html)
        self.assertNotIn("Raw Feed Items → Clusters → Opportunities → ContentJobs", html)
        self.assertIn("2026-09-07T12:07:00", html)
        self.assertIn("method='get'", html)
        self.assertNotIn("method='post'", html)
        self.assertLess(html.index('Other Topic'), html.index('Shared Opportunity'))

        connection = connect(self.database_path, read_only=True)
        try:
            recent = render_detection_dashboard(connection, cluster_sort='recent')
        finally:
            connection.close()
        self.assertIn('Newest / Recently evaluated', recent)

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
        self.assertIn("Raw Feed Items<b>1</b>", filtered)
        self.assertNotIn("Other Topic", filtered)
