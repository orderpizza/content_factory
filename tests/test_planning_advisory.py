"""Planning storage policy and four-stage dashboard lineage, entirely offline."""
from workflow.editorial_planning import EditorialPlanningWorker


from common.timestamps import serialize_timestamp
from contextlib import redirect_stdout
from dashboard.detection import render_detection_dashboard
from dashboard.flow import render_job, render_raw_item
from datetime import datetime, timedelta, timezone
from detection.collector import DetectionCollector
from detection.models import CollectedItem, CollectionResult
from detection.scout import DetectionScout
from detection.store import DetectionStore
from http.server import ThreadingHTTPServer
from io import StringIO
from pathlib import Path
from test_gemini_workflow import FakeGeminiClient, brief
from test_semantic_detection import FakeEncoder
from threading import Thread
from unittest.mock import patch
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from workflow import GeminiDeterminationWorker, GeminiIntakeWorker, WorkflowStore
from workflow.development import prepare_development_database
from workflow.maintenance import StorageMonitor
import runpy
import tempfile
import test_gemini_workflow as fixtures
import unittest


ROOT = Path(__file__).resolve().parents[1]
CONDITIONS = ('missing', 'stale', 'future', 'invalid', 'warning', 'critical', 'emergency')


def condition(store, value):
    if value == 'missing':
        store.connection.execute('DELETE FROM storage_samples')
    else:
        at = datetime.now(timezone.utc)
        timestamp = serialize_timestamp(at - timedelta(hours=4) if value == 'stale' else
                     at + timedelta(days=1) if value == 'future' else at)
        if value == 'invalid':
            timestamp = 'not-a-timestamp'
        state = ('read_only_emergency' if value == 'emergency' else
                 'storage_' + value if value in {'warning', 'critical'} else 'normal')
        store.connection.execute('UPDATE storage_samples SET state=?,sampled_at=?,free_bytes=?',
                                 (state, timestamp, 1))
    store.connection.commit()


class PlanningAdvisoryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)

    def database(self, name):
        path = Path(self.temp.name) / (name + '.db')
        prepare_development_database(path)
        return path

    def decide(self, store, outcome='accepted'):
        result = GeminiDeterminationWorker(store, FakeGeminiClient(
            fixtures.GeminiWorkflowTests.decision(store.catalog(), outcome=outcome))).run_once()
        EditorialPlanningWorker(store).run_once()
        return result

    def test_every_advisory_condition_allows_clarification_refinement_and_contentjob(self):
        for value in CONDITIONS:
            with self.subTest(condition=value), WorkflowStore(self.database(value), enforce_storage=True) as store:
                condition(store, value)
                store.create_human_idea('Teach an idiom', command_id='idea')
                GeminiIntakeWorker(store, FakeGeminiClient({'open_questions': ['Which idiom?']})).run_once()
                self.assertEqual(store.connection.execute('SELECT status FROM intake_requests').fetchone()[0], 'needs_clarification')
                thread = store.connection.execute('SELECT * FROM content_threads').fetchone()
                store.continue_human_thread(thread['thread_id'], 'Teach break the ice at work',
                    command_id='reply', expected_row_version=thread['row_version'])
                GeminiIntakeWorker(store, FakeGeminiClient(brief())).run_once()
                self.assertEqual(store.connection.execute('SELECT COUNT(*) FROM brief_revisions').fetchone()[0], 1)
                self.assertEqual(store.connection.execute('SELECT COUNT(*) FROM determination_requests').fetchone()[0], 1)
                self.assertIsNotNone(self.decide(store))
                self.assertEqual(store.connection.execute('SELECT COUNT(*) FROM content_jobs').fetchone()[0], 1)
                self.assertEqual(store.connection.execute('SELECT COUNT(*) FROM determination_routes').fetchone()[0], 3)
                self.assertEqual(store.connection.execute('SELECT status FROM generation_runs').fetchone()[0], 'pending')
                # This round does not weaken the separate downstream safety policy.
                self.assertIsNone(store.claim('generation_runs', 'generation_run_id', 'generation-test'))
                html = render_detection_dashboard(store.connection)
                for label in ('class=\'stage-tabs\'', '<h2>Clusters</h2>',
                              'ContentJobs<b>1</b>'):
                    self.assertIn(label, html)
                self.assertIn('immutable brief #1', render_job(store.connection, 1))

    def server(self, path):
        module = runpy.run_path(str(ROOT/'scripts/serve_dashboard.py'))
        handler = type('TestDashboard', (module['DashboardHandler'],), {'database_path': str(path)})
        server = ThreadingHTTPServer(('127.0.0.1', 0), handler)
        thread = Thread(target=server.serve_forever, daemon=True)
        thread.start()
        def close():
            server.shutdown(); server.server_close(); thread.join()
        self.addCleanup(close)
        return f'http://127.0.0.1:{server.server_port}', handler.csrf_token

    def test_dashboard_and_cli_accept_new_ideas_and_replies_under_every_condition(self):
        path = self.database('interfaces')
        url, token = self.server(path)
        main = runpy.run_path(str(ROOT/'scripts/create_local_idea.py'))['main']
        for value in CONDITIONS:
            with self.subTest(condition=value), WorkflowStore(path, enforce_storage=True) as store:
                # Restore a row after the missing case to exercise actual states.
                StorageMonitor(store, self.temp.name, self.temp.name).run_once()
                condition(store, value)
                def submit(**values):
                    data = urlencode(dict(csrf_token=token, **values)).encode()
                    request = Request(url+'/commands', data=data,
                        headers={'Content-Type': 'application/x-www-form-urlencoded'})
                    with urlopen(request) as response:
                        self.assertEqual(response.status, 200)
                        self.assertIn('accepted', response.read().decode())
                submit(command_kind='new_idea', command_id=value+'-web', body='Dashboard idea')
                GeminiIntakeWorker(store, FakeGeminiClient({'open_questions': ['Which topic?']})).run_once()
                row = store.connection.execute('SELECT * FROM content_threads ORDER BY thread_id DESC LIMIT 1').fetchone()
                submit(command_kind='continue_thread', command_id=value+'-web-reply', body='Dashboard refinement',
                       thread_id=row['thread_id'], row_version=row['row_version'])
                GeminiIntakeWorker(store, FakeGeminiClient(brief())).run_once()
                with patch.dict(main.__globals__, {'load_environment_file': lambda _: None, 'configure_logging': lambda _: None, 'resolve_primary_database_argument': lambda _parser,_directory:path}), redirect_stdout(StringIO()):
                    with patch('sys.argv', ['idea', 'CLI idea', '--command-id', value+'-cli']):
                        main()
                    GeminiIntakeWorker(store, FakeGeminiClient({'open_questions': ['Which topic?']})).run_once()
                    row = store.connection.execute('SELECT * FROM content_threads ORDER BY thread_id DESC LIMIT 1').fetchone()
                    with patch('sys.argv', ['idea', 'CLI refinement', '--command-id', value+'-cli-reply',
                                          '--thread-id', str(row['thread_id']), '--row-version', str(row['row_version'])]):
                        main()
                    GeminiIntakeWorker(store, FakeGeminiClient(brief())).run_once()
        with WorkflowStore(path) as store:
            self.assertEqual(store.connection.execute('SELECT COUNT(*) FROM intake_requests').fetchone()[0], 4*len(CONDITIONS))

    def test_storage_monitor_failure_cannot_stop_planning_pass(self):
        run_pass = runpy.run_path(str(ROOT/'scripts/run_workflow.py'))['_run_pass']
        with WorkflowStore(self.database('monitor-fails'), enforce_storage=True) as store:
            condition(store, 'missing')
            store.create_human_idea('Teach break the ice', command_id='idea')
            monitor = StorageMonitor(store, self.temp.name, self.temp.name)
            workers = (monitor, GeminiIntakeWorker(store, FakeGeminiClient(brief())),
                       GeminiDeterminationWorker(store, FakeGeminiClient(fixtures.GeminiWorkflowTests.decision(store.catalog()))), EditorialPlanningWorker(store))
            with patch.object(monitor, 'run_once', side_effect=OSError('measurement unavailable')), redirect_stdout(StringIO()):
                run_pass(workers)
            self.assertEqual(store.connection.execute('SELECT COUNT(*) FROM content_jobs').fetchone()[0], 1)
            self.assertEqual(store.connection.execute("SELECT state FROM worker_heartbeats WHERE worker_type='storage_monitor'").fetchone()[0], 'failed')

    def test_detection_selection_handoff_and_job_ignore_all_storage_conditions(self):
        at = datetime(2026, 9, 15, 8, tzinfo=timezone.utc)
        evidence = CollectionResult((CollectedItem('launch', 'OpenAI launches Atlas browser', 100,
                                    rank=1, provider_time=serialize_timestamp(at)),), (), True, 'a'*64, 1)
        for value, outcome in [(v, 'accepted') for v in CONDITIONS] + [('critical', 'not_recommended')]:
            path = self.database('detection-'+value+'-'+outcome)
            with self.subTest(condition=value, outcome=outcome), WorkflowStore(path, enforce_storage=True) as store:
                condition(store, value)
                with DetectionStore(path) as detection:
                    with patch('detection.collector.collect_source', return_value=evidence):
                        DetectionCollector(detection).run_due(now=at, source_ids={'hacker_news_top_stories_v1', 'openai_news_rss_v1'})
                    scout = DetectionScout(detection, encoder=FakeEncoder())
                    evaluate = scout._evaluate
                    def eligible(*args):
                        result = evaluate(*args)
                        for cluster in result['candidates']:
                            cluster.update(eligible=True, eligibility_reason='test_handoff')
                        return result
                    # Isolate admission/handoff from scoring thresholds, tested in the Detection suites.
                    with patch.object(scout, '_evaluate', side_effect=eligible):
                        scout.run(now=at)
                self.assertIsNotNone(self.decide(store, outcome))
                html = render_detection_dashboard(store.connection, stage='opportunities')
                self.assertIn("id='opportunity-1'", html)
                if outcome == 'accepted':
                    self.assertIn('ContentJobs<b>1</b>', html)
                    self.assertIn('Opportunity #1', render_job(store.connection, 1))
                else:
                    self.assertEqual(store.connection.execute('SELECT COUNT(*) FROM content_jobs').fetchone()[0], 0)
                    self.assertIn('not_recommended', html)
                self.assertIn('completed', html)
                self.assertIn('Cluster #1', render_raw_item(store.connection, 1))
                self.assertNotIn('Detection candidate', html)
                self.assertNotIn('candidate(s)', html)
                self.assertIn('Collection attempt', html)
                self.assertIn('Source health', html)
                self.assertEqual(store.connection.execute('SELECT COUNT(*) FROM intake_requests').fetchone()[0], 0)
                # A selected label/timestamp without its committed handoff is not an Opportunity.
                store.connection.execute('UPDATE trend_candidates SET selected_thread_id=NULL')
                store.connection.commit()
                html = render_detection_dashboard(store.connection, stage='opportunities')
                self.assertNotIn("id='opportunity-1'", html)
                self.assertIn('Opportunities<b>0</b>', html)

    def test_job_pagination_filters_and_read_snapshot_are_bounded(self):
        with WorkflowStore(self.database('pages')) as store:
            for number in range(21):
                store.create_human_idea('Teach expression '+str(number), command_id=str(number))
                GeminiIntakeWorker(store, FakeGeminiClient(brief('expression '+str(number)))).run_once()
                self.decide(store)
            before = store.connection.total_changes
            first = render_detection_dashboard(store.connection, stage='jobs')
            second = render_detection_dashboard(store.connection, stage='jobs', job_page=2)
            self.assertEqual(first.count("id='contentjob-"), 20)
            self.assertEqual(second.count("id='contentjob-"), 1)
            self.assertIn("id='contentjob-1'", second)
            self.assertIn('ContentJobs<b>21</b>', first)
            self.assertIn('ContentJobs<b>0</b>', render_detection_dashboard(store.connection, stage='jobs', source='hacker_news_top_stories_v1'))
            self.assertIn('ContentJobs<b>0</b>', render_detection_dashboard(store.connection, stage='jobs', query="%' OR 1=1 --"))
            self.assertEqual(store.connection.total_changes, before)
            self.assertFalse(store.connection.in_transaction)

    def test_responsive_four_stage_layout_and_details(self):
        from playwright.sync_api import sync_playwright
        path = self.database('browser')
        with WorkflowStore(path) as store:
            store.create_human_idea('Teach break the ice at work', command_id='idea')
            GeminiIntakeWorker(store, FakeGeminiClient(brief())).run_once()
            self.decide(store)
        url, _ = self.server(path)
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            try:
                page = browser.new_page(viewport={'width': 1440, 'height': 900})
                errors = []
                page.on('pageerror', lambda error: errors.append(str(error)))
                page.goto(url)
                self.assertEqual(page.locator('.flow-stage').count(), 1)
                self.assertEqual(page.locator('.stage-tabs a').count(), 4)
                self.assertTrue(page.evaluate("document.querySelector('.flow-stage').getBoundingClientRect().y < document.getElementById('queues').getBoundingClientRect().y"))
                page.set_viewport_size({'width': 390, 'height': 844})
                self.assertTrue(page.evaluate('document.documentElement.scrollWidth <= innerWidth'))
                page.locator(".stage-tabs a[href*='stage=jobs']").click()
                page.locator('#contentjob-1 a').first.click()
                self.assertIn('Human thread #1', page.locator('#job-detail').inner_text())
                self.assertEqual(errors, [])
            finally:
                browser.close()
