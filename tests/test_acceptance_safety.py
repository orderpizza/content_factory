"""Offline provider-attempt caps and failure evidence through real workers."""
from dataclasses import replace
import json
import sqlite3
from unittest.mock import patch

import pytest
from google.genai.errors import APIError

from acceptance.framework import (StageCase, discover_cases,
                                  initialize_acceptance_database)
from acceptance.runners import matrix
from acceptance.safety import AcceptanceStore, AttemptGuard, RunGuard, read_accounting
from common import gemini
from workflow import GeminiIntakeWorker, WorkflowStore
from workflow.gemini_image_renderer import DispatchVisualRenderer
from test_acceptance_harness_offline import FIXTURES, text_policy
from test_gemini_workflow import FakeGeminiClient, brief
from test_render_recovery import database, prepare, policy, IncidentClient


def run_smoke(tmp_path, monkeypatch, client, *, repeat=2, max_calls=None):
    monkeypatch.setattr(matrix, '_policies', lambda *args: (text_policy(), None))
    monkeypatch.setattr(gemini, 'VertexGeminiClient', lambda **kwargs: client)
    return matrix.run_matrix(profile='smoke', dry_run=False, cli_live=True, repeat=repeat,
        limits={'max_usd': '1', 'max_calls': max_calls},
        environment={'CONTENT_FACTORY_ENABLE_LIVE_GEMINI_TESTS': '1'},
        case_directory=FIXTURES, output_root=tmp_path)


@pytest.mark.parametrize('scope,cap,expected', [('case', 1, 1), ('case', 2, 2),
                                                ('text', 1, 1), ('combined', 1, 1)])
def test_text_transport_retries_share_case_cap(tmp_path, scope, cap, expected):
    path = tmp_path / 'retry.db'
    initialize_acceptance_database(path)
    guard = AttemptGuard(RunGuard(cap if scope == 'combined' else 10, 0,
                                  cap if scope == 'text' else 10, 1_000_000),
                         {'intake': cap if scope == 'case' else 2}, 1_000_000)

    class Rejected(FakeGeminiClient):
        def generate_json(self, *args, **kwargs):
            self.calls.append(1)
            self.last_usage = None
            raise APIError(429, {'error': {'message': 'private error'}})

    client = Rejected(brief())
    with AcceptanceStore(path, model_budget_policy=text_policy(), attempt_guard=guard) as store:
        store.create_human_idea('teach break the ice', command_id='retry')
        worker = GeminiIntakeWorker(store, client)
        for minute in range(4):
            with patch('workflow.store.now', return_value=f'2030-01-01T00:0{minute}:00'):
                worker.run_once()
    evidence = read_accounting(path)
    assert len(client.calls) == guard.run.calls == evidence['calls'] == expected
    assert guard.blocked == f'acceptance {"case" if scope == "case" else "run"} provider-attempt cap reached'
    assert evidence['accounted_micro_usd'] == 0
    assert not evidence['unresolved']
    assert evidence['invocations'][-1]['outcome'] == 'blocked'
    assert evidence['invocations'][-1]['accounting_status'] == 'released'


@pytest.mark.parametrize('scope,cap', [('case', 1), ('case', 2), ('case', 5),
                                      ('combined', 5), ('image', 5)])
def test_real_image_reinforcement_fallback_and_provider_retry_are_capped(database, tmp_path, scope, cap):
    # This fixture's first composite fails structure, reinforcement also fails,
    # then singleton fallbacks receive explicit retryable 429 rejections.
    with WorkflowStore(database.path) as store:
        prepare(store, database)
    run = RunGuard(cap if scope == 'combined' else 20,
                   cap if scope == 'image' else 20, 0, 20_000_000)
    guard = AttemptGuard(run, {'image_rendering': cap if scope == 'case' else 20}, 20_000_000)
    client = IncidentClient()
    with AcceptanceStore(database.path, attempt_guard=guard) as store:
        worker = DispatchVisualRenderer(store, tmp_path, image_client=client, budget_policy=policy())
        for minute in range(4):
            with patch('workflow.store.now', return_value=f'2030-01-01T00:0{minute}:00'):
                worker.run_once()
        assert len(client.calls) == run.calls == run.images == cap
        assert guard.blocked
        rows = store.connection.execute("SELECT outcome FROM model_invocations WHERE phase='image_rendering'").fetchall()
        assert sum(r[0] != 'blocked' for r in rows) == cap
        assert any(r[0] == 'blocked' for r in rows)
        assert list(tmp_path.glob('render-*.checkpoint/raw-*'))  # partial raw evidence survives
        if cap == 5:
            assert client.counts[((1,), False)] == 1  # scheduled retry was refused
            assert client.counts[((1, 2), True)] == 1  # reinforced composite was counted


def test_recovery_can_complete_with_sufficient_cap_without_changing_retry_policy(database, tmp_path):
    with WorkflowStore(database.path) as store:
        prepare(store, database)
    run = RunGuard(12, 12, 0, 20_000_000)
    guard = AttemptGuard(run, {'image_rendering': 12}, 20_000_000)
    client = IncidentClient(provider_before_structure=True)
    with AcceptanceStore(database.path, attempt_guard=guard) as store:
        worker = DispatchVisualRenderer(store, tmp_path, image_client=client, budget_policy=policy())
        for minute in range(7):
            with patch('workflow.store.now', return_value=f'2030-01-01T00:0{minute}:00'):
                worker.run_once()
        assert store.connection.execute('SELECT status FROM render_runs').fetchone()[0] == 'succeeded'
        assert len(client.calls) == run.calls == 12
        assert client.counts[((1, 2), False)] == client.counts[((1, 2), True)] == 3
        assert client.counts[((1,), False)] == client.counts[((2,), False)] == 2
        assert not guard.blocked


def test_repeats_use_separate_databases_and_one_run_counter(tmp_path, monkeypatch):
    client = FakeGeminiClient(brief())
    output, info = run_smoke(tmp_path, monkeypatch, client, repeat=3, max_calls=2)
    assert len(client.calls) == info['actual_calls'] == info['guard_admitted_calls'] == 2
    assert info['result_counts']['SKIP_BUDGET'] == 1
    assert len(list(output.rglob('workflow.db'))) == 2
    assert not info['accounting_unresolved']
    rows = json.loads((output / 'costs.json').read_text())['cases']
    assert [r['text_calls'] for r in rows] == [1, 1, 0]


@pytest.mark.parametrize('failure', ['missing_usage', 'timeout', 'error_after_return', 'usage_over_reserve'])
def test_failure_accounting_and_next_admission(tmp_path, monkeypatch, failure):
    class Client(FakeGeminiClient):
        def generate_json(self, *args, **kwargs):
            response = super().generate_json(*args, **kwargs)
            if failure in {'missing_usage', 'timeout'}:
                self.last_usage = None
            if failure == 'timeout':
                raise TimeoutError('SECRET provider details')
            if failure == 'usage_over_reserve':
                self.last_usage = gemini.GeminiUsage(2_000_000, 80, 2_000_080, self.model)
            return response
    client = Client(brief())
    original = matrix._intake_executor
    if failure == 'error_after_return':
        def explode(*args, **kwargs):
            original(*args, **kwargs)
            raise RuntimeError('SECRET provider details')
        monkeypatch.setattr(matrix, '_intake_executor', explode)
    output, info = run_smoke(tmp_path, monkeypatch, client)
    attempts = sorted(output.glob('cases/**/evaluation.json'))
    first, second = [json.loads(p.read_text()) for p in attempts]
    evidence = json.loads((attempts[0].parent / 'accounting.json').read_text())
    assert first['calls'] == 1
    assert float(first['estimated_cost_usd']) > 0
    assert 'SECRET' not in (output / 'summary.md').read_text() + attempts[0].read_text()
    if failure in {'missing_usage', 'timeout'}:
        assert info['actual_calls'] == len(client.calls) == 1
        assert evidence['uncertain_micro_usd'] == text_policy().reservation_estimate('intake')[2]
        assert evidence['settled_micro_usd'] == 0 and evidence['unresolved']
        assert first['status'] == 'ERROR' and second['status'] == 'SKIP_BUDGET'
        assert second['findings'][0]['code'] == 'accounting_unresolved'
    elif failure == 'error_after_return':
        assert first['findings'][0]['message'] == 'RuntimeError: case execution failed'
        assert evidence['settled_micro_usd'] > 0 and not evidence['unresolved']
        assert (attempts[0].parent / 'intake.json').exists()
        assert info['actual_calls'] == 2  # known billed failure is counted across attempts
    else:
        assert evidence['settled_micro_usd'] > 1_000_000
        assert evidence['invocations'][0]['actual_minus_reservation_micro_usd'] > 0
        assert second['status'] == 'SKIP_BUDGET' and len(client.calls) == 1


@pytest.mark.parametrize('kind', ['missing', 'partial', 'lost_reservation', 'lost_settlement', 'started'])
def test_missing_partial_and_inflight_evidence_never_looks_free(tmp_path, monkeypatch, kind):
    original = matrix._intake_executor
    client = FakeGeminiClient(brief())
    def explode(stage_case, database, *args, **kwargs):
        if kind == 'partial':
            with sqlite3.connect(database) as connection:
                connection.execute('CREATE TABLE unrelated (id INTEGER)')
        elif kind in {'lost_reservation', 'lost_settlement', 'started'}:
            original(stage_case, database, *args, **kwargs)
            with sqlite3.connect(database) as connection:
                if kind == 'lost_reservation':
                    connection.execute('DELETE FROM gemini_budget_reservations')
                elif kind == 'lost_settlement':
                    connection.execute('UPDATE gemini_budget_reservations SET settled_micro_usd=NULL')
                else:
                    connection.execute("UPDATE model_invocations SET outcome='started',input_tokens=NULL,output_tokens=NULL")
                    connection.execute("UPDATE gemini_budget_reservations SET status='reserved',settled_micro_usd=NULL")
        raise RuntimeError('SECRET')
    monkeypatch.setattr(matrix, '_intake_executor', explode)
    output, info = run_smoke(tmp_path, monkeypatch, client)
    assert info['accounting_unresolved']
    assert info['result_counts']['SKIP_BUDGET'] == 1
    if kind != 'started':
        assert info['actual_calls'] is None and info['estimated_cost_usd'] is None
        assert info['accounting_incomplete']
        assert 'unknown' in (output / 'summary.md').read_text()
    else:
        assert info['actual_calls'] == 1
        assert info['active_reservation_micro_usd'] > 0
    assert 'SECRET' not in (output / 'summary.md').read_text()


@pytest.mark.parametrize('scope', ['case', 'run'])
def test_per_attempt_estimated_dollar_guard_refuses_before_provider(tmp_path, scope):
    path = tmp_path / 'budget.db'
    initialize_acceptance_database(path)
    guard = AttemptGuard(RunGuard(1, 0, 1, 1 if scope == 'run' else 1_000_000),
                         {'intake': 1}, 1 if scope == 'case' else 1_000_000)
    client = FakeGeminiClient(brief())
    with AcceptanceStore(path, model_budget_policy=text_policy(), attempt_guard=guard) as store:
        store.create_human_idea('teach break the ice', command_id='budget')
        assert GeminiIntakeWorker(store, client).run_once() is None
    assert not client.calls and guard.run.calls == 0
    assert guard.blocked == 'acceptance estimated cost budget exhausted'
    assert read_accounting(path)['accounted_micro_usd'] == 0


def test_metadata_repair_cannot_bypass_adaptation_phase_cap(tmp_path):
    from acceptance.adapters.pipeline import _seed_stage_fixture
    from workflow import GeminiAdaptationWorker
    case = next(c for c in discover_cases(FIXTURES)
                if c.start_stage == c.end_stage == 'adaptation' and c.source_kind == 'stage_fixture')
    path = tmp_path / 'metadata.db'
    initialize_acceptance_database(path)
    with WorkflowStore(path) as store:
        _seed_stage_fixture(store, StageCase(case, 1, case.case_id))
        run = store.claim('adaptation_runs', 'adaptation_run_id', 'metadata-test')
    guard = AttemptGuard(RunGuard(10, 0, 10, 1_000_000), {'adaptation': 1}, 1_000_000)
    client = FakeGeminiClient({'private_tags': ['education', 'language'], 'hashtags': [], 'alt_text': 'A lesson.'})
    with AcceptanceStore(path, model_budget_policy=text_policy(), attempt_guard=guard) as store:
        from workflow.model_trace import generate_json
        from workflow.model_budget import ModelBudgetExceeded
        # A metadata-invalid adaptation response is already billable. The repair
        # uses another prompt version on the same claim, not another allowance.
        invocation = store.begin_model_invocation(phase='adaptation', table='adaptation_runs',
            key='adaptation_run_id', row=run, request_version='test', prompt_version='initial',
            schema_version='test', request_value={}, model_id=client.model)
        generate_json(store, invocation, client, 'fixture', {}, temperature=0.2)
        store.finish_model_invocation(invocation, outcome='schema_failed', usage=client.last_usage)
        worker = GeminiAdaptationWorker(store, client)
        request = {'destination': {'platform': 'instagram', 'output_contract_version': 'test'}}
        with pytest.raises(ModelBudgetExceeded):
            worker._retry_metadata(run, request, {'caption_summary': 'A lesson.'})
    assert len(client.calls) == guard.run.calls == 1
    assert guard.blocked == 'acceptance case provider-attempt cap reached'


def test_v2_image_error_before_return_recovers_ledger_and_partial_outputs(tmp_path, monkeypatch):
    from acceptance.adapters import pipeline
    from workflow.storyboard_planner import make_plan
    from test_storyboard_pagination import PlannedClient
    from test_acceptance_harness_offline import image_policy
    units = pipeline._fixture_adaptation('english', 6, 'english_fidelity_6_v1')['visual_units']
    client = PlannedClient(make_plan(units, 'english', calibration_capacities=[6])['boards'])
    image = replace(image_policy(), model_id=client.model)
    monkeypatch.setattr(matrix, '_policies', lambda *args: (text_policy(), image))
    monkeypatch.setattr(pipeline, 'VertexGeminiImageClient', lambda **kwargs: client)
    def no_text(**kwargs):
        raise AssertionError('frozen fixture must never construct a text provider')
    monkeypatch.setattr(pipeline, 'VertexGeminiClient', no_text)
    def fail_export(*args):
        raise OSError('SECRET output path')
    monkeypatch.setattr(pipeline, '_write_render_outputs', fail_export)
    output, info = matrix.run_matrix(profile='fidelity', dry_run=False, cli_live=True, repeat=1,
        limits={'max_usd': '5', 'max_cases': 1},
        environment={'CONTENT_FACTORY_ENABLE_LIVE_GEMINI_TESTS': '1'},
        case_directory=FIXTURES, output_root=tmp_path)
    assert len(client.calls) == info['actual_calls'] == info['actual_image_calls'] == 1
    assert not info['accounting_unresolved']
    result = json.loads(next(output.glob('cases/**/accounting.json')).read_text())
    assert len(result['invocations']) == 1  # frozen upstream fixture calls excluded
    assert result['settled_micro_usd'] > 0
    evaluation = json.loads(next(output.glob('cases/**/accounting.json')).with_name('evaluation.json').read_text())
    assert evaluation['findings'][0]['message'] == 'OSError: case execution failed'
    assert evaluation['output']['image_rendering']['status'] == 'succeeded'
    assert list(output.glob('cases/**/canonical.json'))


def test_distinct_cases_share_run_budget_without_combining_databases(tmp_path, monkeypatch):
    case_dir = tmp_path / 'cases'
    case_dir.mkdir()
    raw = json.loads((FIXTURES / 'smoke.json').read_text())
    for case_id in ('a', 'b', 'c'):
        (case_dir / f'{case_id}.json').write_text(json.dumps({**raw, 'case_id': case_id}))
    client = FakeGeminiClient(brief())
    monkeypatch.setattr(matrix, '_policies', lambda *args: (text_policy(), None))
    monkeypatch.setattr(gemini, 'VertexGeminiClient', lambda **kwargs: client)
    output, info = matrix.run_matrix(profile='smoke', dry_run=False, cli_live=True, repeat=1,
        limits={'max_usd': '1', 'max_calls': 2},
        environment={'CONTENT_FACTORY_ENABLE_LIVE_GEMINI_TESTS': '1'},
        case_directory=case_dir, output_root=tmp_path / 'runs')
    assert info['actual_calls'] == len(client.calls) == 2
    assert info['result_counts']['PASS'] == 2 and info['result_counts']['SKIP_BUDGET'] == 1
    assert len(list(output.rglob('workflow.db'))) == 2
