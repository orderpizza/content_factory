"""All domain review boundaries; temporary databases and fake providers only."""

from common.timestamps import serialize_timestamp
from copy import deepcopy
from dashboard.flow import render_job
from dashboard.planning import render_threads
from datetime import datetime, timezone
from detection.collector import DetectionCollector
from detection.models import CollectedItem, CollectionResult
from detection.scout import DetectionScout
from detection.store import DetectionStore
from hashlib import sha256
from pathlib import Path
from PIL import Image
from test_gemini_image_renderer import FakeImageClient
import test_gemini_image_renderer as image_fixtures
from test_gemini_workflow import FakeGeminiClient
from test_semantic_detection import FakeEncoder
from unittest.mock import patch
from workflow import GeminiAdaptationWorker, GeminiDeterminationWorker, GeminiPipelineRunner, VisualPlanner, WorkflowStore
from workflow.gemini_image_renderer import DispatchVisualRenderer, OVERLAY_PROFILES, build_storyboard_prompt, supports_image_rendering
from workflow.gemini_adaptation import _validated_body_checkpoint
from workflow.active_visual_profiles import (DOMAIN_ARCHETYPES, EXPLAINER_ROLES,
                                             EXPRESSION_ROLES,
                                             active_recipe, validate_recipe,
                                             validate_recipe_roles)
import json
import test_gemini_workflow as fixtures
import unittest


DOMAINS = ('english', 'ai_tech', 'psychology')

EXPRESSION_UNITS = [
    {'role': 'hook', 'title': 'Break the ice',
     'body': 'Start a conversation and make people feel more comfortable.', 'claim_ids': []},
    {'role': 'explanation', 'title': 'What it means',
     'body': 'Start a conversation and help people feel comfortable in a new situation.', 'claim_ids': []},
    {'role': 'explanation', 'title': 'When to use it',
     'body': 'In a quiet room\nWith a new group\nAt a first meeting', 'claim_ids': []},
    {'role': 'example', 'title': 'In a sentence',
     'body': 'She told a funny story to break the ice.\nHe asked a question to break the ice.', 'claim_ids': []},
    {'role': 'example', 'title': 'A short dialogue',
     'body': 'Mia: It feels quiet in here.\nJay: I can break the ice with a question.\nMia: Great idea.', 'claim_ids': []},
    {'role': 'takeaway', 'title': 'Remember this',
     'body': 'Use it in a quiet moment.\nStart with a friendly question.', 'claim_ids': []},
]


def domain_response(fixture, domain):
    response = fixture.adaptation_response('instagram', claim_id=f'{domain}.example.1')
    if domain == 'english':
        response['visual_units'] = deepcopy(EXPRESSION_UNITS)
        return response
    copy = {
        'ai_tech': [
            ('Prepare an opening question', 'A hypothetical AI assistant can help draft a meeting opener.'),
            ('A drafting workflow', 'Provide the meeting context and ask for a neutral opening question.'),
            ('From context to a draft', 'The supplied context shapes a suggested question for human review.'),
            ('An illustrative use case', 'A fictional host asks an assistant to draft a question for a first team meeting.'),
            ('Review before using', 'Review tone and accuracy yourself. This conceptual example makes no product availability claim.'),
            ('Use it as a draft', 'Keep the useful suggestion and review it before the meeting.'),
        ],
        'psychology': [
            ('A quiet first meeting', 'People may hesitate when joining an unfamiliar group.'),
            ('Social uncertainty', 'Silence can reflect uncertainty about how to participate.'),
            ('One possible mechanism', 'A low-stakes prompt may reduce ambiguity; participants may also simply need more time.'),
            ('An everyday scenario', 'In a fictional meeting, a host offers an optional neutral question before the agenda.'),
            ('Leave room to respond', 'Make participation optional and allow people time to think.'),
            ('Ask with care', 'Offer an opening without assuming motives. This is a general interpretation, not a diagnosis.'),
        ],
    }[domain]
    response['visual_units'] = [
        {'role': role, 'title': title, 'body': body,
         'claim_ids': [f'{domain}.example.1'] if role == 'example' else []}
        for role, (title, body) in zip(EXPLAINER_ROLES, copy)
    ]
    response['hashtags'] = []
    return response


def prepare_domain(store, fixture, domain, origin='human', canonical_content=None):
    fixture.register_catalog(store)
    if origin == 'human':
        fixture.create_determination_request(store)
    else:
        at = datetime(2026, 9, 22, 8, tzinfo=timezone.utc)
        evidence = CollectionResult((CollectedItem('lesson', 'A practical learning lesson', 100,
            rank=1, provider_time=serialize_timestamp(at)),), (), True, 'a'*64, 1)
        with DetectionStore(fixture.path) as detection:
            with patch('detection.collector.collect_source', return_value=evidence):
                DetectionCollector(detection).run_due(now=at,
                    source_ids={'hacker_news_top_stories_v1', 'openai_news_rss_v1'})
            scout = DetectionScout(detection, encoder=FakeEncoder())
            evaluate = scout._evaluate
            def eligible(*args):
                result = evaluate(*args)
                for candidate in result['candidates']:
                    candidate.update(eligible=True, eligibility_reason='fixture_handoff')
                return result
            with patch.object(scout, '_evaluate', side_effect=eligible):
                scout.run(now=at)
        fixture.assertEqual(store.connection.execute('SELECT COUNT(*) FROM intake_requests').fetchone()[0], 0)
    snapshot = store.connection.execute('SELECT input_snapshot_json FROM determination_requests').fetchone()
    catalog = json.loads(snapshot[0])['catalog']
    fixture.assertIsNotNone(GeminiDeterminationWorker(store,
        FakeGeminiClient(fixture.decision(catalog, selected_pipeline=domain))).run_once())
    fixture.assertIsNotNone(GeminiPipelineRunner(store,
        FakeGeminiClient(canonical_content or fixture.canonical_response(domain))).run_once())
    fixture.assertIsNotNone(VisualPlanner(store).run_once())


class DomainBoundaryTests(unittest.TestCase):
    def fixture(self):
        fixture = fixtures.GeminiWorkflowTests()
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        return fixture

    def test_both_origins_reach_six_review_assets_for_every_domain(self):
        for origin in ('human', 'trend'):
            for domain in DOMAINS:
                with self.subTest(origin=origin, domain=domain):
                    fixture = self.fixture()
                    with WorkflowStore(fixture.path) as store:
                        prepare_domain(store, fixture, domain, origin)
                        response = domain_response(fixture, domain)
                        json_client = FakeGeminiClient(response)
                        self.assertIsNotNone(GeminiAdaptationWorker(store, json_client).run_once())
                        if domain == 'english':
                            self.assertIn('exactly six visual units in this order', json_client.calls[0]['prompt'])
                            self.assertIn('short dialogue', json_client.calls[0]['prompt'])
                            self.assertIn('never return a two-turn dialogue', json_client.calls[0]['prompt'])
                        else:
                            self.assertIn('exactly six visual units', json_client.calls[0]['prompt'])
                            self.assertIn('qualification' if domain == 'psychology' else 'Limitations / caveats', json_client.calls[0]['prompt'])
                        self._render_and_check(store, fixture, domain, origin)

    def _render_and_check(self, store, fixture, domain, origin):
        self.assertIsNone(VisualPlanner(store).run_once())
        client = (FakeImageClient() if origin == "human" else
                  FakeImageClient(image_fixtures.storyboard_image("JPEG"), mime_type="image/jpeg"))
        artifact_root = Path(fixture.temporary.name) / 'review-assets'
        renderer = DispatchVisualRenderer(store, artifact_root, image_client=client)
        renderer.image_renderer.budget_policy = image_fixtures.ImageWorkflowTests.image_policy(self)
        review = renderer.run_once()
        self.assertIsNotNone(review, renderer.last_operation)
        self.assertEqual(len(client.calls), 1)
        self.assertIsNone(renderer.run_once())
        self.assertEqual(len(client.calls), 1)
        package = json.loads(store.connection.execute('SELECT package_json FROM content_packages').fetchone()[0])
        recipe_row = store.connection.execute('SELECT * FROM visual_recipes').fetchone()
        selected = json.loads(recipe_row['recipe_json'])
        self.assertEqual(selected['archetype_id'], {'english': 'expression_story_scene_v1', 'ai_tech': 'ai_tech_explainer_v1', 'psychology': 'psychology_human_scenario_v1'}[domain])
        self.assertEqual(len(package['visual_units']), 6)
        if domain != 'english':
            self.assertEqual([unit['role'] for unit in package['visual_units']], list(EXPLAINER_ROLES))
        self.assertEqual(json.loads(recipe_row['selection_provenance_json'])['strategy'], 'deterministic_archetype_selector_v1')
        content = json.loads(client.calls[0].split('SLIDE_CONTENT\n')[1])
        self.assertEqual([(slide['title'], slide['body']) for slide in content['slides']],
                         [(unit['title'], unit['body']) for unit in package['visual_units']])
        if domain != 'english':
            self.assertTrue(all('semantic_role' not in slide for slide in content['slides']))
            self.assertNotIn('Semantic sequence:', client.calls[0])
            self.assertIn('The supplied title and body are the only text', client.calls[0])
        if domain == 'psychology':
            self.assertIn('qualified', client.calls[0])
            self.assertIn('alternative explanations', client.calls[0])
        manifest = json.loads(store.connection.execute('SELECT manifest_json FROM render_runs').fetchone()[0])
        self.assertEqual(manifest['pipeline_id'], domain)
        self.assertEqual(manifest['archetype_id'], selected['archetype_id'])
        self.assertEqual(manifest['prompt_version'], 'gemini_storyboard_prompt_v2')
        self.assertEqual(manifest['overlay']['brand_text'], 'o2_english' if domain == 'english' else None)
        self.assertEqual(manifest['storyboard']['prompt_sha256'], sha256(client.calls[0].encode()).hexdigest())
        self.assertEqual(len(list(artifact_root.rglob('raw-storyboard.*'))), 1)
        raw_path = next(artifact_root.rglob('raw-storyboard.*'))
        raw = raw_path.read_bytes()
        self.assertEqual(raw_path.suffix, '.png' if origin == 'human' else '.jpg')
        self.assertEqual(manifest['storyboard']['raw']['mime_type'], client.mime_type)
        self.assertEqual(manifest['storyboard']['raw']['sha256'], sha256(raw).hexdigest())
        self.assertEqual(manifest['storyboard']['raw']['bytes'], len(raw))
        assets = store.connection.execute('SELECT * FROM render_assets ORDER BY ordinal').fetchall()
        self.assertEqual(len(assets), 6)
        for ordinal, asset in enumerate(assets, 1):
            self.assertEqual((asset['asset_role'], asset['ordinal']), ('preview_png', ordinal))
            data = Path(asset['local_path']).read_bytes()
            self.assertEqual((asset['bytes'], asset['sha256']), (len(data), sha256(data).hexdigest()))
            with Image.open(asset['local_path']) as image:
                self.assertEqual((image.format, image.size), ('PNG', (1080, 1350)))
        invocation = store.connection.execute("SELECT * FROM model_invocations WHERE phase='image_rendering'").fetchall()
        self.assertEqual(len(invocation), 1)
        self.assertEqual(invocation[0]['prompt_version'], manifest['prompt_version'])
        reservations = store.connection.execute("SELECT * FROM gemini_budget_reservations WHERE phase='image_rendering'").fetchall()
        self.assertEqual(len(reservations), 1)
        self.assertEqual((reservations[0]['status'], reservations[0]['settled_micro_usd']), ('settled', 6200))
        lineage = store.connection.execute(
            'SELECT COUNT(*) FROM canonical_contents c JOIN output_requests o USING(canonical_content_id) '
            'JOIN adaptation_runs a USING(output_request_id) '
            'JOIN content_packages p ON p.adaptation_run_id=a.adaptation_run_id '
            'JOIN visual_plan_runs v ON v.output_request_id=o.output_request_id '
            'JOIN visual_recipes vr USING(visual_plan_run_id) '
            'JOIN render_runs r USING(visual_recipe_id) '
            'JOIN review_requests rr ON rr.render_run_id=r.render_run_id AND rr.content_package_id=p.content_package_id'
        ).fetchone()[0]
        self.assertEqual(lineage, 1)
        html = render_threads(store.connection, interactive=True) + render_job(store.connection, 1)
        self.assertNotIn('Post now', html)
        self.assertEqual(html.count('<img '), 6)
        for asset in assets:
            self.assertIn(f"/asset?render_asset_id={asset['render_asset_id']}", html)

    def test_invalid_adaptation_shapes_fail_before_package_or_image_call(self):
        for domain in ('ai_tech', 'psychology'):
            for violation in ('five', 'seven', 'ordering', 'missing_position', 'empty_position',
                              'long_title', 'long_body', 'unmapped_claim'):
                with self.subTest(domain=domain, violation=violation):
                    fixture = self.fixture()
                    with WorkflowStore(fixture.path) as store:
                        prepare_domain(store, fixture, domain)
                        response = domain_response(fixture, domain)
                        units = response['visual_units']
                        if violation == 'five':
                            del units[2]
                        elif violation == 'seven':
                            units.insert(2, deepcopy(units[2]))
                        elif violation == 'ordering':
                            units[2], units[3] = units[3], units[2]
                        elif violation == 'missing_position':
                            units[4 if domain == 'ai_tech' else 5]['role'] = 'example'
                        elif violation == 'empty_position':
                            units[4 if domain == 'ai_tech' else 5]['body'] = '...'
                        elif violation == 'long_title':
                            units[0]['title'] = 'a' * 81
                        elif violation == 'long_body':
                            units[2]['body'] = 'a' * 361
                        else:
                            response['public_text_claim_ids'] = []
                            for unit in units:
                                unit['claim_ids'] = []
                        canonical = json.loads(store.connection.execute('SELECT canonical_json FROM canonical_contents').fetchone()[0])
                        with self.assertRaises(ValueError):
                            _validated_body_checkpoint(response, canonical, platform='instagram', pipeline_id=domain)
                        worker = GeminiAdaptationWorker(store, FakeGeminiClient(response))
                        self.assertIsNone(worker.run_once())
                        self.assertEqual(store.connection.execute('SELECT status FROM adaptation_runs').fetchone()[0], 'failed')
                        self.assertIsNone(VisualPlanner(store).run_once())
                        image_client = FakeImageClient()
                        self.assertIsNone(DispatchVisualRenderer(store, Path(fixture.temporary.name)/'assets', image_client=image_client).run_once())
                        self.assertEqual(image_client.calls, [])
                        for table in ('content_packages', 'render_runs', 'review_requests'):
                            self.assertEqual(store.connection.execute(f'SELECT COUNT(*) FROM {table}').fetchone()[0], 0)

    def test_active_english_review_rejects_expression_copy_before_rendering(self):
        fixture = self.fixture()
        with WorkflowStore(fixture.path) as store:
            prepare_domain(store, fixture, 'english')
            response = domain_response(fixture, 'english')
            response['visual_units'][0]['title'] = 'This expression title is too long'
            canonical = json.loads(store.connection.execute(
                'SELECT canonical_json FROM canonical_contents'
            ).fetchone()[0])
            with self.assertRaises(ValueError):
                _validated_body_checkpoint(
                    response, canonical, platform='instagram', pipeline_id='english',
                    strict_english_capacity=True,
                )
            client = FakeGeminiClient(response)
            self.assertIsNone(GeminiAdaptationWorker(
                store, client, strict_english_capacity=True
            ).run_once())
            self.assertEqual(client.calls[0]['temperature'], 0.3)
            self.assertEqual(store.connection.execute(
                'SELECT status FROM adaptation_runs'
            ).fetchone()[0], 'failed')
            self.assertEqual(store.connection.execute(
                'SELECT COUNT(*) FROM content_packages'
            ).fetchone()[0], 0)

    def test_unsupported_domain_archetypes_block_without_html(self):
        for domain in DOMAINS:
            with self.subTest(domain=domain):
                fixture = self.fixture()
                with WorkflowStore(fixture.path) as store:
                    prepare_domain(store, fixture, domain)
                    response = domain_response(fixture, domain)
                    self.assertIsNotNone(GeminiAdaptationWorker(store, FakeGeminiClient(response)).run_once())
                    client = FakeImageClient()
                    root = Path(fixture.temporary.name)/'assets'
                    renderer = DispatchVisualRenderer(store, root, image_client=client)
                    with patch('workflow.gemini_image_renderer.supports_image_rendering', return_value=False):
                        self.assertIsNone(renderer.run_once())
                    self.assertEqual(client.calls, [])
                    self.assertEqual(store.connection.execute('SELECT status FROM render_runs').fetchone()[0], 'blocked')
                    self.assertEqual(store.connection.execute('SELECT COUNT(*) FROM review_requests').fetchone()[0], 0)
                    self.assertFalse(root.exists())

    def test_new_domains_share_terminal_failure_and_atomic_commit_behavior(self):
        for domain in ('ai_tech', 'psychology'):
            for failure in ('provider', 'processing', 'overlay', 'commit'):
                with self.subTest(domain=domain, failure=failure):
                    fixture = self.fixture()
                    with WorkflowStore(fixture.path) as store:
                        prepare_domain(store, fixture, domain)
                        self.assertIsNotNone(GeminiAdaptationWorker(store, FakeGeminiClient(domain_response(fixture, domain))).run_once())
                        self.assertIsNone(VisualPlanner(store).run_once())
                        client = FakeImageClient(error=RuntimeError('provider failure')) if failure == 'provider' else FakeImageClient(data=b'bad') if failure == 'processing' else FakeImageClient()
                        root = Path(fixture.temporary.name)/'assets'
                        renderer = DispatchVisualRenderer(store, root, image_client=client)
                        if failure == 'commit':
                            store.connection.execute("CREATE TEMP TRIGGER fail_third_asset BEFORE INSERT ON render_assets WHEN NEW.ordinal=3 BEGIN SELECT RAISE(ABORT, 'fixture commit failure'); END")
                        from workflow.gemini_image_renderer import apply_overlays
                        def overlay(*args, **kwargs):
                            if failure == 'overlay' and args[1] == 3:
                                raise OSError('fixture write failure')
                            return apply_overlays(*args, **kwargs)
                        with patch('workflow.gemini_image_renderer.apply_overlays', side_effect=overlay):
                            self.assertIsNone(renderer.run_once())
                        self.assertIsNone(renderer.run_once())
                        self.assertEqual(len(client.calls), 1)
                        self.assertEqual(store.connection.execute('SELECT status FROM render_runs').fetchone()[0], 'failed')
                        for table in ('review_requests', 'render_assets'):
                            self.assertEqual(store.connection.execute(f'SELECT COUNT(*) FROM {table}').fetchone()[0], 0)
                        self.assertEqual(store.connection.execute("SELECT COUNT(*) FROM model_invocations WHERE phase='image_rendering'").fetchone()[0], 1)
                        self.assertEqual(list(root.glob('*.tmp')), [])

    def test_new_domain_lost_image_calls_are_not_reclaimed(self):
        for domain in ('ai_tech', 'psychology'):
            fixture = self.fixture()
            with WorkflowStore(fixture.path) as store:
                prepare_domain(store, fixture, domain)
                self.assertIsNotNone(GeminiAdaptationWorker(store, FakeGeminiClient(domain_response(fixture, domain))).run_once())
                self.assertIsNone(VisualPlanner(store).run_once())
                run = store.claim('render_runs', 'render_run_id', 'interrupted')
                store.begin_model_invocation(phase='image_rendering', table='render_runs', key='render_run_id', row=run,
                    request_version='test', prompt_version='test', schema_version='test', request_value={}, model_id='fake')
                store.connection.execute("UPDATE render_runs SET lease_expires_at='2000-01-01T00:00:00'")
                store.connection.commit()
                client = FakeImageClient()
                renderer = DispatchVisualRenderer(store, Path(fixture.temporary.name)/'assets', image_client=client)
                self.assertIsNone(renderer.run_once())
                self.assertEqual(client.calls, [])
                self.assertEqual(store.connection.execute('SELECT status FROM render_runs').fetchone()[0], 'failed')
                self.assertEqual(store.connection.execute('SELECT COUNT(*) FROM review_requests').fetchone()[0], 0)

    def test_domain_compatibility_and_planning_are_explicit(self):
        for domain in DOMAINS:
            package = {'platform': 'instagram', 'visual_units': domain_response(fixtures.GeminiWorkflowTests(), domain)['visual_units']}
            for other_domain, archetype in DOMAIN_ARCHETYPES.items():
                self.assertEqual(supports_image_rendering(package, {'archetype_id': archetype}, pipeline_id=domain), domain == other_domain)
                if domain != other_domain:
                    with self.assertRaises(ValueError):
                        build_storyboard_prompt(package, {'archetype_id': archetype}, pipeline_id=domain)
        for domain in DOMAINS:
            roles = [unit['role'] for unit in domain_response(fixtures.GeminiWorkflowTests(), domain)['visual_units']]
            first = active_recipe(domain, roles)
            second = active_recipe(domain, roles)
            self.assertEqual(first, second)
            self.assertEqual(first['archetype_id'], DOMAIN_ARCHETYPES[domain])
            validate_recipe(first, production=False)
            validate_recipe_roles(first, roles)
            for other_domain, other_archetype in DOMAIN_ARCHETYPES.items():
                other_roles = EXPRESSION_ROLES if other_domain == 'english' else EXPLAINER_ROLES
                self.assertEqual(active_recipe(other_domain, list(other_roles))['archetype_id'], other_archetype)
