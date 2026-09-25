"""Offline acceptance for the two dashboard-visible planning paths."""
from workflow.editorial_planning import EditorialPlanningWorker, GeminiEditorialPlanningWorker, fixture_plan


from common.timestamps import serialize_timestamp
from contextlib import redirect_stdout
from dashboard.evidence import render_candidate, render_evaluation
from dashboard.planning import render_threads
from datetime import datetime, timezone
from detection.collector import DetectionCollector
from detection.models import CollectedItem, CollectionResult
from detection.scout import DetectionScout
from detection.store import DetectionStore
from io import StringIO
from pathlib import Path
from test_gemini_workflow import FakeGeminiClient, brief
from test_semantic_detection import FakeEncoder
from unittest.mock import patch
from workflow import GeminiDeterminationWorker, GeminiIntakeWorker, WorkflowStore
from workflow.development import prepare_development_database
import json
import runpy
import sqlite3
import tempfile
import test_gemini_workflow as gemini_fixtures
import unittest


ROOT = Path(__file__).resolve().parents[1]


class PlanningFlowTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / 'fresh.db'
        prepare_development_database(self.path)

    def test_fresh_setup_has_current_schema_catalog_and_no_external_work(self):
        with WorkflowStore(self.path) as store:
            self.assertEqual(store.connection.execute('PRAGMA user_version').fetchone()[0], 17)
            self.assertEqual(len(store.catalog()), 3)
            self.assertTrue(all(len(c['outputs'])==1 and c['remit']['purpose'] for c in store.catalog()))
            self.assertEqual(store.connection.execute('SELECT COUNT(*) FROM content_threads').fetchone()[0], 0)
            self.assertEqual(store.connection.execute('SELECT COUNT(*) FROM social_destinations').fetchone()[0], 0)
            self.assertEqual(len(store.catalog()), 3)
        with self.assertRaises(FileExistsError):
            prepare_development_database(self.path)

    def test_human_clarification_to_three_routes_and_content_job_is_visible(self):
        with WorkflowStore(self.path) as store:
            store.create_human_idea('Teach something', command_id='idea')
            worker = GeminiIntakeWorker(store, FakeGeminiClient({'open_questions':['Which expression?']}))
            worker.run_once()
            self.assertEqual(worker.last_operation['status'], 'needs_clarification')
            self.assertIn('Which expression?', render_threads(store.connection))
            row = store.connection.execute('SELECT thread_id,row_version FROM content_threads').fetchone()
            store.continue_human_thread(row[0], 'Teach break the ice at business meetings', command_id='reply', expected_row_version=row[1])
            GeminiIntakeWorker(store, FakeGeminiClient(brief())).run_once()
            decision = gemini_fixtures.GeminiWorkflowTests.decision(store.catalog())
            GeminiDeterminationWorker(store, FakeGeminiClient(decision)).run_once()
            EditorialPlanningWorker(store).run_once()
            html = render_threads(store.connection, thread_id=row[0], interactive=True)
            for fragment in ['break the ice', 'business meetings', 'ContentJob #1', 'Three domain routes', 'english', 'psychology', 'fake-gemini', 'Frozen Determination input']:
                self.assertIn(fragment, html)
            self.assertEqual(store.connection.execute('SELECT COUNT(*) FROM determination_routes').fetchone()[0], 3)
            self.assertEqual(store.connection.execute('SELECT status FROM generation_runs').fetchone()[0], 'pending')
            self.assertEqual(store.connection.execute('SELECT COUNT(*) FROM canonical_contents').fetchone()[0], 0)
            with self.assertRaises(sqlite3.IntegrityError):
                store.connection.execute("UPDATE determination_requests SET input_snapshot_json='{}'")

    def test_detection_handoff_freezes_catalog_and_survives_human_refinement(self):
        at = datetime(2026,9,15,8,tzinfo=timezone.utc)
        evidence = CollectionResult((CollectedItem('launch','OpenAI launches Atlas browser',100,rank=1,provider_time=serialize_timestamp(at)),),(),True,'a'*64,1)
        with DetectionStore(self.path) as detection:
            with patch('detection.collector.collect_source', return_value=evidence):
                DetectionCollector(detection).run_due(now=at,source_ids={'hacker_news_top_stories_v1','openai_news_rss_v1'})
            scout = DetectionScout(detection,encoder=FakeEncoder())
            # This test exercises handoff/UI, not score policy. Semantic and
            # attention suites independently guard eligibility and score credit.
            evaluate = scout._evaluate
            def eligible(*args):
                result = evaluate(*args)
                for candidate in result['candidates']:
                    candidate.update(eligible=True,eligibility_reason='test_handoff')
                return result
            with patch.object(scout,'_evaluate',side_effect=eligible):
                scout.run(now=at)
            candidate = detection.connection.execute('SELECT trend_candidate_id FROM trend_candidates').fetchone()[0]
            self.assertIn('OpenAI launches Atlas browser',render_candidate(detection.connection,candidate))
            self.assertIn('Semantic decisions',render_evaluation(detection.connection,1))
        with WorkflowStore(self.path) as store:
            request = store.connection.execute('SELECT * FROM determination_requests').fetchone()
            frozen = json.loads(request['input_snapshot_json'])
            self.assertEqual(len(frozen['catalog']),3)
            self.assertEqual(store.connection.execute('SELECT COUNT(*) FROM intake_requests').fetchone()[0],0)
            GeminiDeterminationWorker(store,FakeGeminiClient(gemini_fixtures.GeminiWorkflowTests.decision(frozen['catalog'],selected_pipeline='ai_tech'))).run_once()
            planning_run = store.connection.execute('SELECT * FROM editorial_plan_runs').fetchone()
            planning_input = json.loads(planning_run['input_snapshot_json'])
            plan = fixture_plan(planning_input)
            plan['lane'] = 'trend'
            plan['why_now'] = 'Frozen sources record this product announcement at the Detection handoff.'
            plan['candidates'][0]['evidence_reference_ids'] = planning_input['allowed_evidence_reference_ids'][:1]
            self.assertIsNotNone(GeminiEditorialPlanningWorker(store, FakeGeminiClient(__import__('claim_fixtures').proposal_response(plan))).run_once())
            self.assertEqual(store.connection.execute('SELECT lane FROM editorial_plans').fetchone()[0], 'trend')
            self.assertEqual(store.connection.execute('SELECT COUNT(*) FROM content_jobs').fetchone()[0],1)
            row = store.connection.execute('SELECT * FROM content_threads').fetchone()
            store.continue_human_thread(row['thread_id'],'Explain practical use cases',command_id='refine',expected_row_version=row['row_version'])
            revised = dict(frozen['brief'], audience='AI tool users')
            client = FakeGeminiClient(revised)
            GeminiIntakeWorker(store,client).run_once()
            self.assertIn('detection_evidence',client.calls[0]['prompt'])
            snapshot = json.loads(store.connection.execute('SELECT source_snapshot_json FROM brief_revisions ORDER BY revision_number DESC LIMIT 1').fetchone()[0])
            self.assertEqual(snapshot['detection_evidence'],frozen['source_context'])
            self.assertEqual(request['input_snapshot_json'],store.connection.execute('SELECT input_snapshot_json FROM determination_requests WHERE determination_request_id=?',(request['determination_request_id'],)).fetchone()[0])

    def test_failed_gemini_claim_is_reported_as_failed_not_idle(self):
        run_pass = runpy.run_path(str(ROOT/'scripts/run_workflow.py'))['_run_pass']
        with WorkflowStore(self.path) as store:
            store.create_human_idea('Teach a practical expression',command_id='bad')
            worker = GeminiIntakeWorker(store,FakeGeminiClient({'open_questions':[], 'topic':'invalid'}))
            with redirect_stdout(StringIO()) as output:
                run_pass((worker,))
            self.assertIn('failed',output.getvalue())
            self.assertEqual(store.connection.execute("SELECT state FROM worker_heartbeats WHERE worker_type='idea_intake'").fetchone()[0],'failed')
            self.assertEqual(store.connection.execute('SELECT status FROM worker_runs').fetchone()[0],'failed')

    def test_planning_runner_never_consumes_generation(self):
        main = runpy.run_path(str(ROOT/'scripts/run_workflow.py'))['main']
        with WorkflowStore(self.path) as store:
            store.create_human_idea('Teach break the ice at business meetings',command_id='one-shot')
        with patch('sys.argv',['run_workflow','--planning-only']), patch.dict(main.__globals__,{'load_environment_file':lambda _:None, 'resolve_primary_database_argument':lambda _parser,_directory:self.path}), redirect_stdout(StringIO()):
            main()
        with WorkflowStore(self.path) as store:
            self.assertEqual(store.connection.execute('SELECT COUNT(*) FROM content_jobs').fetchone()[0],1)
            self.assertEqual(store.connection.execute('SELECT status FROM generation_runs').fetchone()[0],'pending')
            self.assertEqual(store.connection.execute('SELECT COUNT(*) FROM canonical_contents').fetchone()[0],0)

    def test_model_evidence_view_deduplicates_polls_without_mutating_frozen_input(self):
        from workflow.planning_context import model_context
        frozen = {'source_context': {'kind':'selected_trend', 'evidence': [
            {'observation_id':i, 'lexical_key':'event', 'source':'hn', 'contributing':True, 'title':'Same observed event'}
            for i in range(500)]}}
        view = model_context(frozen)
        self.assertEqual(len(frozen['source_context']['evidence']),500)
        self.assertEqual(len(view['source_context']['evidence']),1)
        self.assertEqual(view['source_context']['evidence'][0]['observation_id'],499)
        self.assertEqual(view['source_context']['evidence_selection']['omitted'],499)
        self.assertEqual(view,model_context(frozen))
