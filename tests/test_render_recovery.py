"""Mocked incident replay: composite authority, independent retries, and durable resume."""
from dataclasses import replace
from decimal import Decimal
from io import BytesIO
import json
from unittest.mock import patch

import pytest
from PIL import Image, ImageDraw
from google.genai.errors import APIError

from common.gemini import GeminiUsage
from common.gemini_image import GeneratedImage
from common.failure_disposition import classify_failure, FailureDisposition
from dashboard.flow import render_job_progress, render_progress_label
from workflow import WorkflowStore
from workflow.gemini_image_renderer import DispatchVisualRenderer, validate_composite_structure, split_equal_grid
from workflow.model_budget import ModelBudgetPolicy, ModelBudgetExceeded, runtime_job_limit_loader
from workflow.storyboard_planner import StoryboardPlanner, paginate
from acceptance.adapters.pipeline import _fixture_adaptation, _persist_frozen_render_fixture
from test_domain_boundaries import prepare_domain
from test_storyboard_pagination import grid_bytes
import test_gemini_workflow as fixtures


@pytest.fixture
def database():
    fixture = fixtures.GeminiWorkflowTests()
    fixture.setUp()
    yield fixture
    fixture.doCleanups()


def prepare(store, fixture):
    prepare_domain(store, fixture, 'ai_tech')
    assert _persist_frozen_render_fixture(store, _fixture_adaptation('ai_tech', 5))
    assert StoryboardPlanner(store, calibration_capacities=[2, 2, 1]).run_once()


def policy():
    return ModelBudgetPolicy('fake-image-model', Decimal('.5'), Decimal('60'),
                            10_000_000, 20_000_000, 5_000_000, {'image_rendering': (8000,8000)})


class IncidentClient:
    model = 'fake-image-model'
    last_usage = None

    def __init__(self, *, provider_before_structure=False, singleton_error=429):
        self.calls = []
        self.counts = {}
        self.provider_before_structure = provider_before_structure
        self.singleton_error = singleton_error

    def generate_image(self, prompt, *, aspect_ratio):
        slides = tuple(item['slide'] for item in json.loads(prompt.split('SLIDE_CONTENT\n')[1])['slides'])
        reinforced = 'STRUCTURAL RETRY' in prompt
        key = (slides, reinforced)
        self.calls.append((key, prompt))
        self.counts[key] = count = self.counts.get(key, 0) + 1
        self.last_usage = None
        if slides == (1, 2):
            if self.provider_before_structure and count < 3:
                raise APIError(429, {'error': {'message': 'fixture rejection'}})
            self.last_usage = GeminiUsage(2000, 1667, 3667, self.model)
            # A materially wrong provider aspect ratio cannot safely supply the planned cells.
            return GeneratedImage(grid_bytes(2, 1, '4:5'), 'image/png')
        if slides in {(1,), (2,)} and count == 1:
            if isinstance(self.singleton_error, Exception):
                raise self.singleton_error
            raise APIError(self.singleton_error, {'error': {'message': 'fixture failure'}})
        self.last_usage = GeminiUsage(2000, 1667, 3667, self.model)
        cols, rows = {1:(1,1),2:(2,1)}[len(slides)]
        return GeneratedImage(grid_bytes(cols, rows, aspect_ratio), 'image/png')


def test_five_slide_incident_completes_independent_boards_then_resumes(database, tmp_path):
    client = IncidentClient()
    with WorkflowStore(database.path) as store:
        prepare(store, database)
        worker = DispatchVisualRenderer(store, tmp_path, image_client=client, budget_policy=policy())
        with patch('workflow.store.now', return_value='2030-01-01T00:00:00'):
            assert worker.run_once() is None
        assert [key for key, _ in client.calls] == [((1,2),False),((1,2),True),((1,),False),
                                                  ((2,),False),((3,4),False),((5,),False)]
        assert [r[0] for r in store.connection.execute("SELECT slide_ordinal FROM render_units WHERE status='succeeded'")] == [3,4,5]
        assert store.connection.execute('SELECT status FROM render_runs').fetchone()[0] == 'retry_wait'
        assert 'Partial render · 3 of 5 slides completed · retry available' in render_job_progress(store.connection,1)
        checkpoints = [tuple(r) for r in store.connection.execute("SELECT slide_ordinal,checkpoint_json FROM render_units WHERE status='succeeded'")]
        rows = store.connection.execute('SELECT status,worst_case_micro_usd,settled_micro_usd FROM gemini_budget_reservations').fetchall()
        assert sum(r['status']=='released' for r in rows) == 2
        assert all(r['worst_case_micro_usd']==484000 for r in rows)
        assert all(r['settled_micro_usd']==101020 for r in rows if r['status']=='settled')
    # Reopen SQLite and instantiate a new renderer: no in-memory retry/checkpoint state.
    with WorkflowStore(database.path) as store:
        resumed = DispatchVisualRenderer(store,tmp_path,image_client=client,budget_policy=policy())
        with patch('workflow.store.now', return_value='2030-01-01T00:05:00'):
            assert resumed.run_once() is not None
        assert [key for key,_ in client.calls[-2:]] == [((1,),False),((2,),False)]
        assert [tuple(r) for r in store.connection.execute('SELECT slide_ordinal,checkpoint_json FROM render_units WHERE slide_ordinal>=3')] == checkpoints
        assert store.connection.execute('SELECT COUNT(*) FROM render_assets').fetchone()[0] == 5
        assert 'Ready for review' in render_job_progress(store.connection,1)


def test_provider_attempts_do_not_consume_structural_retry_and_keep_identical_prompt(database,tmp_path):
    with WorkflowStore(database.path) as store:
        prepare(store,database)
        client = IncidentClient(provider_before_structure=True)
        worker = DispatchVisualRenderer(store,tmp_path,image_client=client,budget_policy=policy())
        for minute in range(7):
            with patch('workflow.store.now', return_value=f'2030-01-01T00:{minute:02d}:00'):
                worker.run_once()
        assert client.counts[((1,2),False)] == 3
        assert client.counts[((1,2),True)] == 3
        for key in client.counts:
            assert len({prompt for actual,prompt in client.calls if actual==key}) == 1
        assert store.connection.execute('SELECT status FROM render_runs').fetchone()[0]=='succeeded'
        assert store.connection.execute('SELECT MAX(provider_attempt_count) FROM render_board_units').fetchone()[0]==3
        assert store.connection.execute("SELECT COUNT(*) FROM render_board_attempts WHERE status='structural_failed'").fetchone()[0]==2


@pytest.mark.parametrize('error,expected', [(403,'failed'), (TimeoutError('fixture timeout'),'succeeded')])
def test_nonretryable_and_transient_transport_isolate_boards(database,tmp_path,error,expected):
    with WorkflowStore(database.path) as store:
        prepare(store,database)
        client=IncidentClient(singleton_error=error)
        worker=DispatchVisualRenderer(store,tmp_path,image_client=client,budget_policy=policy())
        for minute in range(3):
            with patch('workflow.store.now',return_value=f'2030-01-01T00:{minute:02d}:00'):
                worker.run_once()
        assert client.counts[((3,4),False)]==1
        assert client.counts[((5,),False)]==1
        assert store.connection.execute('SELECT status FROM render_runs').fetchone()[0]==expected
        states=[r[0] for r in store.connection.execute('SELECT status FROM gemini_budget_reservations')]
        assert ('uncertain' if isinstance(error,Exception) else 'released') in states
        if expected=='failed':
            assert client.counts[((1,),False)]==1


@pytest.mark.parametrize('capacity,ratio', [(2,'3:2'),(4,'4:5'),(6,'5:4')])
def test_expected_seams_and_margins_for_all_layouts(capacity,ratio):
    total=capacity if capacity>=4 else 4
    board=paginate([dict(title='Title',body='Body')]*total,'ai_tech',
                   calibration_capacities=[capacity] if capacity>=4 else [2,2])[0]
    w,h=map(lambda x:int(x)*240,ratio.split(':'))
    canvas=Image.new('RGB',(w,h),'#eeeeee')
    draw=ImageDraw.Draw(canvas)
    for r in range(board['rows']):
        for c in range(board['cols']):
            x0=round(c*w/board['cols'])+12; x1=round((c+1)*w/board['cols'])-12
            y0=round(r*h/board['rows'])+12; y1=round((r+1)*h/board['rows'])-12
            draw.rectangle((x0,y0,x1,y1), fill=('#204050' if c%2 else '#802020'))
            draw.line((x0+25,y0+60,x1-25,y0+60),fill='black',width=5)
    stream=BytesIO();canvas.save(stream,format='PNG')
    evidence=validate_composite_structure(stream.getvalue(),board)
    assert any(s['method']=='margin' for axis in evidence['seams'].values() for s in axis)
    result=split_equal_grid(stream.getvalue(),board,structural=evidence)
    assert len(result.slides)==capacity
    assert all(im.size==(1080,1350) for im in result.slides)
    assert result.metadata['source_rectangles']==evidence['source_rectangles']


def test_displaced_seam_and_singleton_bypass():
    board=paginate([dict(title='T',body='B')]*4,'ai_tech',calibration_capacities=[2,2])[0]
    canvas=Image.new('RGB',(600,400),'#203050');canvas.paste('#a08050',(324,0,600,400))
    stream=BytesIO();canvas.save(stream,format='PNG')
    result=validate_composite_structure(stream.getvalue(),board)
    assert result['source_rectangles']==[[0,0,324,400],[324,0,600,400]]
    singleton=paginate([dict(title='T',body='B')]*4,'ai_tech',calibration_capacities=[1]*4)[0]
    with patch('workflow.gemini_image_renderer._border_connected_background',side_effect=AssertionError('must bypass')):
        assert validate_composite_structure(grid_bytes(3,4,'4:5'),singleton)['outcome']=='singleton'


@pytest.mark.parametrize('status,done,total,label',[
    ('claimed',0,5,'Rendering'), ('failed',0,5,'Render failed before any slides completed'),
    ('retry_wait',0,5,'Incomplete · retry available'),
    ('failed',3,5,'Partial render · 3 of 5 slides completed'),
    ('succeeded',5,5,'Ready for review')])
def test_dashboard_artifact_semantics(status,done,total,label):
    assert render_progress_label(status,done,total)==label


def test_runtime_limit_reload_and_job_snapshot(database,tmp_path):
    env=tmp_path/'.env';env.write_text('GEMINI_JOB_HARD_LIMIT_USD=5.00\n')
    loader=runtime_job_limit_loader(env,{})
    assert loader()==5_000_000
    env.write_text('GEMINI_JOB_HARD_LIMIT_USD=6.00\n')
    assert loader()==6_000_000
    assert runtime_job_limit_loader(env,{'GEMINI_JOB_HARD_LIMIT_USD':'7'})()==7_000_000
    with WorkflowStore(database.path,job_limit_loader=loader) as store:
        prepare(store,database)
        client=IncidentClient()
        worker=DispatchVisualRenderer(store,tmp_path/'assets',image_client=client,budget_policy=policy())
        with patch('workflow.store.now',return_value='2030-01-01T00:00:00'):
            worker.run_once()
        env.write_text('GEMINI_JOB_HARD_LIMIT_USD=0.01\n')
        with patch('workflow.store.now',return_value='2030-01-01T00:05:00'):
            assert worker.run_once() is not None
        assert {r[0] for r in store.connection.execute('SELECT job_limit_micro_usd FROM gemini_budget_reservations')}=={6_000_000}


def test_inflight_reservations_release_actual_reconcile_and_uncertainty(database):
    small=ModelBudgetPolicy('fixture',Decimal('1'),Decimal('2'),200,250,1000,{'intake':(100,50)})
    with WorkflowStore(database.path,model_budget_policy=small) as store:
        def begin(index):
            store.create_human_idea(f'An English idea {index}',command_id=f'budget-{index}')
            claim=store.claim('intake_requests','intake_request_id',f'worker-{index}')
            return store.begin_model_invocation(phase='intake',table='intake_requests',key='intake_request_id',row=claim,
                request_version='fixture',prompt_version='fixture',schema_version='fixture',request_value={},model_id='fixture')
        first=begin(1)
        with pytest.raises(ModelBudgetExceeded):begin(2)
        # An independent connection also sees the outstanding reservation.
        with WorkflowStore(database.path,model_budget_policy=small) as sibling:
            assert sibling.connection.execute("SELECT SUM(worst_case_micro_usd) FROM gemini_budget_reservations WHERE status='reserved'").fetchone()[0]==200
        store.finish_model_invocation(first,outcome='transport_failed',provider_error=APIError(429,{'error':{'message':'fixture'}}))
        second=begin(3)
        store.reconcile_model_usage(second,GeminiUsage(10,5,15,'fixture'),small)
        third=begin(4) # 20 actual + 200 in flight fits the 250 limit.
        store.finish_model_invocation(second,outcome='succeeded',usage=GeminiUsage(10,5,15,'fixture'))
        store.finish_model_invocation(third,outcome='transport_failed',provider_error=TimeoutError())
        with pytest.raises(ModelBudgetExceeded):begin(5)
        assert [tuple(r) for r in store.connection.execute('SELECT status,settled_micro_usd FROM gemini_budget_reservations')]==[
            ('released',0),('settled',20),('uncertain',None)]


def test_three_total_provider_attempts_then_terminal_without_replaying_siblings(database,tmp_path):
    class Exhausted(IncidentClient):
        def generate_image(self,prompt,*,aspect_ratio):
            slides=tuple(item['slide'] for item in json.loads(prompt.split('SLIDE_CONTENT\n')[1])['slides'])
            if slides==(1,2):
                self.calls.append((((1,2),False),prompt))
                self.last_usage=None
                raise APIError(429,{'error':{'message':'fixture'}})
            return super().generate_image(prompt,aspect_ratio=aspect_ratio)
    with WorkflowStore(database.path) as store:
        prepare(store,database)
        client=Exhausted()
        worker=DispatchVisualRenderer(store,tmp_path,image_client=client,budget_policy=policy())
        for minute in range(5):
            with patch('workflow.store.now',return_value=f'2030-01-01T00:{minute:02d}:00'):
                worker.run_once()
        assert sum(key==((1,2),False) for key,_ in client.calls)==3
        assert client.counts[((3,4),False)]==1
        assert client.counts[((5,),False)]==1
        assert store.connection.execute('SELECT status FROM render_runs').fetchone()[0]=='failed'
        assert store.connection.execute("SELECT COUNT(*) FROM render_units WHERE status='succeeded'").fetchone()[0]==3
        assert store.connection.execute("SELECT COUNT(*) FROM render_board_units WHERE lineage_kind!='planned'").fetchone()[0]==0


def test_restart_after_completed_board_and_lost_call_keeps_independent_work(database,tmp_path):
    class Interrupted(IncidentClient):
        def generate_image(self,prompt,*,aspect_ratio):
            slides=tuple(item['slide'] for item in json.loads(prompt.split('SLIDE_CONTENT\n')[1])['slides'])
            if slides==(3,4):
                raise KeyboardInterrupt()
            self.last_usage=GeminiUsage(2000,1667,3667,self.model)
            return GeneratedImage(grid_bytes(2 if len(slides)==2 else 1,1,aspect_ratio),'image/png')
    with WorkflowStore(database.path) as store:
        prepare(store,database)
        worker=DispatchVisualRenderer(store,tmp_path,image_client=Interrupted(),budget_policy=policy())
        with patch('workflow.store.now',return_value='2030-01-01T00:00:00'),pytest.raises(KeyboardInterrupt):
            worker.run_once()
        before=store.connection.execute('SELECT checkpoint_json FROM render_units WHERE slide_ordinal=1').fetchone()[0]
    with WorkflowStore(database.path) as store:
        client=IncidentClient()
        worker=DispatchVisualRenderer(store,tmp_path,image_client=client,budget_policy=policy())
        with patch('workflow.store.now',return_value='2030-01-01T01:00:00'):
            assert worker.run_once() is None
        assert [key for key,_ in client.calls]==[((5,),False)]
        assert store.connection.execute('SELECT checkpoint_json FROM render_units WHERE slide_ordinal=1').fetchone()[0]==before
        assert store.connection.execute("SELECT COUNT(*) FROM render_board_units WHERE status='ambiguous'").fetchone()[0]==1
        assert store.connection.execute("SELECT COUNT(*) FROM gemini_budget_reservations WHERE status='uncertain'").fetchone()[0]==1


def test_generated_board_resumes_local_extraction_without_new_paid_call(database,tmp_path):
    class Valid(IncidentClient):
        def generate_image(self,prompt,*,aspect_ratio):
            self.calls.append(prompt)
            self.last_usage=GeminiUsage(2000,1667,3667,self.model)
            return GeneratedImage(grid_bytes(1 if aspect_ratio=='4:5' else 2,1,aspect_ratio),'image/png')
    with WorkflowStore(database.path) as store:
        prepare(store,database)
        client=Valid()
        worker=DispatchVisualRenderer(store,tmp_path,image_client=client,budget_policy=policy())
        with patch('workflow.store.now',return_value='2030-01-01T00:00:00'), \
             patch('workflow.gemini_image_renderer.apply_overlays',side_effect=KeyboardInterrupt()), \
             pytest.raises(KeyboardInterrupt):
            worker.run_once()
        attempt=store.connection.execute('SELECT result_json FROM render_board_attempts').fetchone()[0]
        assert json.loads(attempt)['stage']=='extracted'
        assert len(client.calls)==1
    with WorkflowStore(database.path) as store:
        resumed=DispatchVisualRenderer(store,tmp_path,image_client=client,budget_policy=policy())
        with patch('workflow.store.now',return_value='2030-01-01T01:00:00'):
            assert resumed.run_once() is not None
        assert len(client.calls)==3
        assert store.connection.execute('SELECT COUNT(*) FROM gemini_budget_reservations').fetchone()[0]==3


def test_resume_between_structural_settlement_and_fallback_transition(database,tmp_path):
    with WorkflowStore(database.path) as store:
        prepare(store,database)
        client=IncidentClient()
        worker=DispatchVisualRenderer(store,tmp_path,image_client=client,budget_policy=policy())
        with patch('workflow.store.now',return_value='2030-01-01T00:00:00'), \
             patch.object(store,'split_render_board_unit',side_effect=KeyboardInterrupt()), \
             pytest.raises(KeyboardInterrupt):
            worker.run_once()
        assert len(client.calls)==1
    with WorkflowStore(database.path) as store:
        resumed=DispatchVisualRenderer(store,tmp_path,image_client=client,budget_policy=policy())
        for minute in (0,5):
            with patch('workflow.store.now',return_value=f'2030-01-01T01:{minute:02d}:00'):
                resumed.run_once()
        assert client.counts[((1,2),False)]==1
        assert client.counts[((1,2),True)]==1
        assert store.connection.execute('SELECT status FROM render_runs').fetchone()[0]=='succeeded'
