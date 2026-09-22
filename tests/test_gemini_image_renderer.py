"""Offline storyboard image generation, splitting, review, and recovery contracts."""
from copy import deepcopy
from dataclasses import replace
from decimal import Decimal
from io import BytesIO
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch
import json
import unittest

from PIL import Image, ImageDraw

from common.gemini import GeminiUsage
from common.gemini_image import VertexGeminiImageClient, configured_image_model, configured_image_size
from workflow.gemini_image_renderer import (
    DispatchVisualRenderer, EXPRESSION_BREAKDOWN_BRIEF, PROMPT_VERSION, build_storyboard_prompt,
    normalize_slide, split_storyboard, apply_overlays,
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


def storyboard_image():
    image = Image.new('RGB', (1200, 960))
    draw = ImageDraw.Draw(image)
    for ordinal, color in enumerate(COLORS):
        column, row = ordinal % 3, ordinal // 3
        draw.rectangle((column * 400, row * 480, (column + 1) * 400 - 1,
                        (row + 1) * 480 - 1), fill=color)
    stream = BytesIO()
    image.save(stream, format='PNG')
    return stream.getvalue()


class FakeImageClient:
    model = 'fake-image-model'
    last_usage = GeminiUsage(100, 200, 300, model)

    def __init__(self, data=None, error=None):
        self.data = data
        self.error = error
        self.calls = []

    def generate_image(self, prompt):
        self.calls.append(prompt)
        if self.error:
            raise self.error
        return storyboard_image() if self.data is None else self.data


class ImagePipelineTests(unittest.TestCase):
    def test_storyboard_prompt_has_exact_content_and_instructional_design_contract(self):
        value = recipe('expression_breakdown_v1', roles=EXPRESSION_ROLES)
        package = {'platform': 'instagram', 'visual_units': deepcopy(EXPRESSION_UNITS)}
        prompt = build_storyboard_prompt(package, value)
        content = json.loads(prompt.split('SLIDE_CONTENT\n')[1])
        self.assertEqual(content['total'], 6)
        self.assertEqual([slide['title'] for slide in content['slides']],
                         [unit['title'] for unit in EXPRESSION_UNITS])
        self.assertEqual([slide['body'] for slide in content['slides']],
                         [unit['body'] for unit in EXPRESSION_UNITS])
        self.assertEqual([slide['semantic_role'] for slide in content['slides']],
                         ['hook', 'meaning / definition', 'when to use it / use cases',
                          'examples', 'short conversation / dialogue', 'takeaway / reminder'])
        for field in ('theme_id', 'composition_id', 'typography_id'):
            self.assertNotIn(value[field], prompt)
        normalized = prompt.replace('\n', ' ')
        for phrase in ('single 3×2 storyboard', '5:4 aspect ratio', 'instructional clarity',
                       'one obvious reading order', 'visual elements that reinforce the lesson',
                       'bold but controlled color', 'poster collage', 'decorative elements overlapping text',
                       'excessive stickers', 'visual noise', 'thin line-art-only scenes',
                       'clearly separated from neighboring panels'):
            self.assertIn(phrase, normalized)
        self.assertIn('Archetype: expression_breakdown_v1', EXPRESSION_BREAKDOWN_BRIEF)
        self.assertIn('Do not add O2English', prompt)
        self.assertNotIn('style anchor', prompt)
        with self.assertRaises(ValueError):
            build_storyboard_prompt({**package, 'platform': 'x'}, value)

    def test_storyboard_split_normalization_and_overlays(self):
        slides = split_storyboard(storyboard_image())
        self.assertEqual(len(slides), 6)
        for ordinal, (slide, color) in enumerate(zip(slides, COLORS), 1):
            self.assertEqual(slide.size, (1080, 1350))
            expected = Image.new('RGB', (1, 1), color).getpixel((0, 0))
            self.assertEqual(slide.getpixel((540, 675)), expected)
            output = apply_overlays(slide, ordinal, 6, brand_name='O2English')
            self.assertEqual(output.size, (1080, 1350))
            self.assertNotEqual(output.crop((0, 0, 1080, 126)).tobytes(),
                                slide.crop((0, 0, 1080, 126)).tobytes())
        self.assertEqual(normalize_slide(slide_image()).size, (1080, 1350))
        with self.assertRaises(ValueError):
            split_storyboard(slide_image())
        with self.assertRaises(Exception):
            split_storyboard(b'not an image')

    def test_vertex_transport_makes_one_5x4_1k_call_without_references_or_retries(self):
        client = VertexGeminiImageClient(project='test', model='test-image', max_output_tokens=8000)
        response = SimpleNamespace(usage_metadata=SimpleNamespace(prompt_token_count=1,
            candidates_token_count=2, thoughts_token_count=3, total_token_count=6), candidates=[
                SimpleNamespace(finish_reason='STOP', content=SimpleNamespace(parts=[
                    SimpleNamespace(inline_data=SimpleNamespace(mime_type='image/png', data=storyboard_image()), thought=False)
                ]))])
        sdk = MagicMock()
        sdk.models.generate_content.return_value = response
        with patch('google.genai.Client', return_value=sdk) as create:
            self.assertEqual(client.generate_image('literal prompt'), storyboard_image())
        self.assertEqual(create.call_args.kwargs['http_options'].retry_options.attempts, 1)
        kwargs = sdk.models.generate_content.call_args.kwargs
        self.assertEqual(kwargs['contents'].parts[0].text, 'literal prompt')
        self.assertEqual(len(kwargs['contents'].parts), 1)
        self.assertEqual(kwargs['config'].image_config.aspect_ratio, '5:4')
        self.assertEqual(kwargs['config'].image_config.image_size, '1K')
        self.assertEqual(client.last_usage.output_tokens, 5)
        sdk.close.assert_called_once()


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

    def test_one_storyboard_call_splits_final_review_assets_and_preserves_inputs(self):
        from dashboard.workflow import _review_preview
        with WorkflowStore(self.path) as store:
            self.prepare(store)
            before = store.connection.execute('SELECT package_json FROM content_packages').fetchone()[0]
            client = FakeImageClient()
            worker = DispatchVisualRenderer(store, self.artifacts, image_client=client)
            review = worker.run_once()
            self.assertIsNotNone(review, getattr(worker, 'last_operation', None))
            self.assertEqual(len(client.calls), 1)
            self.assertIn('single 3×2 storyboard', client.calls[0])
            assets = list(store.connection.execute('SELECT * FROM render_assets ORDER BY ordinal'))
            self.assertEqual([asset['ordinal'] for asset in assets], list(range(1, 7)))
            for ordinal, asset in enumerate(assets, 1):
                with Image.open(asset['local_path']) as image:
                    self.assertEqual(image.size, (1080, 1350))
                    self.assertEqual(image.getpixel((540, 675)), Image.new('RGB', (1, 1), COLORS[ordinal - 1]).getpixel((0, 0)))
            manifest = json.loads(store.connection.execute('SELECT manifest_json FROM render_runs').fetchone()[0])
            self.assertEqual(manifest['renderer'], 'gemini_storyboard_designer_v1')
            self.assertEqual(manifest['prompt_version'], PROMPT_VERSION)
            self.assertEqual(manifest['template_version'], 'gemini_carousel_storyboard_v1')
            self.assertEqual(manifest['storyboard']['columns'], 3)
            self.assertEqual(manifest['storyboard']['rows'], 2)
            raw = self.artifacts / 'render-1' / manifest['storyboard']['raw']['filename']
            self.assertEqual(raw.read_bytes(), storyboard_image())
            self.assertEqual([slide['source_cell'] for slide in manifest['slides']], [
                {'row': 1, 'column': 1}, {'row': 1, 'column': 2}, {'row': 1, 'column': 3},
                {'row': 2, 'column': 1}, {'row': 2, 'column': 2}, {'row': 2, 'column': 3},
            ])
            self.assertEqual(store.connection.execute(
                "SELECT COUNT(*) FROM model_invocations WHERE phase='image_rendering'").fetchone()[0], 1)
            self.assertEqual(_review_preview(store.connection, review, interactive=False,
                             csrf_token='', production=False).count('<img '), 6)
            self.assertEqual(before, store.connection.execute('SELECT package_json FROM content_packages').fetchone()[0])

    def test_image_defaults_use_the_new_model_and_1k_storyboard(self):
        with patch.dict('os.environ', {}, clear=True):
            self.assertEqual(configured_image_model(), 'gemini-3.1-flash-image')
            self.assertEqual(configured_image_size(), '1K')

    def test_generation_and_processing_fail_terminal_without_fallback(self):
        for client in (FakeImageClient(error=RuntimeError('provider failed')), FakeImageClient(data=b'bad')):
            with self.subTest(error=client.error):
                fixture = workflow_fixtures.GeminiWorkflowTests(); fixture.setUp()
                try:
                    with WorkflowStore(fixture.path) as store:
                        original = self.fixture; self.fixture = fixture
                        self.prepare(store); self.fixture = original
                        worker = DispatchVisualRenderer(store, Path(fixture.temporary.name) / 'assets', image_client=client)
                        self.assertIsNone(worker.run_once())
                        self.assertEqual(len(client.calls), 1)
                        self.assertEqual(store.connection.execute('SELECT status FROM render_runs').fetchone()[0], 'failed')
                        self.assertEqual(store.connection.execute('SELECT COUNT(*) FROM review_requests').fetchone()[0], 0)
                finally:
                    fixture.doCleanups()

    def image_policy(self):
        return ModelBudgetPolicy('fake-image-model', Decimal('2'), Decimal('30'),
            1_000_000, 2_000_000, 1_000_000, {'image_rendering': (8000, 8000)})

    def test_storyboard_rate_settles_against_original_job_once(self):
        with WorkflowStore(self.path) as store:
            self.prepare(store)
            worker = DispatchVisualRenderer(store, self.artifacts, image_client=FakeImageClient())
            worker.image_renderer.budget_policy = self.image_policy()
            self.assertIsNotNone(worker.run_once())
            row = store.connection.execute("SELECT * FROM gemini_budget_reservations WHERE phase='image_rendering'").fetchone()
            self.assertEqual(row['content_job_id'], 1)
            self.assertEqual(row['status'], 'settled')
            self.assertEqual(row['settled_micro_usd'], 6200)
            self.assertEqual(row['worst_case_micro_usd'], 256000)
            self.assertEqual(store.connection.execute(
                "SELECT SUM(settled_micro_usd) FROM gemini_budget_reservations WHERE phase='image_rendering'").fetchone()[0], 6200)

    def test_budget_and_processing_failures_do_not_create_assets(self):
        with WorkflowStore(self.path) as store:
            self.prepare(store)
            client = FakeImageClient()
            worker = DispatchVisualRenderer(store, self.artifacts, image_client=client)
            worker.image_renderer.budget_policy = replace(self.image_policy(), job_hard_micro_usd=100)
            self.assertIsNone(worker.run_once())
            self.assertEqual(client.calls, [])
            self.assertEqual(store.connection.execute('SELECT status FROM render_runs').fetchone()[0], 'failed')
        fixture = workflow_fixtures.GeminiWorkflowTests(); fixture.setUp()
        try:
            with WorkflowStore(fixture.path) as store:
                original = self.fixture; self.fixture = fixture
                self.prepare(store); self.fixture = original
                client = FakeImageClient(); client.last_usage = None
                worker = DispatchVisualRenderer(store, Path(fixture.temporary.name) / 'assets', image_client=client)
                worker.image_renderer.budget_policy = self.image_policy()
                with patch('workflow.gemini_image_renderer.apply_overlays', side_effect=OSError('write failed')):
                    self.assertIsNone(worker.run_once())
                row = store.connection.execute("SELECT * FROM gemini_budget_reservations WHERE phase='image_rendering'").fetchone()
                self.assertEqual(row['status'], 'uncertain')
                self.assertEqual(store.connection.execute('SELECT COUNT(*) FROM render_assets').fetchone()[0], 0)
        finally:
            fixture.doCleanups()

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

    def test_explicit_html_path_remains_available(self):
        with WorkflowStore(self.path) as store:
            self.prepare(store)
            client = FakeImageClient()
            worker = DispatchVisualRenderer(store, self.artifacts, renderer='html', image_client=client)
            self.assertIsNotNone(worker.run_once(), getattr(worker, 'last_operation', None))
            self.assertEqual(client.calls, [])
