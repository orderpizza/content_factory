"""Offline acceptance of immutable pagination and complete ordered review sets."""
from copy import deepcopy
from io import BytesIO
import json
from pathlib import Path
import sqlite3
import unittest
from unittest.mock import patch
from PIL import Image, ImageDraw
from common.gemini_image import GeneratedImage, VertexGeminiImageClient, validate_provider_aspect_ratio
from dashboard.flow import render_job_progress
from dashboard.workflow import _review_preview
from workflow import WorkflowStore, GeminiAdaptationWorker
from workflow.storyboard_planner import StoryboardPlanner, paginate, make_plan, validate_plan
from workflow.gemini_image_renderer import DispatchVisualRenderer, split_equal_grid
from workflow.gemini_prompt_compiler import build_storyboard_prompt
from workflow.gemini_adaptation import _validated_body_checkpoint, adaptation_schema
from test_domain_boundaries import prepare_domain, domain_response
import test_gemini_workflow as fixtures
from test_gemini_workflow import FakeGeminiClient
from test_gemini_image_renderer import FakeImageClient


def board_bytes(board, *, width_delta=0):
    ar_width, ar_height = map(int, board['provider_aspect_ratio'].split(':'))
    width, height = ar_width * 150, ar_height * 150
    image = Image.new('RGB', (width + width_delta, height))
    cw, ch = width // board['cols'], height // board['rows']
    for cell, ordinal in enumerate(board['slide_indices']):
        x, y = cell % board['cols'] * cw, cell // board['cols'] * ch
        image.paste((ordinal * 15, 80, 130), (x, y, x + cw, y + ch))
    stream = BytesIO()
    image.save(stream, format='PNG')
    return stream.getvalue()


class PlannedClient(FakeImageClient):
    def __init__(self, boards, fail_at=None):
        super().__init__()
        self.boards, self.fail_at = boards, fail_at

    def generate_image(self, prompt, *, aspect_ratio='5:4'):
        self.calls.append(prompt)
        board = self.boards[len(self.calls)-1]
        assert aspect_ratio == board['provider_aspect_ratio']
        if len(self.calls) == self.fail_at:
            raise RuntimeError('fake provider failure')
        return GeneratedImage(board_bytes(board), 'image/png')


def sparse_units(total):
    return [dict(title='Title', body='Body') for _ in range(total)]


def persisted_boards(store):
    return json.loads(store.connection.execute('SELECT boards_json FROM storyboard_plans').fetchone()[0])


class PaginationTests(unittest.TestCase):
    def test_closed_packing_and_order(self):
        for count, expected in [(4,[4]), (6,[6]), (8,[4,4]), (10,[6,4]), (12,[6,6]), (14,[6,6,2])]:
            for domain in ('ai_tech', 'psychology'):
                boards = paginate(sparse_units(count), domain)
                self.assertEqual([b['capacity'] for b in boards], expected)
                self.assertEqual([i for b in boards for i in b['slide_indices']], list(range(1,count+1)))
                for b in boards:
                    self.assertEqual(b['capacity'], b['cols'] * b['rows'])
        for count in range(4,15):
            self.assertEqual(sum(b['capacity'] for b in paginate(sparse_units(count),'ai_tech')),count)
        self.assertEqual(len(paginate(sparse_units(6),'english')),1)
        for domain in ('english','ai_tech','psychology'):
            for count in (0,3,15,True,6.0):
                with self.assertRaises(ValueError): paginate(count,domain)
        with self.assertRaises(ValueError): paginate(sparse_units(8),'english')
        value = make_plan(sparse_units(8),'ai_tech'); value['boards'][0]['cols']=3
        with self.assertRaises(ValueError): validate_plan(value,sparse_units(8),'ai_tech')

    def test_equal_split_geometry_and_pixels(self):
        for total in (5,8,10,14):
            for board in paginate(sparse_units(total),'ai_tech'):
                split = split_equal_grid(board_bytes(board),board)
                self.assertEqual(len(split.slides),board['capacity'])
                for ordinal, slide in zip(board['slide_indices'],split.slides):
                    self.assertEqual(slide.size,(1080,1350))
                    self.assertEqual(slide.getpixel((540,675)),(ordinal*15,80,130))
                with self.assertRaises(ValueError): split_equal_grid(board_bytes(board,width_delta=1 if board['cols'] > 1 else 100),board)

    def test_closed_provider_mapping_for_every_supported_count(self):
        expected = {1: (1,1,'4:5'), 2: (2,1,'3:2'), 4: (2,2,'4:5'), 6: (3,2,'5:4')}
        seen = set()
        for domain in ('ai_tech','psychology'):
            for count in range(4,15):
                boards=paginate(sparse_units(count),domain)
                self.assertEqual(sum(b['capacity'] for b in boards),count)
                self.assertEqual([i for b in boards for i in b['slide_indices']],list(range(1,count+1)))
                for board in boards:
                    seen.add(board['capacity'])
                    self.assertEqual((board['cols'],board['rows'],board['provider_aspect_ratio']),expected[board['capacity']])
                    self.assertNotIn('aspect_ratio',board)
                    self.assertNotIn(board['provider_aspect_ratio'],('6:5','8:5'))
                    self.assertEqual((board['slide_aspect_ratio'],board['final_width'],board['final_height']),('4:5',1080,1350))
                    self.assertEqual(board['split_strategy'],'equal_grid_then_fit_4x5_v1')
        self.assertEqual(seen,set(expected))
        english=paginate(sparse_units(6),'english')[0]
        self.assertEqual(english['provider_aspect_ratio'],'5:4')
        self.assertEqual(english['split_strategy'],'english_accepted_v1')

    def test_unsupported_provider_ratio_fails_before_sdk_call_or_planning(self):
        client=VertexGeminiImageClient(project='test',model='fake')
        for ratio in ('6:5','8:5','1:1','unknown'):
            with self.assertRaises(ValueError): validate_provider_aspect_ratio(ratio)
            with patch('google.genai.Client') as provider:
                with self.assertRaises(ValueError): client.generate_image('test',aspect_ratio=ratio)
                provider.assert_not_called()
        with patch.dict('workflow.storyboard_planner.PROVIDER_ASPECT_RATIOS',{6:'6:5'}):
            with self.assertRaises(ValueError): make_plan(sparse_units(6),'ai_tech')
        plan=make_plan(sparse_units(6),'ai_tech'); plan['boards'][0]['provider_aspect_ratio']='6:5'
        with self.assertRaises(ValueError): validate_plan(plan,sparse_units(6),'ai_tech')

    def test_provider_pixel_rounding_is_tolerated_but_wrong_shapes_are_not(self):
        board=paginate(sparse_units(6),'ai_tech')[0]
        def png(width,height):
            stream=BytesIO(); Image.new('RGB',(width,height)).save(stream,format='PNG'); return stream.getvalue()
        # Divisible 3×2 grid, slightly different from nominal 5:4 and exact 4:5 cells.
        for width,height in ((1200,962),(1194,960)):
            split=split_equal_grid(png(width,height),board)
            self.assertEqual(len(split.slides),6)
            self.assertEqual(split.metadata['source_rectangles'][0],[0,0,width//3,height//2])
        for width,height in ((1200,1200),(1200,800),(1201,960),(597,478)):
            with self.assertRaises(ValueError): split_equal_grid(png(width,height),board)

    def test_center_fit_crops_each_cell_without_geometric_stretch(self):
        for count in (6,14):
            board=paginate(sparse_units(count),'ai_tech')[-1]  # 3×2 and 2×1 have non-4:5 raw cells.
            with Image.open(BytesIO(board_bytes(board))) as original:
                raw=original.copy()
            cw,ch=raw.width//board['cols'],raw.height//board['rows']
            self.assertNotEqual(cw*5,ch*4)
            draw=ImageDraw.Draw(raw)
            for cell in range(board['capacity']):
                x=(cell%board['cols'])*cw+cw//2
                y=(cell//board['cols'])*ch+ch//2
                draw.ellipse((x-35,y-35,x+35,y+35),fill=(255,255,255))
            stream=BytesIO(); raw.save(stream,format='PNG')
            split=split_equal_grid(stream.getvalue(),board)
            for cell,slide in enumerate(split.slides):
                mask=slide.convert('L').point(lambda p: 255 if p>240 else 0)
                left,top,right,bottom=mask.getbbox()
                # A direct anisotropic resize would turn this circle into an ellipse.
                self.assertLessEqual(abs((right-left)-(bottom-top)),2)
                self.assertEqual(slide.size,(1080,1350))
                self.assertEqual(split.metadata['source_rectangles'][cell],
                    [cell%board['cols']*cw,cell//board['cols']*ch,(cell%board['cols']+1)*cw,(cell//board['cols']+1)*ch])


class StoryboardBoundaryTests(unittest.TestCase):
    def fixture(self):
        f=fixtures.GeminiWorkflowTests(); f.setUp(); self.addCleanup(f.doCleanups); return f

    def prepare(self, store, f, domain, count):
        prepare_domain(store,f,domain)
        response=domain_response(f,domain)
        if count > 6:
            response['visual_units'][2:2]=[deepcopy(response['visual_units'][2]) for _ in range(count-6)]
        # Preserve the exact qualification text and all canonical claim mappings.
        result=GeminiAdaptationWorker(store,FakeGeminiClient(response)).run_once()
        self.assertIsNotNone(result)
        self.assertEqual(store.connection.execute('SELECT COUNT(*) FROM render_runs').fetchone()[0],0)
        return response

    def test_fresh_database_acceptance_english_six_ai_eight_psychology_fourteen(self):
        for domain,count,capacities in [('english',6,[6]),('ai_tech',8,[4,4]),('ai_tech',10,[6,4]),('psychology',14,[6,4,4])]:
            with self.subTest(domain=domain):
                f=self.fixture()
                with WorkflowStore(f.path) as store:
                    response=self.prepare(store,f,domain,count)
                    self.assertIsNotNone(StoryboardPlanner(store).run_once())
                    self.assertIsNone(StoryboardPlanner(store).run_once())
                    row=store.connection.execute('SELECT * FROM storyboard_plans').fetchone()
                    boards=json.loads(row['boards_json'])
                    self.assertEqual([b['capacity'] for b in boards],capacities)
                    self.assertRegex(row['created_at'],r'^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d$')
                    package=json.loads(store.connection.execute('SELECT package_json FROM content_packages').fetchone()[0])
                    self.assertEqual([{k:v for k,v in u.items() if k != 'body'} for u in package['visual_units']],response['visual_units'])
                    recipe=json.loads(store.connection.execute('SELECT recipe_json FROM visual_recipes').fetchone()[0])
                    client=FakeImageClient() if domain=='english' else PlannedClient(boards)
                    worker=DispatchVisualRenderer(store,Path(f.temporary.name)/'assets',image_client=client)
                    review=worker.run_once()
                    self.assertIsNotNone(review,worker.last_operation)
                    self.assertEqual(len(client.calls),len(boards))
                    assets=store.connection.execute('SELECT * FROM render_assets ORDER BY ordinal').fetchall()
                    self.assertEqual([a['ordinal'] for a in assets],list(range(1,count+1)))
                    for a in assets:
                        with Image.open(a['local_path']) as image: self.assertEqual(image.size,(1080,1350))
                    manifest=json.loads(store.connection.execute('SELECT manifest_json FROM render_runs').fetchone()[0])
                    self.assertEqual(manifest['storyboard_plan_id'],row['storyboard_plan_id'])
                    self.assertEqual(_review_preview(store.connection,review,interactive=False,csrf_token='').count('<img '),count)
                    html=render_job_progress(store.connection,1)
                    self.assertIn(f'{count} slides · {len(boards)} boards',html)
                    for board,prompt in zip(boards,client.calls):
                        if domain=='english': continue
                        self.assertIn(f"{board['cols']} columns and {board['rows']} rows",prompt)
                        self.assertIn('No outer margins. No gutters.',prompt)
                        self.assertIn(f"Provider board aspect ratio {board['provider_aspect_ratio']}",prompt)
                        self.assertIn('Panels must touch edge-to-edge',prompt)
                        self.assertIn('away from the extreme panel edges',prompt)
                        self.assertIn('center-fit into the final 4:5 Instagram slide',prompt)
                        self.assertNotIn('Each panel is a separate 4:5 Instagram slide',prompt)
                        exact=json.loads(prompt.split('SLIDE_CONTENT\n')[1])
                        self.assertEqual([u['slide'] for u in exact['slides']],board['slide_indices'])
                        self.assertEqual([u['body'] for u in exact['slides']], ['\n'.join(response['visual_units'][i-1]['body_lines']) for i in board['slide_indices']])
                        self.assertEqual(prompt,build_storyboard_prompt(package,recipe,pipeline_id=domain,board=board))
                    if domain!='english':
                        for expected, actual in zip(boards, manifest['boards']):
                            for key, value in expected.items(): self.assertEqual(actual[key],value)
                            self.assertEqual(actual['split']['normalization']['method'],'ImageOps.fit')
                            self.assertEqual(actual['split']['normalization']['centering'],[0.5,0.5])
                            self.assertEqual(len(actual['split']['source_rectangles']),expected['capacity'])
                        self.assertEqual([s['board_index'] for s in manifest['slides']], [b['board_index'] for b in boards for _ in b['slide_indices']])
                    self.assertEqual(store.connection.execute('PRAGMA foreign_key_check').fetchall(),[])

    def test_immutable_duplicate_and_lineage_guards(self):
        f=self.fixture()
        with WorkflowStore(f.path) as store:
            self.prepare(store,f,'ai_tech',8); StoryboardPlanner(store).run_once()
            for sql in ["UPDATE storyboard_plans SET total_slides=9", "DELETE FROM storyboard_plans",
                        "UPDATE storyboard_plan_runs SET content_package_id=999", "UPDATE render_runs SET storyboard_plan_id=999",
                        "INSERT INTO storyboard_plan_runs(content_package_id,status,attempt_limit,created_at) VALUES (1,'pending',2,'2026-01-01T00:00:00')"]:
                with self.assertRaises(sqlite3.IntegrityError): store.connection.execute(sql)
            row=store.connection.execute('SELECT * FROM storyboard_plans').fetchone()
            self.assertEqual((row['content_package_id'],row['output_request_id'],row['visual_recipe_id']),(1,1,1))

    def test_handoff_rolls_back_on_downstream_failure_and_stale_claim(self):
        f=self.fixture()
        with WorkflowStore(f.path) as store:
            self.prepare(store,f,'psychology',8)
            run=store.claim('storyboard_plan_runs','storyboard_plan_run_id','test')
            store.connection.execute("CREATE TRIGGER reject_render BEFORE INSERT ON render_runs BEGIN SELECT RAISE(ABORT,'test'); END")
            store.connection.commit()
            with self.assertRaises(sqlite3.IntegrityError): store.create_storyboard_plan(run)
            self.assertEqual(store.connection.execute('SELECT COUNT(*) FROM storyboard_plans').fetchone()[0],0)
            store.connection.execute('DROP TRIGGER reject_render')
            store.connection.execute("UPDATE storyboard_plan_runs SET lease_expires_at='2000-01-01T00:00:00'")
            store.connection.commit()
            with self.assertRaises(RuntimeError): store.create_storyboard_plan(run)
            self.assertEqual(store.connection.execute('SELECT COUNT(*) FROM storyboard_plans').fetchone()[0],0)
            self.assertIsNotNone(StoryboardPlanner(store).run_once())

    def test_partial_provider_failure_never_reviews_or_retries(self):
        f=self.fixture()
        with WorkflowStore(f.path) as store:
            self.prepare(store,f,'psychology',14); StoryboardPlanner(store).run_once()
            client=PlannedClient(persisted_boards(store),fail_at=2)
            worker=DispatchVisualRenderer(store,Path(f.temporary.name)/'assets',image_client=client)
            self.assertIsNone(worker.run_once()); self.assertIsNone(worker.run_once())
            self.assertEqual(len(client.calls),2)
            self.assertEqual(store.connection.execute('SELECT COUNT(*) FROM review_requests').fetchone()[0],0)
            self.assertEqual(store.connection.execute('SELECT COUNT(*) FROM render_assets').fetchone()[0],0)
            self.assertEqual([r[0] for r in store.connection.execute("SELECT outcome FROM model_invocations WHERE phase='image_rendering' ORDER BY model_invocation_id")],['succeeded','transport_failed'])
            self.assertEqual(list((Path(f.temporary.name)/'assets').iterdir()),[])

    def test_dynamic_readability_roles_cues_and_claims(self):
        f=self.fixture()
        for domain in ('ai_tech','psychology'):
            response=domain_response(f,domain); canonical=f.canonical_response(domain)
            schema=adaptation_schema('instagram','instagram_static_carousel_v2',domain)
            self.assertEqual(schema['properties']['visual_units']['maxItems'],14)
            for mutation in ('long','line','role','claims','count'):
                bad=deepcopy(response)
                if mutation=='long': bad['visual_units'][1]['body']='x'*281
                if mutation=='line': bad['visual_units'][1]['body']=' '.join(['word']*19)
                if mutation=='role': bad['visual_units'][1]['role']='hook'
                if mutation=='claims':
                    bad['public_text_claim_ids']=[]
                    for u in bad['visual_units']: u['claim_ids']=[]
                if mutation=='count': bad['visual_units']=bad['visual_units']*3
                with self.assertRaises(ValueError): _validated_body_checkpoint(bad,canonical,platform='instagram',pipeline_id=domain)

    def test_package_and_storyboard_handoff_are_atomic(self):
        f=self.fixture()
        with WorkflowStore(f.path) as store:
            prepare_domain(store,f,'ai_tech')
            store.connection.execute("CREATE TRIGGER reject_storyboard BEFORE INSERT ON storyboard_plan_runs BEGIN SELECT RAISE(ABORT,'test'); END")
            store.connection.commit()
            worker=GeminiAdaptationWorker(store,FakeGeminiClient(domain_response(f,'ai_tech')))
            self.assertIsNone(worker.run_once())
            for table in ('content_packages','storyboard_plan_runs','render_runs'):
                self.assertEqual(store.connection.execute(f'SELECT COUNT(*) FROM {table}').fetchone()[0],0)
            self.assertEqual(store.connection.execute('SELECT status FROM adaptation_runs').fetchone()[0],'failed')

    def test_board_invocations_fence_order_duplicate_and_expired_claim(self):
        f=self.fixture()
        with WorkflowStore(f.path) as store:
            self.prepare(store,f,'ai_tech',8); StoryboardPlanner(store).run_once()
            run=store.claim('render_runs','render_run_id','test')
            boards=persisted_boards(store)
            def begin(index):
                return store.begin_model_invocation(phase='image_rendering',table='render_runs',key='render_run_id',row=run,
                    request_version='test',prompt_version='test',schema_version='test',model_id='fake',
                    request_value={'board':boards[index-1]},board_index=index)
            with self.assertRaises(RuntimeError): begin(2)
            begin(1)
            with self.assertRaises(RuntimeError): begin(1)
            with self.assertRaises(RuntimeError): begin(2)
            store.connection.execute("UPDATE render_runs SET lease_expires_at='2000-01-01T00:00:00'")
            store.connection.commit()
            with self.assertRaises(RuntimeError): begin(2)
            self.assertIsNone(store.claim('render_runs','render_run_id','new-owner'))
            self.assertEqual(store.connection.execute('SELECT status FROM render_runs').fetchone()[0],'failed')

    def test_second_board_budget_refusal_is_terminal(self):
        from dataclasses import replace
        import test_gemini_image_renderer as image_fixtures
        f=self.fixture()
        with WorkflowStore(f.path) as store:
            self.prepare(store,f,'ai_tech',8); StoryboardPlanner(store).run_once()
            client=PlannedClient(persisted_boards(store))
            worker=DispatchVisualRenderer(store,Path(f.temporary.name)/'assets',image_client=client)
            worker.image_renderer.budget_policy=replace(image_fixtures.ImageWorkflowTests.image_policy(self),daily_hard_micro_usd=260000)
            self.assertIsNone(worker.run_once())
            self.assertEqual(len(client.calls),1)
            self.assertEqual(store.connection.execute('SELECT status FROM render_runs').fetchone()[0],'failed')
            self.assertEqual(store.connection.execute('SELECT COUNT(*) FROM review_requests').fetchone()[0],0)
            self.assertEqual([r[0] for r in store.connection.execute("SELECT outcome FROM model_invocations WHERE phase='image_rendering' ORDER BY model_invocation_id")],['succeeded','blocked'])
            self.assertIsNone(worker.run_once())

    def test_first_board_daily_budget_deferral_can_start_without_replaying_paid_work(self):
        from dataclasses import replace
        import test_gemini_image_renderer as image_fixtures
        f=self.fixture()
        with WorkflowStore(f.path) as store:
            self.prepare(store,f,'ai_tech',8); StoryboardPlanner(store).run_once()
            client=PlannedClient(persisted_boards(store))
            worker=DispatchVisualRenderer(store,Path(f.temporary.name)/'assets',image_client=client)
            policy=image_fixtures.ImageWorkflowTests.image_policy(self)
            worker.image_renderer.budget_policy=replace(policy,daily_hard_micro_usd=100)
            self.assertIsNone(worker.run_once())
            self.assertEqual(client.calls,[])
            self.assertEqual(store.connection.execute('SELECT status FROM render_runs').fetchone()[0],'retry_wait')
            store.connection.execute("UPDATE render_runs SET next_attempt_at='2000-01-01T00:00:00'")
            store.connection.commit()
            worker.image_renderer.budget_policy=policy
            self.assertIsNotNone(worker.run_once(),worker.last_operation)
            self.assertEqual(len(client.calls),2)
