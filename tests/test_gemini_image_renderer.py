"""Offline composite image generation, processing, review and recovery contracts."""
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
from common.gemini_image import VertexGeminiImageClient
from workflow.gemini_image_renderer import (
    DispatchVisualRenderer, build_image_prompt, split_composite, apply_overlays,
)
from workflow import GeminiAdaptationWorker, VisualPlanner, WorkflowStore
from workflow.model_budget import ModelBudgetPolicy
import test_gemini_workflow as workflow_fixtures
from test_gemini_workflow import FakeGeminiClient
from test_visual_system import EXPRESSION_UNITS, EXPRESSION_ROLES, recipe

COLORS = ['#d03030', '#30d030', '#3030d0', '#d0d030', '#d030d0', '#30d0d0']


def composite():
    image = Image.new('RGB', (1500, 1200))
    draw = ImageDraw.Draw(image)
    for i, color in enumerate(COLORS):
        x, y = i % 3 * 500, i // 3 * 600
        draw.rectangle((x, y, x + 499, y + 599), fill=color)
        # These narrow edge strips must disappear under the centered 4:5 crop.
        draw.rectangle((x, y, x + 4, y + 599), fill='black')
        draw.rectangle((x + 495, y, x + 499, y + 599), fill='black')
    stream = BytesIO()
    image.save(stream, format='PNG')
    return stream.getvalue()


class FakeImageClient:
    model = 'fake-image-model'
    last_usage = GeminiUsage(100, 200, 300, model)

    def __init__(self, data=None, error=None):
        self.data = composite() if data is None else data
        self.error = error
        self.calls = []

    def generate_image(self, prompt):
        self.calls.append(prompt)
        if self.error:
            raise self.error
        return self.data


class ImagePipelineTests(unittest.TestCase):
    def test_semantic_prompt_exact_text_and_no_recipe_tokens(self):
        value = recipe('expression_breakdown_v1', roles=EXPRESSION_ROLES)
        package = {'platform': 'instagram', 'visual_units': deepcopy(EXPRESSION_UNITS)}
        prompt = build_image_prompt(package, value)
        for label in ('hook', 'meaning / definition', 'when to use it / use cases',
                      'examples', 'short conversation / dialogue', 'takeaway / reminder'):
            self.assertIn(label, prompt)
        slides = json.loads(prompt[prompt.index('[{"slide"'):])
        self.assertEqual([x['title'] for x in slides], [x['title'] for x in EXPRESSION_UNITS])
        self.assertEqual([x['body'] for x in slides], [x['body'] for x in EXPRESSION_UNITS])
        for field in ('theme_id', 'composition_id', 'typography_id'):
            self.assertNotIn(value[field], prompt)
        for word in ('3×2', '5:4', 'Row-major', 'safe area', 'Do not add branding',
                     'page counters', 'footer CTA', 'top 10%', 'bottom 14%'):
            self.assertIn(word, prompt)
        value['theme_id'] = 'never_send_this'
        self.assertEqual(prompt, build_image_prompt(package, value))
        with self.assertRaises(ValueError):
            build_image_prompt({**package, 'platform': 'x'}, value)

    def test_split_order_center_crop_and_overlays(self):
        slides = split_composite(composite())
        self.assertEqual(len(slides), 6)
        for ordinal, (slide, color) in enumerate(zip(slides, COLORS), 1):
            self.assertEqual(slide.size, (1080, 1350))
            expected = Image.new('RGB', (1, 1), color).getpixel((0, 0))
            self.assertEqual(slide.getpixel((0, 600)), expected)
            self.assertEqual(slide.getpixel((1079, 600)), expected)
            output = apply_overlays(slide, ordinal, 6, brand_name='O2English')
            self.assertEqual(output.size, (1080, 1350))
            self.assertEqual(output.getpixel((500, 600)), expected)
            self.assertNotEqual(output.crop((0, 0, 1080, 126)).tobytes(), slide.crop((0, 0, 1080, 126)).tobytes())
            self.assertGreater(len(output.crop((56, 1205, 700, 1290)).getcolors(100000)), 1)
            self.assertEqual(output.tobytes(), apply_overlays(slide, ordinal, 6, brand_name='O2English').tobytes())
        with self.assertRaises(Exception):
            split_composite(b'not an image')
        stream = BytesIO()
        Image.new('RGB', (600, 600)).save(stream, format='PNG')
        with self.assertRaises(ValueError):
            split_composite(stream.getvalue())

    def test_vertex_transport_single_call_no_retries_or_references(self):
        client = VertexGeminiImageClient(project='test', model='test-image', max_output_tokens=8000)
        response = SimpleNamespace(usage_metadata=SimpleNamespace(prompt_token_count=1,
            candidates_token_count=2, thoughts_token_count=3, total_token_count=6), candidates=[
                SimpleNamespace(finish_reason='STOP', content=SimpleNamespace(parts=[
                    SimpleNamespace(inline_data=SimpleNamespace(mime_type='image/png', data=composite()), thought=False)
                ]))])
        sdk = MagicMock()
        sdk.models.generate_content.return_value = response
        with patch('google.genai.Client', return_value=sdk) as create:
            self.assertEqual(client.generate_image('literal prompt'), composite())
        self.assertEqual(create.call_args.kwargs['http_options'].retry_options.attempts, 1)
        self.assertEqual(sdk.models.generate_content.call_count, 1)
        kwargs = sdk.models.generate_content.call_args.kwargs
        self.assertEqual(kwargs['contents'], 'literal prompt')
        self.assertEqual(kwargs['config'].image_config.aspect_ratio, '5:4')
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

    def test_one_call_six_review_assets_and_immutable_inputs(self):
        from dashboard.workflow import _review_preview
        with WorkflowStore(self.path) as store:
            self.prepare(store)
            before = store.connection.execute('SELECT package_json FROM content_packages').fetchone()[0]
            client = FakeImageClient()
            worker = DispatchVisualRenderer(store, self.artifacts, image_client=client)
            review = worker.run_once()
            self.assertIsNotNone(review, getattr(worker, 'last_operation', None))
            self.assertIsNone(worker.run_once())
            self.assertEqual(len(client.calls), 1)
            assets = list(store.connection.execute('SELECT * FROM render_assets ORDER BY ordinal'))
            self.assertEqual(len(assets), 6)
            self.assertEqual([a['ordinal'] for a in assets], list(range(1, 7)))
            for asset in assets:
                with Image.open(asset['local_path']) as image:
                    self.assertEqual(image.size, (1080, 1350))
            manifest = json.loads(store.connection.execute('SELECT manifest_json FROM render_runs').fetchone()[0])
            self.assertEqual(manifest['renderer'], 'gemini_image_v1')
            self.assertTrue(manifest['review_only'])
            master = self.artifacts / 'render-1' / manifest['master_composite']['filename']
            self.assertTrue(master.is_file())
            self.assertNotIn(str(master), [a['local_path'] for a in assets])
            html = _review_preview(store.connection, review, interactive=False, csrf_token='', production=False)
            self.assertEqual(html.count('<img '), 6)
            self.assertEqual(before, store.connection.execute('SELECT package_json FROM content_packages').fetchone()[0])
            invocation = store.connection.execute("SELECT * FROM model_invocations WHERE phase='image_rendering'").fetchone()
            self.assertEqual(invocation['outcome'], 'succeeded')
            self.assertEqual(invocation['output_tokens'], 200)

    def test_generation_and_processing_fail_terminal_without_fallback(self):
        for client in (FakeImageClient(error=RuntimeError('provider failed')), FakeImageClient(data=b'bad')):
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
                        self.assertEqual(len(client.calls), 1)
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

    def test_explicit_html_path_remains_available(self):
        with WorkflowStore(self.path) as store:
            self.prepare(store)
            client = FakeImageClient()
            worker = DispatchVisualRenderer(store, self.artifacts, renderer='html', image_client=client)
            self.assertIsNotNone(worker.run_once(), getattr(worker, 'last_operation', None))
            self.assertEqual(client.calls, [])
            manifest = json.loads(store.connection.execute('SELECT manifest_json FROM render_runs').fetchone()[0])
            self.assertEqual(manifest['renderer'], 'html_playwright_v1')
