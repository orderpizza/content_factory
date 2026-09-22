"""Domain boundaries; offline tests use temporary databases and fake providers."""

from common.timestamps import serialize_timestamp
from copy import deepcopy
from dashboard.flow import render_job
from dashboard.planning import render_threads
from datetime import datetime, timezone
from detection.collector import DetectionCollector
from detection.models import CollectedItem, CollectionResult
from detection.scout import DetectionScout
from detection.store import DetectionStore
from pathlib import Path
from test_gemini_image_renderer import FakeImageClient
from test_gemini_workflow import FakeGeminiClient
from test_semantic_detection import FakeEncoder
from test_visual_library import EXPRESSION_UNITS
from unittest.mock import patch
from workflow import GeminiAdaptationWorker, GeminiDeterminationWorker, GeminiPipelineRunner, VisualPlanner, WorkflowStore
from workflow.gemini_image_renderer import DispatchVisualRenderer
import json
import test_gemini_workflow as fixtures
import unittest


ROOT = Path(__file__).resolve().parents[1]


DOMAINS = ('english', 'ai_tech', 'psychology')


REASON = 'Gemini visual renderer not implemented for this domain.'


class DomainBoundaryTests(unittest.TestCase):


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
                evidence = CollectionResult((CollectedItem('lesson','A practical learning lesson',100,rank=1,provider_time=serialize_timestamp(at)),),(),True,'a'*64,1)
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
