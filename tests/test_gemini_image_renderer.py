"""Offline sequential image generation, processing, review and recovery contracts."""
from copy import deepcopy
from dataclasses import replace
from decimal import Decimal
from io import BytesIO
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch, MagicMock
import json
import unittest

from PIL import Image, ImageDraw

from common.gemini import GeminiUsage
from common.gemini_image import VertexGeminiImageClient, configured_image_model, configured_image_size
from workflow.gemini_image_renderer import (
    DispatchVisualRenderer, EXPRESSION_BREAKDOWN_BRIEF, GLOBAL_DESIGNER_BRIEF, PROMPT_VERSION,
    build_slide_prompt, normalize_slide, apply_overlays,
)
from workflow import GeminiAdaptationWorker, VisualPlanner, WorkflowStore
from workflow.model_budget import ModelBudgetPolicy
import test_gemini_workflow as workflow_fixtures
from test_gemini_workflow import FakeGeminiClient
from test_visual_system import EXPRESSION_UNITS, EXPRESSION_ROLES, recipe

COLORS = ['#d03030', '#30d030', '#3030d0', '#d0d030', '#d030d0', '#30d0d0']


def slide_image(index=0):
    image = Image.new('RGB', (800, 1000), COLORS[index])
    stream = BytesIO()
    image.save(stream, format='PNG')
    return stream.getvalue()


class FakeImageClient:
    model = 'fake-image-model'
    last_usage = GeminiUsage(100, 200, 300, model)

    def __init__(self, data=None, error=None, fail_at=1):
        self.data = data
        self.fail_at = fail_at
        self.error = error
        self.calls = []

    def generate_image(self, prompt, *, references=None):
        self.calls.append((prompt, references))
        if self.error and len(self.calls) == self.fail_at:
            raise self.error
        return slide_image(len(self.calls) - 1) if self.data is None else self.data


class ImagePipelineTests(unittest.TestCase):
    def test_semantic_prompt_exact_text_and_no_recipe_tokens(self):
        value = recipe('expression_breakdown_v1', roles=EXPRESSION_ROLES)
        package = {'platform': 'instagram', 'visual_units': deepcopy(EXPRESSION_UNITS)}
        for ordinal, unit in enumerate(EXPRESSION_UNITS, 1):
            prompt = build_slide_prompt(package, value, ordinal)
            content = json.loads(prompt.split('SLIDE_CONTENT\n')[1])
            self.assertEqual(content['title'], unit['title'])
            self.assertEqual(content['body'], unit['body'])
            self.assertEqual(content['slide'], ordinal)
            for field in ('theme_id', 'composition_id', 'typography_id'):
                self.assertNotIn(value[field], prompt)
            for word in ('3×2', '5:4', 'composite', 'grid', 'sheet'):
                self.assertNotIn(word, prompt.replace('worksheet-like', ''))
            for word in ('4:5', 'safe area', 'Do not add branding', 'page counters',
                         'footer CTA', 'top 10%', 'bottom 14%'):
                self.assertIn(word, prompt)
            if ordinal > 1:
                self.assertIn('preserve style but adapt composition', prompt)
                self.assertIn('slide 1 only', prompt)
                self.assertIn('vary the layout rhythm', prompt)
                self.assertNotIn('immediately previous slide', prompt)
            modified = {**value, 'theme_id': 'never_send_this'}
            self.assertEqual(prompt, build_slide_prompt(package, modified, ordinal))
        self.assertIn('style anchor', build_slide_prompt(package, value, 1))
        prompt = build_slide_prompt(package, value, 1)
        normalized_prompt = prompt.replace('\n', ' ')
        for phrase in ('senior social-media art director', 'editorial designer',
                       'premium Instagram education', 'editorial typography', 'playful asymmetry',
                       'layered shapes and color blocks', 'marker or highlighter swashes',
                       'chunky iconography', 'pale pastel blob backgrounds', 'frosted-glass blobs',
                       'pale gradients', 'thin line-art-only scenes',
                       'PowerPoint-like presentation templates'):
            self.assertIn(phrase, normalized_prompt)
        self.assertNotIn('Semantic sequence:', GLOBAL_DESIGNER_BRIEF)
        self.assertNotIn('O2English', GLOBAL_DESIGNER_BRIEF)
        self.assertIn('Archetype: expression_breakdown_v1', EXPRESSION_BREAKDOWN_BRIEF)
        for step in ('1. Hook', '2. Meaning / definition', '3. When to use it / use cases',
                     '4. Examples', '5. Short conversation / dialogue', '6. Takeaway / reminder'):
            self.assertIn(step, EXPRESSION_BREAKDOWN_BRIEF)
        with self.assertRaises(ValueError):
            build_slide_prompt({**package, 'platform': 'x'}, value, 1)

    def test_normalization_and_overlays(self):
        for ordinal, color in enumerate(COLORS, 1):
            slide = normalize_slide(slide_image(ordinal - 1))
            self.assertEqual(slide.size, (1080, 1350))
            expected = Image.new('RGB', (1, 1), color).getpixel((0, 0))
            output = apply_overlays(slide, ordinal, 6, brand_name='O2English')
            self.assertEqual(output.size, (1080, 1350))
            self.assertEqual(output.getpixel((500, 600)), expected)
            self.assertNotEqual(output.crop((0, 0, 1080, 126)).tobytes(), slide.crop((0, 0, 1080, 126)).tobytes())
            self.assertGreater(len(output.crop((56, 1205, 700, 1290)).getcolors(100000)), 1)
            self.assertEqual(output.tobytes(), apply_overlays(slide, ordinal, 6, brand_name='O2English').tobytes())
        with self.assertRaises(Exception):
            normalize_slide(b'not an image')
        stream = BytesIO()
        Image.new('RGB', (1500, 1200)).save(stream, format='PNG')
        with self.assertRaises(ValueError):
            normalize_slide(stream.getvalue())

    def test_vertex_transport_single_call_with_bounded_references_no_retries(self):
        client = VertexGeminiImageClient(project='test', model='test-image', max_output_tokens=8000)
        response = SimpleNamespace(usage_metadata=SimpleNamespace(prompt_token_count=1,
            candidates_token_count=2, thoughts_token_count=3, total_token_count=6), candidates=[
                SimpleNamespace(finish_reason='STOP', content=SimpleNamespace(parts=[
                    SimpleNamespace(inline_data=SimpleNamespace(mime_type='image/png', data=slide_image()), thought=False)
                ]))])
        sdk = MagicMock()
        sdk.models.generate_content.return_value = response
        with patch('google.genai.Client', return_value=sdk) as create:
            self.assertEqual(client.generate_image('literal prompt', references=[slide_image()]), slide_image())
        self.assertEqual(create.call_args.kwargs['http_options'].retry_options.attempts, 1)
        self.assertEqual(sdk.models.generate_content.call_count, 1)
        kwargs = sdk.models.generate_content.call_args.kwargs
        self.assertEqual(kwargs['contents'].parts[0].text, 'literal prompt')
        self.assertEqual(kwargs['contents'].parts[1].inline_data.data, slide_image())
        self.assertEqual(kwargs['contents'].parts[1].inline_data.mime_type, 'image/png')
        self.assertEqual(kwargs['config'].image_config.aspect_ratio, '4:5')
        self.assertEqual(kwargs['config'].image_config.image_size, '2K')
        self.assertEqual(client.last_usage.output_tokens, 5)
        sdk.close.assert_called_once()
        response.candidates = []
        with patch('google.genai.Client', return_value=sdk), self.assertRaises(ValueError):
            client.generate_image('empty')
        self.assertIsNotNone(client.last_usage)


class ImageWorkflowTests(unittest.TestCase):
    def setUp(self):
        self.fixture = workflow_fixtures.GeminiWorkflowTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.path = self.fixture.path
        self.artifacts = Path(self.fixture.temporary.name) / 'image-artifacts'

    def prepare(self, store):
        self.fixture.prepare_english_canonical(store)
        response = self.fixture.adaptation_response('instagram')
        response['visual_units'] = deepcopy(EXPRESSION_UNITS)
        response['visual_intent']['primary_structure'] = 'cards'
        self.assertIsNotNone(GeminiAdaptationWorker(store, FakeGeminiClient(response)).run_once())
        self.assertIsNotNone(VisualPlanner(store).run_once())
        value = json.loads(store.connection.execute('SELECT recipe_json FROM visual_recipes').fetchone()[0])
        self.assertEqual(value['archetype_id'], 'expression_breakdown_v1')

    def test_six_sequential_calls_final_review_assets_and_immutable_inputs(self):
        from dashboard.workflow import _review_preview
        with WorkflowStore(self.path) as store:
            self.prepare(store)
            before = store.connection.execute('SELECT package_json FROM content_packages').fetchone()[0]
            client = FakeImageClient()
            worker = DispatchVisualRenderer(store, self.artifacts, image_client=client)
            review = worker.run_once()
            self.assertIsNotNone(review, getattr(worker, 'last_operation', None))
            self.assertIsNone(worker.run_once())
            self.assertEqual(len(client.calls), 6)
            for index, (prompt, references) in enumerate(client.calls):
                self.assertIn(f'Slide {index + 1} of 6', prompt)
                expected = [] if index == 0 else [slide_image(0)]
                self.assertEqual(references, expected)
            assets = list(store.connection.execute('SELECT * FROM render_assets ORDER BY ordinal'))
            self.assertEqual(len(assets), 6)
            self.assertEqual([a['ordinal'] for a in assets], list(range(1, 7)))
            for asset in assets:
                with Image.open(asset['local_path']) as image:
                    self.assertEqual(image.size, (1080, 1350))
            manifest = json.loads(store.connection.execute('SELECT manifest_json FROM render_runs').fetchone()[0])
            self.assertEqual(manifest['renderer'], 'gemini_designer_v3')
            self.assertEqual(manifest['prompt_version'], PROMPT_VERSION)
            self.assertEqual(manifest['template_version'], 'gemini_carousel_designer_v3')
            self.assertTrue(manifest['review_only'])
            self.assertNotIn('master_composite', manifest)
            self.assertEqual(len(manifest['slides']), 6)
            for index, provenance in enumerate(manifest['slides'], 1):
                raw = self.artifacts / 'render-1' / provenance['raw']['filename']
                self.assertEqual(raw.read_bytes(), slide_image(index - 1))
                self.assertNotIn(str(raw), [a['local_path'] for a in assets])
                self.assertEqual(provenance['reference_ordinals'], [] if index == 1 else [1])
            self.assertEqual(store.connection.execute("SELECT COUNT(*) FROM model_invocations WHERE phase='image_rendering'").fetchone()[0], 6)
            html = _review_preview(store.connection, review, interactive=False, csrf_token='', production=False)
            self.assertEqual(html.count('<img '), 6)
            self.assertEqual(before, store.connection.execute('SELECT package_json FROM content_packages').fetchone()[0])
            invocation = store.connection.execute("SELECT * FROM model_invocations WHERE phase='image_rendering'").fetchone()
            self.assertEqual(invocation['outcome'], 'succeeded')
            self.assertEqual(invocation['output_tokens'], 200)

    def test_image_defaults_use_the_new_model_and_high_resolution(self):
        with patch.dict('os.environ', {}, clear=True):
            self.assertEqual(configured_image_model(), 'gemini-3.1-flash-image')
            self.assertEqual(configured_image_size(), '2K')

    def test_generation_and_processing_fail_terminal_without_fallback(self):
        for client in (FakeImageClient(error=RuntimeError('provider failed'), fail_at=4), FakeImageClient(data=b'bad')):
            with self.subTest(error=client.error):
                # A distinct test database for each independent failure.
                fixture = workflow_fixtures.GeminiWorkflowTests(); fixture.setUp()
                try:
                    with WorkflowStore(fixture.path) as store:
                        original = self.fixture; self.fixture = fixture
                        self.prepare(store); self.fixture = original
                        worker = DispatchVisualRenderer(store, Path(fixture.temporary.name) / 'assets', image_client=client)
                        self.assertIsNone(worker.run_once())
                        self.assertIsNone(worker.run_once())
                        self.assertEqual(len(client.calls), 4 if client.error else 1)
                        self.assertEqual(store.connection.execute('SELECT status FROM render_runs').fetchone()[0], 'failed')
                        self.assertEqual(store.connection.execute('SELECT COUNT(*) FROM review_requests').fetchone()[0], 0)
                        self.assertEqual(store.connection.execute('SELECT COUNT(*) FROM visual_plan_runs').fetchone()[0], 1)
                finally:
                    fixture.doCleanups()

    def image_policy(self):
        return ModelBudgetPolicy('fake-image-model', Decimal('2'), Decimal('30'),
            1_000_000, 2_000_000, 1_000_000, {'image_rendering': (8000, 8000)})

    def test_image_rates_settle_against_original_job(self):
        with WorkflowStore(self.path) as store:
            self.prepare(store)
            policy = self.image_policy()
            worker = DispatchVisualRenderer(store, self.artifacts, image_client=FakeImageClient())
            worker.image_renderer.budget_policy = policy
            self.assertIsNotNone(worker.run_once())
            row = store.connection.execute("SELECT * FROM gemini_budget_reservations WHERE phase='image_rendering'").fetchone()
            self.assertEqual(row['content_job_id'], 1)
            self.assertEqual(row['price_snapshot_hash'], policy.fingerprint)
            self.assertEqual(row['status'], 'settled')
            self.assertEqual(row['settled_micro_usd'], 6200)
            self.assertEqual(row['worst_case_micro_usd'], 256000)
            self.assertEqual(store.connection.execute("SELECT SUM(settled_micro_usd) FROM gemini_budget_reservations WHERE phase='image_rendering'").fetchone()[0], 37200)

    def test_job_limit_prevents_call(self):
        with WorkflowStore(self.path) as store:
            self.prepare(store)
            client = FakeImageClient()
            worker = DispatchVisualRenderer(store, self.artifacts, image_client=client)
            worker.image_renderer.budget_policy = replace(self.image_policy(), job_hard_micro_usd=100)
            self.assertIsNone(worker.run_once())
            self.assertEqual(client.calls, [])
            self.assertEqual(store.connection.execute('SELECT status FROM render_runs').fetchone()[0], 'failed')
            self.assertEqual(store.connection.execute("SELECT outcome FROM model_invocations WHERE phase='image_rendering'").fetchone()[0], 'blocked')

    def test_missing_usage_retains_uncertain_reservation_and_overlay_failure_is_terminal(self):
        with WorkflowStore(self.path) as store:
            self.prepare(store)
            client = FakeImageClient()
            client.last_usage = None
            worker = DispatchVisualRenderer(store, self.artifacts, image_client=client)
            worker.image_renderer.budget_policy = self.image_policy()
            with patch('workflow.gemini_image_renderer.apply_overlays', side_effect=OSError('write failed')):
                self.assertIsNone(worker.run_once())
            self.assertIsNone(worker.run_once())
            self.assertEqual(len(client.calls), 1)
            row = store.connection.execute("SELECT * FROM gemini_budget_reservations WHERE phase='image_rendering'").fetchone()
            self.assertEqual(row['status'], 'uncertain')
            self.assertEqual(row['worst_case_micro_usd'], 256000)
            self.assertEqual(store.connection.execute('SELECT COUNT(*) FROM render_assets').fetchone()[0], 0)
            self.assertEqual(store.connection.execute('SELECT COUNT(*) FROM review_requests').fetchone()[0], 0)
            self.assertEqual(list(self.artifacts.iterdir()), [])

    def test_lost_external_call_is_not_reclaimed(self):
        with WorkflowStore(self.path) as store:
            self.prepare(store)
            run = store.claim('render_runs', 'render_run_id', 'interrupted')
            store.begin_model_invocation(phase='image_rendering', table='render_runs', key='render_run_id', row=run,
                request_version='test', prompt_version='test', schema_version='test', request_value={}, model_id='fake')
            store.connection.execute("UPDATE render_runs SET lease_expires_at='2000-01-01T00:00:00'")
            store.connection.commit()
            client = FakeImageClient()
            self.assertIsNone(DispatchVisualRenderer(store, self.artifacts, image_client=client).run_once())
            self.assertEqual(client.calls, [])
            self.assertEqual(store.connection.execute('SELECT status FROM render_runs').fetchone()[0], 'failed')

    def test_mid_carousel_daily_budget_refusal_is_terminal(self):
        with WorkflowStore(self.path) as store:
            self.prepare(store)
            client = FakeImageClient()
            worker = DispatchVisualRenderer(store, self.artifacts, image_client=client)
            worker.image_renderer.budget_policy = replace(self.image_policy(),
                daily_warning_micro_usd=260000, daily_hard_micro_usd=260000)
            self.assertIsNone(worker.run_once())
            self.assertEqual(len(client.calls), 1)
            self.assertIsNone(worker.run_once())
            self.assertEqual(store.connection.execute('SELECT status FROM render_runs').fetchone()[0], 'failed')
            self.assertEqual(store.connection.execute('SELECT COUNT(*) FROM review_requests').fetchone()[0], 0)
            outcomes = [r[0] for r in store.connection.execute(
                "SELECT outcome FROM model_invocations WHERE phase='image_rendering' ORDER BY model_invocation_id")]
            self.assertEqual(outcomes, ['succeeded', 'blocked'])

    def test_invocation_sequence_replay_and_expired_claim_guards(self):
        with WorkflowStore(self.path) as store:
            self.prepare(store)
            run = store.claim('render_runs', 'render_run_id', 'test')
            arguments = dict(phase='image_rendering', table='render_runs', key='render_run_id', row=run,
                request_version='test', prompt_version='designer-test', schema_version='test', request_value={}, model_id='fake')
            with self.assertRaises(RuntimeError):
                store.begin_model_invocation(**arguments, image_slide_ordinal=2)
            invocation = store.begin_model_invocation(**arguments, image_slide_ordinal=1)
            with self.assertRaises(RuntimeError):
                store.begin_model_invocation(**arguments, image_slide_ordinal=2)
            store.finish_model_invocation(invocation, outcome='succeeded')
            with self.assertRaises(RuntimeError):
                store.begin_model_invocation(**arguments, image_slide_ordinal=1)
            store.connection.execute("UPDATE render_runs SET lease_expires_at='2000-01-01T00:00:00'")
            store.connection.commit()
            with self.assertRaises(RuntimeError):
                store.begin_model_invocation(**arguments, image_slide_ordinal=2)

    def test_unsupported_instagram_and_x_use_html(self):
        with WorkflowStore(self.path) as store:
            self.fixture.prepare_packages(store)
            VisualPlanner(store).run_once()
            VisualPlanner(store).run_once()
            client = FakeImageClient()
            worker = DispatchVisualRenderer(store, self.artifacts, image_client=client)
            self.assertIsNotNone(worker.run_once())
            self.assertIsNotNone(worker.run_once())
            self.assertEqual(client.calls, [])
            for row in store.connection.execute('SELECT manifest_json FROM render_runs'):
                self.assertEqual(json.loads(row[0])['renderer'], 'html_playwright_v1')

    def test_explicit_html_path_remains_available(self):
        with WorkflowStore(self.path) as store:
            self.prepare(store)
            client = FakeImageClient()
            worker = DispatchVisualRenderer(store, self.artifacts, renderer='html', image_client=client)
            self.assertIsNotNone(worker.run_once(), getattr(worker, 'last_operation', None))
            self.assertEqual(client.calls, [])
            manifest = json.loads(store.connection.execute('SELECT manifest_json FROM render_runs').fetchone()[0])
            self.assertEqual(manifest['renderer'], 'html_playwright_v1')
