"""Audit regressions: no providers, no real DB writes, no retention deletions."""
from datetime import datetime, timedelta, timezone
from io import StringIO
from pathlib import Path
from http.server import ThreadingHTTPServer
from threading import Thread
from unittest.mock import patch
from urllib.request import urlopen
import json
import logging
import runpy
import tempfile
import unittest

from common.operation_log import LOGGER, emit, configure_logging
from common.storage import storage_status
from workflow import WorkflowStore, GeminiIntakeWorker, GeminiDeterminationWorker
from workflow.development import prepare_development_database
from workflow.maintenance import StorageMonitor
from workflow.storage_growth import measure_tables
from dashboard.evidence import render_storage_status, render_storage_growth
from dashboard.detection import render_detection_dashboard
from test_gemini_workflow import FakeGeminiClient, brief
import test_gemini_workflow as fixtures

ROOT = Path(__file__).resolve().parents[1]


class Audit0920Tests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name)/'test.db'
        prepare_development_database(self.path)

    def test_stale_normal_sample_is_not_disk_pressure_and_recovery_is_model_free(self):
        with WorkflowStore(self.path, enforce_storage=True) as store:
            old = (datetime.now(timezone.utc)-timedelta(hours=4)).isoformat()
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
            future = (datetime.now(timezone.utc)+timedelta(days=1)).isoformat()
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

    def test_logs_correlate_decision_without_payloads_or_exception_bodies(self):
        output = StringIO()
        handler = logging.StreamHandler(output)
        old_level = LOGGER.level
        LOGGER.setLevel(logging.INFO); LOGGER.addHandler(handler)
        self.addCleanup(LOGGER.removeHandler,handler)
        self.addCleanup(LOGGER.setLevel,old_level)
        with WorkflowStore(self.path) as store:
            store.create_human_idea('PRIVATE_HUMAN_SENTINEL',command_id='logged')
            GeminiIntakeWorker(store,FakeGeminiClient(brief())).run_once()
            GeminiDeterminationWorker(store,FakeGeminiClient(fixtures.GeminiWorkflowTests.decision(store.catalog()))).run_once()
        emit('test','safe', status='failed', model_id='access_token=SECRET', prompt='PROMPT_SENTINEL', body='BODY_SENTINEL')
        lines = [json.loads(line) for line in output.getvalue().splitlines()]
        for forbidden in ('PRIVATE_HUMAN_SENTINEL','PROMPT_SENTINEL','BODY_SENTINEL','SECRET','break the ice'):
            self.assertNotIn(forbidden,output.getvalue())
        decision = next(r for r in lines if r.get('decision_id'))
        self.assertEqual(decision['selected_count'],1)
        self.assertEqual(decision['skipped_count'],2)
        self.assertTrue(decision['job_ids'])
        self.assertTrue(any(r['event']=='model_result' and r.get('model_id') for r in lines))

    def test_rotating_logs_are_bounded_and_do_not_touch_other_files(self):
        root=Path(self.temp.name)/'logs'
        root.mkdir()
        unrelated=root/'evidence.json'
        unrelated.write_text('keep')
        previous=list(LOGGER.handlers); previous_level=LOGGER.level
        # Isolate global logging from the remaining tests.
        LOGGER.handlers=[]
        try:
            configure_logging('test',root=root,max_bytes=1024,backups=2)
            for handler in list(LOGGER.handlers):
                if not hasattr(handler,'baseFilename'):
                    LOGGER.removeHandler(handler)
            for number in range(100):
                emit('test','rotation',record_id=number,status='completed')
            files=list(root.glob('cf-test-*.jsonl*'))
            self.assertLessEqual(len(files),3)
            self.assertTrue(all(p.stat().st_size<=1024 for p in files))
            self.assertEqual(unrelated.read_text(),'keep')
        finally:
            for handler in LOGGER.handlers:
                handler.close()
            LOGGER.handlers=previous
            LOGGER.setLevel(previous_level)

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
