"""Offline storyboard image generation, splitting, review, and recovery contracts."""

from PIL import Image, ImageDraw, ImageFont
from common.gemini import GeminiUsage
from common.gemini_image import GeneratedImage, VertexGeminiImageClient, configured_image_model, configured_image_size
from copy import deepcopy
from dataclasses import replace
from decimal import Decimal
from hashlib import sha256
from io import BytesIO
from pathlib import Path
from test_gemini_workflow import FakeGeminiClient
from workflow.active_visual_profiles import EXPRESSION_ROLES, active_recipe, PROMPT_COMPILER_VERSION
from workflow.visual_art_direction import EXPRESSION_BREAKDOWN_BRIEF
from types import SimpleNamespace
from unittest.mock import MagicMock, patch
from workflow import GeminiAdaptationWorker, VisualPlanner, WorkflowStore
from workflow.gemini_image_renderer import DispatchVisualRenderer, OVERLAY_PROFILES, apply_overlays, build_storyboard_prompt, footer_cta_phrases, split_storyboard, split_storyboard_with_metadata
from workflow.model_budget import ModelBudgetPolicy
import json
import test_gemini_workflow as workflow_fixtures
import unittest


COLORS = ['#d03030', '#30d030', '#3030d0', '#d0d030', '#d030d0', '#30d0d0']

EXPRESSION_UNITS = [
    {'role': 'hook', 'title': 'Break the ice', 'body': 'Start a conversation and make people feel more comfortable.', 'claim_ids': []},
    {'role': 'explanation', 'title': 'What it means', 'body': 'Start a conversation and help people feel comfortable in a new situation.', 'claim_ids': []},
    {'role': 'explanation', 'title': 'When to use it', 'body': 'In a quiet room\nWith a new group\nAt a first meeting', 'claim_ids': []},
    {'role': 'example', 'title': 'In a sentence', 'body': 'She told a funny story to break the ice.\nHe asked a question to break the ice.', 'claim_ids': []},
    {'role': 'example', 'title': 'A short dialogue', 'body': 'Mia: It feels quiet in here.\nJay: I can break the ice with a question.\nMia: Great idea.', 'claim_ids': []},
    {'role': 'takeaway', 'title': 'Remember this', 'body': 'Use it in a quiet moment.\nStart with a friendly question.', 'claim_ids': []},
]


def recipe(archetype: str, *, roles: list[str]):
    domain = next(domain for domain, value in {
        'english': 'expression_breakdown_v1', 'ai_tech': 'ai_tech_explainer_v1',
        'psychology': 'psychology_explainer_v1',
    }.items() if value == archetype)
    return active_recipe(domain, list(roles))


def slide_image(index=0):
    image = Image.new('RGB', (800, 1000), COLORS[index])
    stream = BytesIO()
    image.save(stream, format='PNG')
    return stream.getvalue()


def storyboard_image(image_format='PNG'):
    image = Image.new('RGB', (1200, 960))
    draw = ImageDraw.Draw(image)
    for ordinal, color in enumerate(COLORS):
        column, row = ordinal % 3, ordinal // 3
        draw.rectangle((column * 400, row * 480, (column + 1) * 400 - 1,
                        (row + 1) * 480 - 1), fill=color)
    stream = BytesIO()
    image.save(stream, format=image_format)
    return stream.getvalue()


def storyboard_with_margins(*, margin=32, column_gutter=26, row_gutter=30, background='#b9aa9a'):
    panel_height = 450
    height = margin * 2 + panel_height * 2 + row_gutter
    panel_width = round((height * 1.25 - margin * 2 - column_gutter * 2) / 3)
    width = margin * 2 + panel_width * 3 + column_gutter * 2
    image = Image.new('RGB', (width, height), background)
    draw = ImageDraw.Draw(image)
    for ordinal, color in enumerate(COLORS):
        column, row = ordinal % 3, ordinal // 3
        left = margin + column * (panel_width + column_gutter)
        top = margin + row * (panel_height + row_gutter)
        draw.rectangle((left, top, left + panel_width - 1, top + panel_height - 1), fill=color)
    stream = BytesIO()
    image.save(stream, format='PNG')
    return stream.getvalue()


class FakeImageClient:
    model = 'fake-image-model'
    last_usage = GeminiUsage(100, 200, 300, model)

    def __init__(self, data=None, error=None, mime_type='image/png'):
        self.data = data
        self.error = error
        self.mime_type = mime_type
        self.calls = []

    def generate_image(self, prompt):
        self.calls.append(prompt)
        if self.error:
            raise self.error
        return GeneratedImage(storyboard_image() if self.data is None else self.data, self.mime_type)


class ImagePipelineTests(unittest.TestCase):
    def test_storyboard_prompt_has_exact_content_and_instructional_design_contract(self):
        value = recipe('expression_breakdown_v1', roles=EXPRESSION_ROLES)
        package = {'platform': 'instagram', 'visual_units': deepcopy(EXPRESSION_UNITS)}
        prompt = build_storyboard_prompt(package, value, pipeline_id="english")
        # Characterization of the accepted full English design brief and fixture copy.
        self.assertEqual(sha256(prompt.encode()).hexdigest(),
                         '1c58cc306f382b14f8913f54c7252ae890d3db78b57949a0ce8b6cd27d3ddee1')
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
            self.assertNotIn(field, value)
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
            build_storyboard_prompt({**package, 'platform': 'x'}, value, pipeline_id='english')

    def test_storyboard_split_and_transparent_overlays(self):
        split = split_storyboard_with_metadata(storyboard_with_margins())
        slides = split.slides
        self.assertEqual(len(slides), 6)
        self.assertFalse(split.metadata['fallback_used'])
        for actual, expected in zip(split.metadata['outer_crop_box'], [32, 32, 1209, 962]):
            self.assertLessEqual(abs(actual - expected), 5)
        for actual in [item['width'] for item in split.metadata['gutters']['vertical']]:
            self.assertLessEqual(abs(actual - 26), 5)
        self.assertLessEqual(abs(split.metadata['gutters']['horizontal'][0]['width'] - 30), 5)
        self.assertEqual(len(split.metadata['source_rectangles']), 6)
        for ordinal, (slide, color) in enumerate(zip(slides, COLORS), 1):
            self.assertEqual(slide.size, (1080, 1350))
            expected = Image.new('RGB', (1, 1), color).getpixel((0, 0))
            self.assertEqual(slide.getpixel((540, 675)), expected)
            output = apply_overlays(slide, ordinal, 6,
                                    cta_phrase='Swipe' if ordinal < 6 else None)
            self.assertEqual(output.size, (1080, 1350))
            self.assertNotEqual(output.tobytes(), slide.tobytes())
            for point in ((0, 0), (1079, 0), (0, 1349), (1079, 1349), (540, 130), (540, 1160)):
                self.assertEqual(output.getpixel(point), slide.getpixel(point))
        with self.assertRaises(ValueError):
            split_storyboard(slide_image())
        with self.assertRaises(Exception):
            split_storyboard(b'not an image')

    def test_adaptive_split_handles_different_nonwhite_margin_and_gutters(self):
        split = split_storyboard_with_metadata(storyboard_with_margins(
            margin=44, column_gutter=18, row_gutter=42, background='#58717a'))
        self.assertFalse(split.metadata['fallback_used'])
        for actual, expected in zip(split.metadata['outer_crop_box'], [44, 44, 1244, 986]):
            self.assertLessEqual(abs(actual - expected), 5)
        for actual in [item['width'] for item in split.metadata['gutters']['vertical']]:
            self.assertLessEqual(abs(actual - 18), 5)
        self.assertLessEqual(abs(split.metadata['gutters']['horizontal'][0]['width'] - 42), 5)
        for slide, color in zip(split.slides, COLORS):
            self.assertEqual(slide.getpixel((540, 675)), Image.new('RGB', (1, 1), color).getpixel((0, 0)))

    def test_split_falls_back_when_margins_and_gutters_are_not_detectable(self):
        split = split_storyboard_with_metadata(storyboard_image())
        self.assertTrue(split.metadata['fallback_used'])
        self.assertEqual(split.metadata['method'], 'equal_grid_fallback_v1')
        self.assertEqual(len(split.slides), 6)

    def test_footer_ctas_are_deterministic_and_stop_after_slide_five(self):
        self.assertEqual(footer_cta_phrases(42), footer_cta_phrases(42))
        phrases = footer_cta_phrases(42)
        self.assertEqual(phrases, ["More examples", "See more", "Keep going", "Next", "Continue", None])
        self.assertEqual(len(set(phrases[:5])), 5)
        self.assertIsNone(phrases[5])
        self.assertEqual(OVERLAY_PROFILES['english']['brand'], 'o2_english')
        self.assertNotIn('Small Steps. A Bigger You.',
                         Path('src/workflow/gemini_image_renderer.py').read_text())

    def test_english_overlay_pixels_match_accepted_baseline(self):
        # Captured from the pre-Pass-3 renderer with Pillow's bundled font, avoiding
        # platform font differences while freezing labels, geometry, color and CTA.
        expected = [
            'bc52e6a6c73164c3fa27ba1fbefc89b4b17d34f5b4f3def96026ae88fa1e60b7',
            '09c9d0ed9694ee28292dee95abb0826aa891905842907ecf4eb2e01a04544101',
            '64ba83d655413c636eebae57530a91d033cf5759968186692b14722b9ec19564',
            '62c18cb108eeb59b3884cd7ad2e8e857e8c4d68de587f197f21cb6d5e96ac4fa',
            '1b8281bf1925793c75679e9031b9e15778558c6a4365ca1e2f462acfc1e1a2cc',
            'd8c5927ea7d76f00592e270705f0e9720d58acd3fa1d87720ae9d223ddd9b1ac',
        ]
        slide = Image.new('RGB', (1080, 1350), '#e9eef1')
        with patch('workflow.gemini_image_renderer._overlay_font', return_value=ImageFont.load_default(size=32)):
            actual = [sha256(apply_overlays(slide, ordinal, 6,
                cta_phrase=footer_cta_phrases(42)[ordinal - 1]).tobytes()).hexdigest()
                for ordinal in range(1, 7)]
        self.assertEqual(actual, expected)

    def test_new_domain_overlays_have_labels_but_no_invented_brand(self):
        from workflow.gemini_image_renderer import OVERLAY_PROFILES
        slide = Image.new('RGB', (1080, 1350), '#e9eef1')
        for domain, labels in (
            ('ai_tech', ['AI / TECH', 'WHAT CHANGED', 'WHY IT MATTERS', 'USE CASE', 'LIMITS', 'TAKEAWAY']),
            ('psychology', ['PSYCHOLOGY', 'THE CONCEPT', 'WHY IT MAY HAPPEN', 'EXAMPLE', 'WHAT HELPS', 'TAKEAWAY']),
        ):
            phrases = footer_cta_phrases(42, pipeline_id=domain)
            self.assertEqual(phrases, footer_cta_phrases(42, pipeline_id=domain))
            self.assertEqual(len(set(phrases[:5])), 5)
            self.assertIsNone(phrases[-1])
            self.assertNotEqual(phrases, footer_cta_phrases(42))
            self.assertIsNone(OVERLAY_PROFILES[domain]['brand'])
            self.assertEqual(list(OVERLAY_PROFILES[domain]['labels']), labels)
            for ordinal in range(1, 7):
                output = apply_overlays(slide, ordinal, 6,
                    cta_phrase=phrases[ordinal - 1], pipeline_id=domain)
                # Lower-left footer is untouched; label and page number remain.
                box = (0, 1170, 500, 1350)
                self.assertEqual(output.crop(box).tobytes(), slide.crop(box).tobytes())
                self.assertNotEqual(output.crop((0, 0, 1080, 140)).tobytes(), slide.crop((0, 0, 1080, 140)).tobytes())
                if ordinal == 6:
                    box = (500, 1170, 1080, 1350)
                    self.assertEqual(output.crop(box).tobytes(), slide.crop(box).tobytes())

    def test_vertex_transport_makes_one_5x4_2k_call_without_references_or_retries(self):
        client = VertexGeminiImageClient(project='test', model='test-image', max_output_tokens=8000)
        response = SimpleNamespace(usage_metadata=SimpleNamespace(prompt_token_count=1,
            candidates_token_count=2, thoughts_token_count=3, total_token_count=6), candidates=[
                SimpleNamespace(finish_reason='STOP', content=SimpleNamespace(parts=[
                    SimpleNamespace(inline_data=SimpleNamespace(mime_type='image/png', data=storyboard_image()), thought=False)
                ]))])
        sdk = MagicMock()
        sdk.models.generate_content.return_value = response
        with patch('google.genai.Client', return_value=sdk) as create:
            image = client.generate_image('literal prompt')
        self.assertEqual(image, GeneratedImage(storyboard_image(), 'image/png'))
        self.assertEqual(create.call_args.kwargs['http_options'].retry_options.attempts, 1)
        kwargs = sdk.models.generate_content.call_args.kwargs
        self.assertEqual(kwargs['contents'].parts[0].text, 'literal prompt')
        self.assertEqual(len(kwargs['contents'].parts), 1)
        self.assertEqual(kwargs['config'].image_config.aspect_ratio, '5:4')
        self.assertEqual(kwargs['config'].image_config.image_size, '2K')
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
        self.assertIsNotNone(GeminiAdaptationWorker(store, FakeGeminiClient(response)).run_once())
        self.assertIsNone(VisualPlanner(store).run_once())
        value = json.loads(store.connection.execute('SELECT recipe_json FROM visual_recipes').fetchone()[0])
        self.assertEqual(value['archetype_id'], 'expression_story_scene_v1')

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
                self.assertEqual(asset['asset_role'], 'preview_png')
                self.assertEqual(asset['mime_type'], 'image/png')
                with Image.open(asset['local_path']) as image:
                    self.assertEqual(image.format, 'PNG')
                    self.assertEqual(image.size, (1080, 1350))
                    self.assertEqual(image.getpixel((540, 675)), Image.new('RGB', (1, 1), COLORS[ordinal - 1]).getpixel((0, 0)))
            manifest = json.loads(store.connection.execute('SELECT manifest_json FROM render_runs').fetchone()[0])
            self.assertEqual(manifest['renderer'], 'gemini_storyboard_designer_v1')
            self.assertEqual(manifest['prompt_version'], PROMPT_COMPILER_VERSION)
            self.assertEqual(manifest['prompt_compiler_version'], 'gemini_storyboard_prompt_v2')
            self.assertEqual(manifest['overlay']['background'], 'transparent')
            self.assertEqual(manifest['overlay']['brand_text'], 'o2_english')
            self.assertEqual(manifest['overlay']['footer_cta_phrases'], footer_cta_phrases(1))
            self.assertTrue(all(slide['footer_cta'] for slide in manifest['slides'][:5]))
            self.assertIsNone(manifest['slides'][5]['footer_cta'])
            self.assertEqual(manifest['storyboard']['columns'], 3)
            self.assertEqual(manifest['storyboard']['rows'], 2)
            self.assertTrue(manifest['storyboard']['split']['fallback_used'])
            raw = self.artifacts / 'render-1' / manifest['storyboard']['raw']['filename']
            self.assertEqual(raw.read_bytes(), storyboard_image())
            self.assertEqual(raw.name, 'raw-storyboard.png')
            self.assertEqual(manifest['storyboard']['raw']['mime_type'], 'image/png')
            self.assertNotIn(str(raw), [asset['local_path'] for asset in assets])
            self.assertEqual([slide['source_cell'] for slide in manifest['slides']], [
                {'row': 1, 'column': 1}, {'row': 1, 'column': 2}, {'row': 1, 'column': 3},
                {'row': 2, 'column': 1}, {'row': 2, 'column': 2}, {'row': 2, 'column': 3},
            ])
            self.assertEqual(store.connection.execute(
                "SELECT COUNT(*) FROM model_invocations WHERE phase='image_rendering'").fetchone()[0], 1)
            self.assertEqual(_review_preview(store.connection, review, interactive=False,
                             csrf_token='').count('<img '), 6)
            self.assertEqual(before, store.connection.execute('SELECT package_json FROM content_packages').fetchone()[0])

    def test_jpeg_storyboard_is_retained_with_its_provider_extension(self):
        with WorkflowStore(self.path) as store:
            self.prepare(store)
            worker = DispatchVisualRenderer(
                store, self.artifacts,
                image_client=FakeImageClient(storyboard_image('JPEG'), mime_type='image/jpeg'),
            )
            self.assertIsNotNone(worker.run_once(), getattr(worker, 'last_operation', None))
            manifest = json.loads(store.connection.execute('SELECT manifest_json FROM render_runs').fetchone()[0])
            raw = self.artifacts / 'render-1' / manifest['storyboard']['raw']['filename']
            self.assertEqual(raw.name, 'raw-storyboard.jpg')
            self.assertEqual(raw.read_bytes(), storyboard_image('JPEG'))
            self.assertEqual(manifest['storyboard']['raw']['mime_type'], 'image/jpeg')

    def test_image_defaults_use_configured_model_and_2k_storyboard(self):
        with patch.dict('os.environ', {}, clear=True):
            self.assertEqual(configured_image_model(), 'gemini-3.1-flash-image')
            self.assertEqual(configured_image_size(), '2K')

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


    def test_english_format_uses_its_active_gemini_profile_without_html_fallback(self):
        with WorkflowStore(self.path) as store:
            self.prepare(store)
            client = FakeImageClient()
            worker = DispatchVisualRenderer(store, self.artifacts, image_client=client)
            self.assertIsNotNone(worker.run_once())
            self.assertEqual(len(client.calls), 1)
            row = store.connection.execute('SELECT status,failure_reason FROM render_runs').fetchone()
            self.assertEqual(tuple(row), ('succeeded', None))
            self.assertEqual(store.connection.execute('SELECT COUNT(*) FROM review_requests').fetchone()[0], 1)
