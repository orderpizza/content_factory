"""Offline characterization of the three-domain Instagram review baseline."""
from copy import deepcopy
from datetime import datetime, timezone
from hashlib import sha256
from pathlib import Path
from unittest.mock import patch
import json
import tempfile
import unittest

from database.current import initialize_database, connect, SchemaError
from detection.configuration import load_manifest, validate_manifest
from detection.adapters import collect_source
from detection.collector import DetectionCollector
from detection.scout import DetectionScout
from detection.models import CollectedItem, CollectionResult
from detection.store import DetectionStore
from workflow import WorkflowStore, GeminiDeterminationWorker, GeminiPipelineRunner, GeminiAdaptationWorker, VisualPlanner
from workflow.development import prepare_development_database
from workflow.gemini_image_renderer import DispatchVisualRenderer, build_storyboard_prompt
from dashboard.planning import render_threads
from dashboard.flow import render_job
from test_gemini_workflow import FakeGeminiClient
import test_gemini_workflow as fixtures
from test_gemini_image_renderer import FakeImageClient
from test_visual_system import EXPRESSION_UNITS
from test_semantic_detection import FakeEncoder

ROOT = Path(__file__).resolve().parents[1]
DOMAINS = ('english', 'ai_tech', 'psychology')
REASON = 'Gemini visual renderer not implemented for this domain.'


class BaselineTests(unittest.TestCase):
    def test_exact_catalog_and_no_incidental_database_upgrade(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = prepare_development_database(Path(tmp)/'baseline.db')
            with WorkflowStore(path) as store:
                catalog = store.catalog()
                self.assertEqual(tuple(c['pipeline_id'] for c in catalog), DOMAINS)
                self.assertEqual([[(o['platform'], o['account']) for o in c['outputs']] for c in catalog],
                                 [[('instagram', f'fixture_{domain}')] for domain in DOMAINS])
                with self.assertRaises(ValueError):
                    store.register_capability('english', enabled=True, generation_ready=True,
                                              outputs=[{'platform': 'x', 'account': 'fixture', 'content_format': 'removed'}])
            with connect(path) as connection:
                connection.execute('PRAGMA user_version=8')
            before = path.read_bytes()
            with self.assertRaises(SchemaError):
                initialize_database(path)
            self.assertEqual(path.read_bytes(), before)

    def test_current_rss_sources_collect_metadata_with_rss_and_atom_fixtures(self):
        manifest = load_manifest(ROOT/'config/releases/detection.json')
        sources = manifest['components']['detection']['sources']
        self.assertEqual({s['source_kind'] for s in sources},
                         {'publisher_feed_collector_v1', 'hacker_news_top_stories_v1', 'wikimedia_enwiki_pageviews_v1'})
        self.assertEqual({s['stable_id'] for s in sources}, {
            'openai_news_rss_v1', 'google_ai_rss_v1', 'nature_psychology_rss_v1',
            'sciencedaily_psychology_rss_v1', 'voa_grammar_rss_v1', 'voa_expressions_rss_v1',
            'cambridge_words_rss_v1', 'hacker_news_top_stories_v1', 'wikimedia_enwiki_daily_v1',
        })
        self.assertTrue(all(s['enabled'] and s['secret_ref'] is None for s in sources))
        self.assertEqual([s['independence_group'] for s in sources if s['stable_id'].startswith('voa_')], ['voa', 'voa'])
        payloads = {
            'rss': b'<rss><channel><item><title>A useful lesson</title><guid>lesson</guid><link>https://example.org/lesson</link><pubDate>Tue, 22 Sep 2026 12:00:00 +0200</pubDate><description>Not copied</description></item></channel></rss>',
            'atom': b'<feed xmlns="http://www.w3.org/2005/Atom"><entry><title>A useful lesson</title><id>lesson</id><link rel="self" href="https://example.org/feed-entry"/><link rel="alternate" href="https://example.org/lesson"/><published>2026-09-22T12:00:00+02:00</published><content>Not copied</content></entry></feed>',
        }
        for source in sources:
            if source['source_kind'] != 'publisher_feed_collector_v1':
                continue
            for format, body in payloads.items():
                with self.subTest(source=source['stable_id'], format=format):
                    variant = deepcopy(manifest)
                    index = sources.index(source)
                    variant['components']['detection']['sources'][index]['delivery_format'] = format
                    validate_manifest(variant)
                    config = variant['components']['detection']['sources'][index]
                    row = {**config, 'config_json': json.dumps(config), 'collection_day': '2026-09-22'}
                    with patch('detection.adapters._bounded_get', return_value=(body, {}, source['endpoint_url'], [])):
                        result = collect_source(row)
                    self.assertTrue(result.complete)
                    self.assertEqual(len(result.items), 1)
                    self.assertEqual(result.items[0].canonical_url, 'https://example.org/lesson')
                    self.assertEqual(result.items[0].provider_time, '2026-09-22T10:00:00')
                    self.assertNotIn('Not copied', json.dumps(result.items[0].payload))

    def test_large_publisher_history_is_bounded_and_newest_first(self):
        manifest = load_manifest(ROOT/'config/releases/detection.json')
        source = next(s for s in manifest['components']['detection']['sources'] if s['stable_id']=='openai_news_rss_v1')
        entries = ''.join(f'<item><title>Lesson {n}</title><guid>{n}</guid><pubDate>2026-09-22T10:{n//60:02}:{n%60:02}+00:00</pubDate></item>' for n in range(105))
        row = {**source, 'config_json': json.dumps(source), 'collection_day': '2026-09-22'}
        with patch('detection.adapters._bounded_get', return_value=(f'<rss><channel>{entries}</channel></rss>'.encode(), {}, source['endpoint_url'], [])):
            result = collect_source(row)
        self.assertTrue(result.complete)
        self.assertEqual(len(result.items), 100)
        self.assertEqual([i.source_item_id for i in result.items], [str(n) for n in reversed(range(5,105))])
        self.assertEqual(result.events[0].disposition, 'excluded_out_of_scope')

    def test_both_origins_reach_each_domain_and_unsupported_rendering_stops_without_assets(self):
        for origin in ('human', 'trend'):
            for domain in DOMAINS:
                with self.subTest(origin=origin, domain=domain):
                    fixture = fixtures.GeminiWorkflowTests(); fixture.setUp()
                    try:
                        self._exercise_origin(fixture, origin, domain)
                    finally:
                        fixture.doCleanups()

    def _exercise_origin(self, fixture, origin, domain):
        with WorkflowStore(fixture.path) as store:
            fixture.register_catalog(store)
            if origin == 'human':
                fixture.create_determination_request(store)
            else:
                at = datetime(2026,9,22,8,tzinfo=timezone.utc)
                evidence = CollectionResult((CollectedItem('lesson','A practical learning lesson',100,rank=1,provider_time=at.isoformat()),),(),True,'a'*64,1)
                with DetectionStore(fixture.path) as detection:
                    with patch('detection.collector.collect_source', return_value=evidence):
                        DetectionCollector(detection).run_due(now=at,source_ids={'hacker_news_top_stories_v1','openai_news_rss_v1'})
                    scout = DetectionScout(detection, encoder=FakeEncoder())
                    evaluate = scout._evaluate
                    def eligible(*args):
                        result = evaluate(*args)
                        for candidate in result['candidates']:
                            candidate.update(eligible=True,eligibility_reason='fixture_handoff')
                        return result
                    with patch.object(scout, '_evaluate', side_effect=eligible):
                        scout.run(now=at)
                self.assertEqual(store.connection.execute('SELECT COUNT(*) FROM intake_requests').fetchone()[0], 0)
            request = store.connection.execute('SELECT input_snapshot_json FROM determination_requests').fetchone()
            catalog = json.loads(request[0])['catalog']
            self.assertIsNotNone(GeminiDeterminationWorker(store, FakeGeminiClient(fixture.decision(catalog, selected_pipeline=domain))).run_once())
            self.assertIsNotNone(GeminiPipelineRunner(store, FakeGeminiClient(fixture.canonical_response(domain))).run_once())
            response = fixture.adaptation_response('instagram', claim_id=f'{domain}.example.1')
            response['visual_units'] = deepcopy(EXPRESSION_UNITS)
            for unit in response['visual_units']:
                unit['claim_ids'] = [f'{domain}.example.1' if c == 'english.example.1' else c for c in unit['claim_ids']]
            response['visual_intent']['primary_structure'] = 'cards'
            if domain != 'english':
                # A valid request for required images must hit the capability stop,
                # not the inactive HTML planner's unsupported-image error.
                response['visual_intent']['image_need'] = 'required'
            self.assertIsNotNone(GeminiAdaptationWorker(store, FakeGeminiClient(response)).run_once())
            with patch("workflow.static_renderer.StaticVisualRenderer._render_assets", side_effect=AssertionError("HTML must remain inactive")):
                self._render_and_check(store, fixture, domain)

    def _render_and_check(self, store, fixture, domain):
        planner = VisualPlanner(store)
        plan = planner.run_once()
        client = FakeImageClient()
        artifact_root = Path(fixture.temporary.name)/'review-assets'
        renderer = DispatchVisualRenderer(store, artifact_root, image_client=client)
        review = renderer.run_once()
        html = render_threads(store.connection, interactive=True) + render_job(store.connection, 1)
        self.assertNotIn('Post now', html)
        if domain == 'english':
            self.assertIsNotNone(plan)
            self.assertIsNotNone(review, renderer.last_operation)
            self.assertEqual(len(client.calls), 1)
            self.assertEqual(store.connection.execute('SELECT COUNT(*) FROM render_assets').fetchone()[0], 6)
            self.assertEqual(html.count('<img '), 6)
        else:
            self.assertIsNone(plan)
            self.assertIsNone(review)
            row = store.connection.execute('SELECT status,failure_reason FROM visual_plan_runs').fetchone()
            self.assertEqual(tuple(row), ('blocked', REASON))
            self.assertIn(REASON, html)
            self.assertIn('Adaptation: succeeded', html)
            self.assertEqual(client.calls, [])
            self.assertFalse(artifact_root.exists())
            for table in ('visual_recipes', 'render_runs', 'render_assets', 'review_requests'):
                self.assertEqual(store.connection.execute(f'SELECT COUNT(*) FROM {table}').fetchone()[0], 0)
            self.assertIsNone(planner.run_once())
            self.assertEqual(store.connection.execute("SELECT COUNT(*) FROM model_invocations WHERE phase='image_rendering'").fetchone()[0], 0)
