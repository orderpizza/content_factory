"""Text fidelity planning and English multi-board review: no live clients."""
from copy import deepcopy
from dataclasses import replace
from fractions import Fraction
from pathlib import Path
import json

import pytest
from PIL import Image, ImageChops

from workflow.render_text_policy import (measure_slide, measure_board, assess_board,
                                        PROVISIONAL_CAPACITY_BUDGETS, POLICY_VERSION, MEASUREMENT_VERSION)
from workflow.storyboard_planner import make_plan, validate_plan, StoryboardPlanner
from workflow.gemini_prompt_compiler import build_storyboard_prompt
from workflow.gemini_image_renderer import DispatchVisualRenderer, apply_overlays, footer_cta_phrases
from workflow.gemini_adaptation import _validated_body_checkpoint, adaptation_schema
from workflow.active_visual_profiles import validate_archetype_units
from workflow import WorkflowStore, GeminiAdaptationWorker
from acceptance.adapters.pipeline import _fixture_adaptation, _write_render_inputs, _write_render_outputs
from test_domain_boundaries import prepare_domain, domain_response
import test_gemini_workflow as workflow_tests
from test_gemini_workflow import FakeGeminiClient
from test_storyboard_pagination import PlannedClient
import test_gemini_image_renderer as image_tests


def units(words):
    return [dict(title=f'T{i}', body=' '.join(['w'] * (n-1))) for i, n in enumerate(words)]


def capacities(plan):
    return [b['capacity'] for b in plan['boards']]


def test_measurement_literal_unicode_whitespace_and_regions():
    value = measure_slide(dict(title='Hi 한글', body='one two\n\n  café\nthree-four'))
    assert value == dict(title_characters=5, title_words=2, body_characters=26, body_words=4,
                         title_non_empty_lines=1, body_non_empty_lines=3, total_words=6,
                         total_characters=31, total_lines=4, total_text_regions=2,
                         longest_line_characters=10, longest_line_words=2)
    assert measure_slide(dict(title='', body=' \n'))['total_text_regions'] == 0
    board = measure_board([value, value])
    assert board == dict(slide_count=2, total_characters=62, total_words=12, total_lines=8,
                        total_text_regions=4, maximum_slide_characters=31, maximum_slide_words=6,
                        maximum_slide_lines=4)


@pytest.mark.parametrize('capacity', [1, 2, 4, 6])
def test_capacity_specific_hard_constraints(capacity):
    slides = [measure_slide(u) for u in units([2]*capacity)]
    assert not assess_board(slides, capacity)[1]
    for key, maximum in PROVISIONAL_CAPACITY_BUDGETS[capacity]['slide'].items():
        over = deepcopy(slides); over[0][key] = maximum + 1
        assert f'slide:1:{key}' in assess_board(over, capacity)[1]
    for key, maximum in PROVISIONAL_CAPACITY_BUDGETS[capacity]['board'].items():
        over = deepcopy(slides); over[0][key] = maximum + 1
        assert f'board:{key}' in assess_board(over, capacity)[1]


@pytest.mark.parametrize('words,expected', [([10]*6,[6]), ([20]*4+[50]*2,[4,2]),
    ([50]*2+[20]*4,[2,4]), ([30]*6,[2,2,2]), ([70]*6,[1]*6)])
def test_contiguous_text_packing_and_stable_repeatability(words, expected):
    content = units(words); before = deepcopy(content)
    plan = make_plan(content, 'english')
    assert capacities(plan) == expected
    assert [i for b in plan['boards'] for i in b['slide_indices']] == list(range(1,7))
    assert all(not b['budget_violations'] for b in plan['boards'])
    assert content == before
    assert all(make_plan(content,'english') == plan for _ in range(5))
    assert validate_plan(plan,content,'english') == plan
    for b in plan['boards']:
        assert b['measurement_version'] == MEASUREMENT_VERSION
        assert b['text_policy_version'] == POLICY_VERSION
    forged = deepcopy(plan); forged['boards'][0]['slide_text_load'][0]['total_words'] += 1
    with pytest.raises(ValueError): validate_plan(forged,content,'english')


def test_density_headroom_beats_largest_first_and_stable_tie():
    content = units([15]*8)
    plan = make_plan(content,'ai_tech')
    assert capacities(plan) == [4,4]
    larger = make_plan(content,'ai_tech',calibration_capacities=[6,2])
    density = lambda p: max(Fraction(**b['density']) for b in p['boards'])
    assert density(plan) < density(larger)
    assert capacities(make_plan(units([15]*10),'ai_tech')) == [6,4]


@pytest.mark.parametrize('total', [8,10,12,14])
def test_dynamic_dense_content_stays_unchanged(total):
    content = units([30]*total)
    plan = make_plan(content,'psychology')
    assert capacities(plan) == [2]*(total//2)
    assert plan['total_slides'] == total
    assert [i for b in plan['boards'] for i in b['slide_indices']] == list(range(1,total+1))


def test_no_valid_partition_and_forced_policy_violations_are_explicit():
    content = units([81]*6)
    with pytest.raises(ValueError, match='single slides'): make_plan(content,'english')
    plan = make_plan(content,'english',calibration_capacities=[6])
    assert plan['boards'][0]['budget_violations']
    assert plan['boards'][0]['planning_mode'] == 'forced_fidelity_experiment_v1'
    validate_plan(plan,content,'english')
    with pytest.raises(ValueError): make_plan(content,'english',calibration_capacities=[4,1])


def test_english_sparse_and_accepted_denser_fixture():
    assert capacities(make_plan(_fixture_adaptation('english',6)['visual_units'],'english')) == [6]
    content = _fixture_adaptation('english',6,'english_fidelity_6_v1')['visual_units']
    assert capacities(make_plan(content,'english')) == [2,2,2]


@pytest.mark.parametrize('domain', ['ai_tech','psychology'])
def test_copy_prompt_policy_edges_and_schema_bounds(domain):
    f = workflow_tests.GeminiWorkflowTests(); response = domain_response(f,domain)
    def check(value):
        return _validated_body_checkpoint(value,f.canonical_response(domain),platform='instagram',pipeline_id=domain)
    for field,copy in [('title',' '.join(['x']*11)),('body',' '.join(['x']*17)),
                       ('body','one\ntwo\nthree\nfour'),('body',' '.join(['x']*16)+'\n'+' '.join(['x']*15))]:
        invalid = deepcopy(response); invalid['visual_units'][1][field] = copy
        with pytest.raises(ValueError): check(invalid)
    response['visual_units'][1]['title'] = ' '.join(['t']*10)
    response['visual_units'][1]['body'] = ' '.join(['w']*15)+'\n'+' '.join(['w']*15)
    check(response)
    for id in (f'{domain}_explainer_v1',): validate_archetype_units(response['visual_units'],id)
    schema = adaptation_schema('instagram','instagram_static_carousel_v2',domain)['properties']
    assert schema['visual_units']['items']['properties']['title']['maxLength'] == 80
    assert schema['visual_units']['items']['properties']['body']['maxLength'] == 280
    assert schema['alt_text']['maxLength'] == 1000
    assert schema['caption_summary']['maxLength'] == 1100


@pytest.fixture
def workflow_fixture():
    f = workflow_tests.GeminiWorkflowTests(); f.setUp()
    yield f
    f.doCleanups()


def prepare_dense_english(store, f, forced=None):
    prepare_domain(store,f,'english')
    response = _fixture_adaptation('english',6,'english_fidelity_6_v1')
    assert GeminiAdaptationWorker(store,FakeGeminiClient(response)).run_once() is not None
    before = dict(store.connection.execute('SELECT * FROM content_packages').fetchone())
    assert StoryboardPlanner(store,calibration_capacities=forced).run_once() is not None
    assert dict(store.connection.execute('SELECT * FROM content_packages').fetchone()) == before
    row = store.connection.execute('SELECT * FROM storyboard_plans').fetchone()
    assert row['schema_version'] == 'storyboard_plan_v3'
    return json.loads(before['package_json']), json.loads(row['boards_json'])


@pytest.mark.parametrize('forced', [None,[6],[4,2],[2,2,2],[1]*6])
def test_english_multi_board_exact_prompts_provenance_overlays_and_review(workflow_fixture, tmp_path, forced):
    f = workflow_fixture
    with WorkflowStore(f.path) as store:
        package, boards = prepare_dense_english(store,f,forced)
        recipe = json.loads(store.connection.execute('SELECT recipe_json FROM visual_recipes').fetchone()[0])
        client = PlannedClient(boards)
        worker = DispatchVisualRenderer(store,tmp_path,image_client=client,budget_policy=image_tests.ImageWorkflowTests.image_policy(f))
        _write_render_inputs(store,tmp_path)
        assert worker.run_once() is not None
        manifest = json.loads(store.connection.execute('SELECT manifest_json FROM render_runs').fetchone()[0])
        assert 'storyboard' not in manifest
        assert len(client.calls) == len(boards) == len(manifest['boards'])
        assert len(manifest['slides']) == 6
        assert [s['ordinal'] for s in manifest['slides']] == list(range(1,7))
        for b, prompt, actual in zip(boards,client.calls,manifest['boards']):
            assert prompt == build_storyboard_prompt(package,recipe,pipeline_id='english',board=b)
            exact = json.loads(prompt.split('SLIDE_CONTENT\n')[1])
            assert [s['slide'] for s in exact['slides']] == b['slide_indices']
            for i, u in enumerate(package['visual_units'],1):
                assert (u['body'] in [s['body'] for s in exact['slides']]) == (i in b['slide_indices'])
            raw = tmp_path/'render-1'/actual['raw']['filename']
            assert raw.exists() and actual['provider_latency_ms'] >= 0
            assert actual['text_policy_version'] == POLICY_VERSION
            for key in b: assert b[key] == actual[key]
        if len(boards)>1:
            common = [p.split('CAROUSEL_VISUAL_CONTRACT\n')[1].split('\nSEMANTIC_CUES')[0] for p in client.calls]
            assert len(set(common)) == 1
            identities = [p.split('ACCOUNT_VISUAL_IDENTITY\n')[1].split('\nSEMANTIC_CUES')[0] for p in client.calls]
            assert len(set(identities)) == 1
        ctas = footer_cta_phrases(1,6,pipeline_id='english')
        for s in manifest['slides']:
            ordinal = s['ordinal']; b = boards[s['board_index']-1]
            assert ordinal in b['slide_indices']
            color = (ordinal*15,80,130)
            expected = apply_overlays(Image.new('RGB',(1080,1350),color),ordinal,6,
                                      cta_phrase=ctas[ordinal-1],pipeline_id='english')
            with Image.open(tmp_path/'render-1'/s['final']['filename']) as actual:
                assert ImageChops.difference(actual,expected).getbbox() is None
        ledger = store.connection.execute("SELECT * FROM model_invocations WHERE phase='image_rendering' ORDER BY attempt_ordinal").fetchall()
        assert [r['attempt_ordinal'] for r in ledger] == list(range(1,len(boards)+1))
        assert all(r['outcome']=='succeeded' for r in ledger)
        assert store.connection.execute("SELECT COUNT(*) FROM gemini_budget_reservations WHERE phase='image_rendering'").fetchone()[0] == len(boards)
        assert store.connection.execute('SELECT COUNT(*) FROM review_requests').fetchone()[0] == 1
        _write_render_outputs({'image_rendering':{'manifest':manifest}},tmp_path)
        review = json.loads((tmp_path/'fidelity-review.json').read_text())
        assert review['slides'][0]['expected_body'] == package['visual_units'][0]['body']
        assert all(s['exact_text'] is None for s in review['slides'])


@pytest.mark.parametrize('failure', ['budget','provider'])
def test_english_later_board_failure_keeps_ledger_without_partial_review(workflow_fixture,tmp_path,failure):
    f=workflow_fixture
    with WorkflowStore(f.path) as store:
        _,boards=prepare_dense_english(store,f)
        client=PlannedClient(boards,fail_at=2 if failure=='provider' else None)
        policy=image_tests.ImageWorkflowTests.image_policy(f)
        if failure=='budget': policy=replace(policy,daily_hard_micro_usd=260000)
        worker=DispatchVisualRenderer(store,tmp_path,image_client=client,budget_policy=policy)
        assert worker.run_once() is None
        assert worker.run_once() is None
        outcomes=[r[0] for r in store.connection.execute("SELECT outcome FROM model_invocations WHERE phase='image_rendering' ORDER BY model_invocation_id")]
        assert outcomes == ['succeeded','blocked' if failure=='budget' else 'transport_failed']
        assert store.connection.execute('SELECT COUNT(*) FROM review_requests').fetchone()[0]==0
        assert store.connection.execute('SELECT COUNT(*) FROM render_assets').fetchone()[0]==0
        assert list(tmp_path.iterdir()) == []


def test_english_copy_bounds_preserve_required_turns_and_reject_unbounded_titles():
    original = _fixture_adaptation('english',6)['visual_units']
    for field, index, value in [('title',1,' '.join(['word']*13)),
                              ('body',1,'one\ntwo\nthree\nfour\nfive\nsix'),
                              ('body',4,'First turn\nSecond turn\nThird turn')]:
        invalid=deepcopy(original); invalid[index][field]=value
        with pytest.raises(ValueError):validate_archetype_units(invalid,'expression_breakdown_v1')
    validate_archetype_units(original,'expression_breakdown_v1')
