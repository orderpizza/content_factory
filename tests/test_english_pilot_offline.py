"""Exercise the pilot with the existing validator, runner and evaluators only."""
import json
from pathlib import Path

import pytest

from acceptance.evaluators.pipeline import evaluate_pipeline
from acceptance.framework import StageCase, StageExecution, Status, discover_cases
from acceptance.runners import matrix


PILOT = Path(__file__).resolve().parents[1] / 'acceptance/scenarios/english_pilot'


def test_pilot_is_discoverable_separately_without_expanding_existing_profiles():
    cases = discover_cases(PILOT)
    assert len(cases) == 6
    assert len({c.case_id for c in cases}) == 6
    assert all(c.schema_version == 2 for c in cases)
    assert len([c for c in cases if 'journey' in c.profiles]) == 5
    assert len([c for c in cases if 'stage' in c.profiles]) == 1
    assert {tag for c in cases for tag in c.tags} >= {'a1', 'a2', 'b1'}
    assert not {c.case_id for c in cases} & {c.case_id for c in discover_cases(PILOT.parent)}
    for case in cases:
        if case.end_stage == 'image_rendering':
            count = case.expectations['adaptation']['min_slides']
            assert count == case.expectations['adaptation']['max_slides']
            assert 4 <= count <= 6
            # Budget initial/reinforced boards, fallback/reinforced singletons,
            # and three provider attempts per logical request; see pilot guide.
            assert case.live_budget['image_calls'] == 9 * 6


@pytest.mark.parametrize('profile,attempts,calls,images,ceiling,admitted', [
    ('full', 12, 592, 540, '20', 6),
    ('journey', 10, 590, 540, '20', 4),
    ('stage', 2, 2, 0, '20', 2),
    # Synthetic offline capacity only: demonstrate every case can be planned
    # while retaining the smaller campaign ceiling in the execution guide.
    ('full', 12, 592, 540, '50', 12),
])
def test_pilot_dry_run_uses_real_admission_without_provider_or_database(
    tmp_path, monkeypatch, profile, attempts, calls, images, ceiling, admitted,
):
    def forbidden(*args, **kwargs):
        raise AssertionError('dry-run reached live execution or database creation')

    monkeypatch.setattr(matrix, 'authorize_live', forbidden)
    monkeypatch.setattr(matrix, 'execute_case', forbidden)
    monkeypatch.setattr(matrix, 'initialize_acceptance_database', forbidden)
    monkeypatch.setattr(matrix, '_intake_executor', forbidden)
    env = {
        'GEMINI_INPUT_COST_PER_MILLION_USD': '1.25',
        'GEMINI_OUTPUT_COST_PER_MILLION_USD': '5',
        'GEMINI_IMAGE_INPUT_COST_PER_MILLION_USD': '2',
        'GEMINI_IMAGE_OUTPUT_COST_PER_MILLION_USD': '8',
        'GEMINI_DAILY_WARNING_USD': '5',
        'GEMINI_DAILY_HARD_LIMIT_USD': '20',
        'GEMINI_JOB_HARD_LIMIT_USD': '5',
    }
    path, run = matrix.run_matrix(
        profile=profile, dry_run=True, cli_live=False, repeat=2,
        limits={'max_usd': ceiling, 'max_calls': 592, 'max_image_calls': 540, 'max_cases': 12},
        environment=env, case_directory=PILOT, output_root=tmp_path,
    )
    plan = json.loads((path / 'plan.json').read_text())['planned']
    assert len(plan) == attempts
    assert sum(p['max_calls'] for p in plan) == calls
    assert sum(p['max_image_calls'] for p in plan) == images
    assert run['actual_calls'] == run['actual_image_calls'] == 0
    assert run['estimated_cost_usd'] == '0'
    assert run['result_counts']['SKIP'] == admitted
    assert run['result_counts']['SKIP_BUDGET'] == attempts - admitted
    assert not list(path.rglob('*.db'))
    costs = json.loads((path / 'costs.json').read_text())
    assert costs['total_estimated_cost_usd'] == '0'
    assert all(row['estimated_cost_usd'] == '0' for row in costs['cases'])


def test_ambiguous_control_requires_clarification_not_fabricated_completion():
    case = next(c for c in discover_cases(PILOT) if c.case_id == 'pilot_ambiguous_input')
    stage = StageCase(case, 1, case.case_id)
    for status, expected in [('needs_clarification', Status.PASS), ('completed', Status.FAIL)]:
        evaluation = evaluate_pipeline(stage, StageExecution(
            Status.PASS, 'intake', 'offline-fake',
            output={'intake': {'status': status, 'brief': None}},
        ))
        assert evaluation.status == expected


def test_pilot_critical_target_and_slide_count_remain_hard_findings():
    case = next(c for c in discover_cases(PILOT) if c.case_id == 'pilot_a1_vocabulary')
    # A model response with the wrong count and no critical target must not be
    # waved through merely because it is an inspectable adaptation artifact.
    execution = StageExecution(Status.PASS, 'adaptation', 'offline-fake', output={
        'adaptation': {'package': {'visual_units': [{'role': 'hook'}], 'claim_mappings': []}},
    })
    evaluation = evaluate_pipeline(StageCase(case, 1, case.case_id), execution)
    assert evaluation.status == Status.FAIL
    assert {f.code for f in evaluation.findings if f.status == Status.FAIL} >= {
        'slide_bounds', 'conservation_exact_identifier_missing',
    }
