"""Offline strategy boundary contracts and fenced handoffs."""
import json
import sqlite3
from copy import deepcopy
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from workflow.development import prepare_development_database
from workflow import WorkflowStore, GeminiDeterminationWorker, GeminiIntakeWorker, GeminiPipelineRunner
from workflow.editorial_planning import (
    EditorialPlanningWorker, GeminiEditorialPlanningWorker, fixture_plan, validate_plan,
    QUALIFICATIONS, PLAN_SCHEMA,
)
from dashboard.planning import render_threads
from test_gemini_workflow import FakeGeminiClient, brief
import test_gemini_workflow as fixtures


class EditorialPlanningTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / 'editorial.db'
        prepare_development_database(self.path)
        self.store = WorkflowStore(self.path)
        self.addCleanup(self.store.close)
        self.sequence = 0

    def pending(self, domain='english', intention=None):
        self.sequence += 1
        target = f'editorial subject {self.sequence}'
        value = brief(target)
        if intention:
            value['constraints']['editorial_intention'] = intention
        self.store.create_human_idea(intention or 'Explain ' + target, command_id=str(self.sequence))
        GeminiIntakeWorker(self.store, FakeGeminiClient(value)).run_once()
        decision = fixtures.GeminiWorkflowTests.decision(self.store.catalog(), selected_pipeline=domain)
        self.assertIsNotNone(GeminiDeterminationWorker(self.store, FakeGeminiClient(decision)).run_once())
        return self.store.connection.execute('SELECT * FROM editorial_plan_runs ORDER BY editorial_plan_run_id DESC LIMIT 1').fetchone()

    def count(self, table):
        return self.store.connection.execute(f'SELECT COUNT(*) FROM {table}').fetchone()[0]

    def test_domains_plan_before_job_and_generation_consumes_plan(self):
        for domain in QUALIFICATIONS:
            with self.subTest(domain=domain):
                run = self.pending(domain, 'Explain specifically as three practical mistakes beginners make.')
                before = self.count('content_jobs')
                snapshot = json.loads(run['input_snapshot_json'])
                self.assertIn('three practical mistakes', snapshot['brief']['constraints']['editorial_intention'])
                client = FakeGeminiClient(fixture_plan(snapshot))
                plan_id = GeminiEditorialPlanningWorker(self.store, client).run_once()
                self.assertIsNotNone(plan_id)
                self.assertEqual(self.count('content_jobs'), before + 1)
                plan = self.store.connection.execute('SELECT * FROM editorial_plans WHERE editorial_plan_id=?', (plan_id,)).fetchone()
                value = json.loads(plan['plan_json'])
                self.assertEqual(value['domain'], domain)
                self.assertEqual(value['lane'], 'evergreen')
                self.assertEqual(plan['brief_revision_id'], run['revision_id'])
                self.assertEqual(plan['input_fingerprint'], run['input_fingerprint'])
                self.assertRegex(plan['created_at'], r'^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}$')
                self.assertIs(client.calls[0]['schema'], PLAN_SCHEMA)
                generator = FakeGeminiClient(fixtures.GeminiWorkflowTests.canonical_response(domain))
                self.assertIsNotNone(GeminiPipelineRunner(self.store, generator).run_once())
                self.assertIn('editorial_plan', generator.calls[0]['prompt'])
                self.assertIn('must_cover_points', generator.calls[0]['prompt'])
                self.assertIn('Editorial plan: promise', render_threads(self.store.connection))
                with self.assertRaises(sqlite3.IntegrityError):
                    self.store.connection.execute("UPDATE editorial_plans SET lane='trend' WHERE editorial_plan_id=?", (plan_id,))
                with self.assertRaises(sqlite3.IntegrityError):
                    self.store.connection.execute('DELETE FROM editorial_plans WHERE editorial_plan_id=?', (plan_id,))
                self.store.connection.rollback()

    def test_closed_validation_and_domain_policy(self):
        run = self.pending('psychology')
        snapshot = json.loads(run['input_snapshot_json'])
        base = fixture_plan(snapshot)
        mutations = {
            'unknown_domain': lambda p: p.update(domain='health'),
            'wrong_domain': lambda p: p.update(domain='english'),
            'lane': lambda p: p.update(lane='viral'),
            'candidate_count': lambda p: p['candidates'].extend(deepcopy(p['candidates'])*2),
            'one_candidate': lambda p: p['candidates'].pop(),
            'selection': lambda p: p.update(selected_candidate_id='missing'),
            'duplicate_id': lambda p: p['candidates'][1].update(candidate_id='1'),
            'empty_angle': lambda p: p['candidates'][0].update(angle=' '),
            'empty_promise': lambda p: p['candidates'][0].update(reader_promise=''),
            'empty_points': lambda p: p['candidates'][0].update(must_cover_points=[]),
            'too_many_points': lambda p: p['candidates'][0].update(must_cover_points=['x']*9),
            'references': lambda p: p['candidates'][0].update(evidence_reference_ids=['invented:9']),
            'series': lambda p: p.update(series_key='weekly'),
            'experiment': lambda p: p.update(experiment_key='test'),
            'experiment_without_intention': lambda p: p.update(lane='experiment'),
            'qualification': lambda p: p['candidates'][0].update(qualification_requirements=['uncertainty']),
            'platform': lambda p: p.update(caption='bad'),
            'visual': lambda p: p['candidates'][0].update(archetype_id='bad'),
            'strategy': lambda p: p['candidates'][0].update(angle_type='what_changed'),
        }
        for name, mutate in mutations.items():
            with self.subTest(name=name):
                value = deepcopy(base); mutate(value)
                with self.assertRaises(ValueError):
                    validate_plan(value, snapshot)
        for lane in ('series', 'experiment'):
            value = deepcopy(base); value['lane'] = lane
            if lane == 'series':
                value['series_key'] = 'psychology-myths'
            else:
                value['experiment_key'] = 'scenario-first'
                value['experiment_intention'] = 'Test a scenario before naming the concept.'
            validate_plan(value, snapshot)

    def test_failed_model_plan_visible_without_job_or_fallback(self):
        run = self.pending()
        client = FakeGeminiClient({'caption': 'not a plan'})
        worker = GeminiEditorialPlanningWorker(self.store, client)
        self.assertIsNone(worker.run_once())
        self.assertEqual(worker.last_operation['status'], 'failed')
        self.assertEqual(self.count('editorial_plans'), 0)
        self.assertEqual(self.count('content_jobs'), 0)
        self.assertIsNone(EditorialPlanningWorker(self.store).run_once())
        self.assertEqual(len(client.calls), 1)
        self.assertIn('Editorial planning: failed', render_threads(self.store.connection))
        self.assertEqual(self.store.connection.execute("SELECT outcome FROM model_invocations WHERE phase='editorial_planning'").fetchone()[0], 'schema_failed')

    def test_transaction_rollback_and_restart_duplicate_protection(self):
        run = self.pending()
        with self.store.connection:
            self.store.connection.execute("CREATE TRIGGER test_handoff_failure BEFORE INSERT ON generation_runs BEGIN SELECT RAISE(ABORT,'injected failure'); END")
        self.assertIsNone(EditorialPlanningWorker(self.store).run_once())
        self.assertEqual(self.count('editorial_plans'), 0)
        self.assertEqual(self.count('content_jobs'), 0)
        with self.store.connection:
            self.store.connection.execute('DROP TRIGGER test_handoff_failure')
        self.pending('ai_tech')
        self.assertIsNotNone(EditorialPlanningWorker(self.store).run_once())
        with WorkflowStore(self.path) as restarted:
            self.assertIsNone(EditorialPlanningWorker(restarted).run_once())
        self.assertEqual(self.count('content_jobs'), 1)
        with self.assertRaises(sqlite3.IntegrityError):
            self.store.connection.execute('INSERT INTO content_jobs SELECT * FROM content_jobs')
        self.store.connection.rollback()

    def test_expired_claim_fencing_and_paid_history_no_replay(self):
        self.pending()
        old = self.store.claim('editorial_plan_runs', 'editorial_plan_run_id', 'old')
        snapshot = json.loads(old['input_snapshot_json'])
        with self.store.connection:
            self.store.connection.execute("UPDATE editorial_plan_runs SET lease_expires_at='2000-01-01T00:00:00'")
        new = self.store.claim('editorial_plan_runs', 'editorial_plan_run_id', 'new')
        with self.assertRaises(RuntimeError):
            self.store.complete_editorial_plan(old, fixture_plan(snapshot), planner_version='fixture')
        self.assertEqual(self.count('editorial_plans'), 0)
        self.store.begin_model_invocation(phase='editorial_planning', table='editorial_plan_runs', key='editorial_plan_run_id', row=new,
                                          request_version='editorial_input_v1', prompt_version='editorial_planner_v1', schema_version='editorial_plan_v1', request_value=snapshot, model_id='fake')
        with self.store.connection:
            self.store.connection.execute("UPDATE editorial_plan_runs SET lease_expires_at='2000-01-01T00:00:00'")
        self.assertIsNone(EditorialPlanningWorker(self.store).run_once())
        self.assertEqual(self.store.connection.execute('SELECT status FROM editorial_plan_runs').fetchone()[0], 'failed')
        self.assertEqual(self.count('content_jobs'), 0)

    def test_cancelled_thread_prevents_paid_call(self):
        self.pending()
        with self.store.connection:
            self.store.connection.execute("UPDATE content_threads SET status='cancelled'")
        client = FakeGeminiClient({})
        self.assertIsNone(GeminiEditorialPlanningWorker(self.store, client).run_once())
        self.assertEqual(client.calls, [])
        self.assertEqual(self.store.connection.execute('SELECT status FROM editorial_plan_runs').fetchone()[0], 'cancelled')
        self.assertEqual(self.count('content_jobs'), 0)

    def test_history_is_bounded_frozen_and_domain_scoped(self):
        for _ in range(14):
            self.pending(); EditorialPlanningWorker(self.store).run_once()
        run = self.pending()
        snapshot = json.loads(run['input_snapshot_json'])
        self.assertEqual([h['editorial_plan_id'] for h in snapshot['history']], list(range(14, 2, -1)))
        other = self.pending('psychology')
        self.assertEqual(json.loads(other['input_snapshot_json'])['history'], [])
        with self.assertRaises(sqlite3.IntegrityError):
            self.store.connection.execute("UPDATE editorial_plan_runs SET input_snapshot_json='{}' WHERE editorial_plan_run_id=?", (run['editorial_plan_run_id'],))
        self.store.connection.rollback()
        self.assertEqual(self.store.connection.execute('SELECT input_snapshot_json FROM editorial_plan_runs WHERE editorial_plan_run_id=?', (run['editorial_plan_run_id'],)).fetchone()[0], run['input_snapshot_json'])

    def test_determination_handoff_has_no_job_and_lineage_cannot_be_spoofed(self):
        run = self.pending()
        self.assertEqual(self.count('content_jobs'), 0)
        self.assertEqual(self.count('generation_runs'), 0)
        self.assertEqual(run['status'], 'pending')
        claim = self.store.claim('editorial_plan_runs', 'editorial_plan_run_id', 'fixture')
        forged = dict(claim); forged['revision_id'] += 100
        with self.assertRaises(ValueError):
            self.store.complete_editorial_plan(forged, fixture_plan(json.loads(run['input_snapshot_json'])), planner_version='fixture')
        self.assertEqual(self.count('editorial_plans'), 0)

    def test_planning_budget_deferral_and_usage_settlement(self):
        from decimal import Decimal
        from workflow.model_budget import ModelBudgetPolicy
        run = self.pending()
        value = fixture_plan(json.loads(run['input_snapshot_json']))
        self.store.model_budget_policy = ModelBudgetPolicy('fake', Decimal('1'), Decimal('2'), 50, 100, 1000, {'editorial_planning': (100, 50)})
        client = FakeGeminiClient(value)
        self.assertIsNone(GeminiEditorialPlanningWorker(self.store, client).run_once())
        self.assertEqual(client.calls, [])
        row = self.store.connection.execute('SELECT status,next_attempt_at FROM editorial_plan_runs').fetchone()
        self.assertEqual(row['status'], 'retry_wait')
        self.assertRegex(row['next_attempt_at'], r'^\d{4}-\d{2}-\d{2}T00:00:00$')
        self.assertEqual(self.count('content_jobs'), 0)
        # A separate route with sufficient daily allowance settles shared accounting.
        self.store.model_budget_policy = None
        run = self.pending('ai_tech')
        self.store.model_budget_policy = ModelBudgetPolicy('fake', Decimal('1'), Decimal('2'), 500000, 1000000, 1000, {'editorial_planning': (100, 50)})
        client = FakeGeminiClient(fixture_plan(json.loads(run['input_snapshot_json'])))
        self.assertIsNotNone(GeminiEditorialPlanningWorker(self.store, client).run_once())
        reservation = self.store.connection.execute("SELECT status,content_job_id FROM gemini_budget_reservations WHERE phase='editorial_planning'").fetchone()
        self.assertEqual(reservation['status'], 'settled')
        self.assertIsNone(reservation['content_job_id'])
