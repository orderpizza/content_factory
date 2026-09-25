"""Offline regressions for authority, bounded content planning and execution traces."""
from copy import deepcopy
from hashlib import sha256
import json
import sqlite3
import unittest

from workflow.catalog import domain_context
from workflow.gemini_intake import _validate_intake_response, _intake_prompt
from workflow.gemini_generation import _generation_prompt, _validate_content, source_evidence
from workflow.gemini_determination import _determination_prompt, determination_schema, _validate_decision
from workflow.gemini_adaptation import _adaptation_prompt, _validate_package
from workflow.editorial_planning import fixture_plan, validate_plan, planning_prompt
from workflow.content_contract import resolve_content_contract, semantic_qa, english_positions
from workflow.storyboard_planner import make_plan, StoryboardPlanner
from workflow import WorkflowStore, GeminiIntakeWorker, GeminiAdaptationWorker
from workflow.model_trace import invocation_cost
import test_gemini_workflow as wf
from test_gemini_workflow import FakeGeminiClient, brief
from test_domain_boundaries import prepare_domain
import test_gemini_image_renderer as image_tests
from test_gemini_image_renderer import FakeImageClient
from workflow.gemini_image_renderer import DispatchVisualRenderer
from claim_fixtures import register_fixture_semantics


class PromptContractTests(unittest.TestCase):
    def canonical(self, count=4):
        c = wf.GeminiWorkflowTests.canonical_response('english')
        c['domain_payload']['usage_notes'] = c['domain_payload']['usage_notes'][:1 if count < 6 else 3]
        if count == 5:
            c['examples'].append('A second invented usage example.')
        return register_fixture_semantics(c)

    def response(self, c, count):
        response = wf.GeminiWorkflowTests.adaptation_response('instagram')
        response['visual_units'] = [response['visual_units'][i] for i in english_positions(count)]
        response['public_text_claim_ids'] = [claim['claim_id'] for claim in c['claims']]
        return response

    def test_sparse_intake_does_not_promote_invented_intent(self):
        value = brief('under the weather')
        value.update(coverage_kind='etymology and usage guide', editorial_goal='Explain origin theories',
                     desired_outcome='Know medieval history', audience='Linguistics enthusiasts',
                     constraints={'treatment': 'historical origins'})
        snapshot = {'conversation': {'messages': [{'author_kind': 'human', 'body': "English expression 'under the weather'"}]}}
        result, question = _validate_intake_response(value, snapshot)
        self.assertIsNone(question)
        self.assertTrue(all(result[k] is None for k in ('editorial_goal', 'audience', 'desired_outcome')))
        self.assertEqual(result['coverage_kind'], 'subject')
        self.assertEqual(result['constraints'], {})
        self.assertEqual(result['field_authority']['audience'], 'unknown')
        self.assertNotIn('DOMAIN_CATALOG', _intake_prompt(snapshot))

    def test_context_is_domain_scoped_and_catalog_driven(self):
        for domain in ('english', 'ai_tech', 'psychology'):
            request = {'pipeline_id': domain}
            for prompt in (_generation_prompt(request), _adaptation_prompt(request)):
                self.assertIn(domain_context(domain)['purpose'], prompt)
                for other in {'english', 'ai_tech', 'psychology'} - {domain}:
                    self.assertNotIn(domain_context(other)['purpose'], prompt)
                self.assertNotIn('local content factory', prompt)
        catalog = [{'pipeline_id': 'new_domain', 'enabled': False, 'generation_ready': False,
                    'remit': {'purpose': 'A configuration-supplied remit'}, 'outputs': []}]
        snapshot = dict(catalog=catalog, brief={}, source_context={})
        prompt = _determination_prompt(snapshot)
        self.assertIn('every domain in DOMAIN_CATALOG', prompt)
        self.assertNotIn('all three', prompt)
        schema = determination_schema(catalog)
        self.assertEqual(schema['properties']['routes']['minItems'], 1)
        result = dict(outcome='not_recommended', opportunity_value='None', rationale='Disabled', warnings=[],
                      routes=[dict(pipeline_id='new_domain', disposition='skipped', fit='Unavailable', reason='Disabled', outputs=[])])
        self.assertEqual(_validate_decision(result, catalog)['routes'][0]['pipeline_id'], 'new_domain')

    def test_topic_reference_does_not_establish_other_facts(self):
        c = self.canonical()
        c['claims'][0].update(text='This expression dates to 1600.', claim_kind='source_bound_fact', evidence_reference_ids=['message:1'])
        source = {'messages': [{'message_id': 1, 'body': 'Teach an English expression.'}], 'job_id': 8}
        self.assertEqual(set(source_evidence(source)), {'message:1'})
        with self.assertRaisesRegex(ValueError, 'literal excerpt'):
            _validate_content(c, 'english', {'message:1'}, source)
        c['claims'][0]['text'] = 'Teach an English expression.'
        _validate_content(c, 'english', {'message:1'}, source)

    def test_public_prose_cannot_bypass_claim_registry(self):
        for field in ('context', 'takeaway', 'hook'):
            c = self.canonical()
            c[field] = 'An unregistered factual assertion.'
            with self.assertRaisesRegex(ValueError, 'not registered'):
                _validate_content(c, 'english', set())
        c = self.canonical()
        c['domain_payload']['nuance'] = 'An unregistered nuance.'
        with self.assertRaisesRegex(ValueError, 'not registered'):
            _validate_content(c, 'english', set())
        c = self.canonical()
        c['claims'][0].update(claim_kind='model_general_knowledge', evidence_reference_ids=['message:1'])
        with self.assertRaisesRegex(ValueError, 'cannot cite'):
            _validate_content(c, 'english', {'message:1'})

    def test_history_penalty_changes_close_choice_but_relevance_can_win(self):
        snapshot = dict(domain='english', brief=brief(), allowed_evidence_reference_ids=[], history=[])
        first = fixture_plan(snapshot)
        snapshot['history'] = [{'angle_type': first['candidates'][0]['angle_type']}]
        repeated = fixture_plan(snapshot)
        self.assertEqual(repeated['selected_candidate_id'], '2')
        repeated['candidates'][0]['relevance_score'] = 4
        repeated['selected_candidate_id'] = '1'
        validate_plan(repeated, snapshot)
        self.assertIsNone(repeated['why_now'])

    def test_content_count_is_frozen_before_render_partitioning(self):
        for count in (4, 5, 6):
            c = self.canonical(count)
            contract = resolve_content_contract(c, 'expression_breakdown_v1')
            self.assertEqual(contract['minimum_units'], count)
            response = self.response(c, count)
            package = _validate_package(response, c, platform='instagram', account='fixture',
                content_format='instagram_static_carousel_v2', pipeline_id='english', archetype_id='expression_breakdown_v1')
            before = deepcopy(package)
            normal = make_plan(package['visual_units'], 'english')
            singles = make_plan(package['visual_units'], 'english', calibration_capacities=[1]*count)
            self.assertEqual(normal['total_slides'], singles['total_slides'])
            self.assertEqual(package, before)
            self.assertEqual(package['semantic_qa']['outcome'], 'passed')

    def test_hero_dialogue_chrome_and_polarity_fail_before_render(self):
        c = self.canonical()
        units = self.response(c, 4)['visual_units']
        contract = resolve_content_contract(c, 'expression_story_scene_v1')
        ids = [claim['claim_id'] for claim in c['claims']]
        for defect in ('hero', 'dialogue', 'chrome', 'contradiction'):
            altered = deepcopy(units)
            if defect == 'hero':
                altered[0]['title'] = 'A different expression'
            elif defect == 'dialogue':
                altered[2]['body'] = altered[2]['body'].replace('Jay:', 'Mia:')
            elif defect == 'chrome':
                altered[1]['title'] = 'What it means'
            else:
                c['claims'].append(dict(claim_id='polarity', text='People do learn together.', claim_kind='generated_example'))
                altered[0]['body'] = 'People do not learn together.'
                altered[0]['claim_ids'] = ['polarity']
            with self.subTest(defect=defect), self.assertRaises(ValueError):
                semantic_qa(altered, c, contract, public_claim_ids=ids)

    def test_execution_trace_is_captured_before_call_and_immutable(self):
        f = wf.GeminiWorkflowTests(); f.setUp(); self.addCleanup(f.doCleanups)
        with WorkflowStore(f.path) as store:
            f.register_catalog(store)
            store.create_human_idea('Teach break the ice.', command_id='trace')
            class InspectClient(FakeGeminiClient):
                def generate_json(self, prompt, schema, *, temperature):
                    row = store.connection.execute('SELECT * FROM model_invocations').fetchone()
                    assert row['prompt_text'] == prompt
                    assert row['prompt_sha256'] == sha256(prompt.encode()).hexdigest()
                    self.last_raw_response = json.dumps(self.response)
                    return super().generate_json(prompt, schema, temperature=temperature)
            self.assertIsNotNone(GeminiIntakeWorker(store, InspectClient(brief())).run_once())
            row = store.connection.execute('SELECT * FROM model_invocations').fetchone()
            self.assertEqual(json.loads(row['raw_response_text']), json.loads(row['response_json']))
            self.assertIn('provider_response_schema', json.loads(row['trace_json'])['generation_configuration'])
            with self.assertRaises(sqlite3.IntegrityError):
                store.connection.execute("UPDATE model_invocations SET prompt_text='forged'")
            self.assertIsNone(invocation_cost(store.connection, row['model_invocation_id'])['actual_micro_usd'])

    def test_dynamic_english_reaches_review_with_exact_frozen_text(self):
        for count in (4, 5):
            with self.subTest(count=count):
                f = wf.GeminiWorkflowTests(); f.setUp(); self.addCleanup(f.doCleanups)
                c = self.canonical(count)
                with WorkflowStore(f.path) as store:
                    prepare_domain(store, f, 'english', canonical_content=c)
                    response = self.response(c, count)
                    self.assertIsNotNone(GeminiAdaptationWorker(store, FakeGeminiClient(response)).run_once())
                    self.assertIsNotNone(StoryboardPlanner(store).run_once())
                    client = FakeImageClient()
                    renderer = DispatchVisualRenderer(store, f.path.parent/'images', image_client=client)
                    renderer.image_renderer.budget_policy = image_tests.ImageWorkflowTests.image_policy(self)
                    self.assertIsNotNone(renderer.run_once(), renderer.image_renderer.last_operation)
                    self.assertEqual(store.connection.execute('SELECT COUNT(*) FROM render_assets').fetchone()[0], count)
                    package = json.loads(store.connection.execute('SELECT package_json FROM content_packages').fetchone()[0])
                    self.assertEqual(package['visual_units'], response['visual_units'])
                    rows = store.connection.execute("SELECT * FROM model_invocations WHERE phase='image_rendering'").fetchall()
                    for row, call in zip(rows, client.calls):
                        self.assertEqual(row['prompt_text'], call)
                        cost = invocation_cost(store.connection, row['model_invocation_id'])
                        self.assertIsNotNone(cost['actual_minus_reservation_micro_usd'])
                        self.assertEqual(cost['model_invocation_id'], row['model_invocation_id'])
                        self.assertEqual(cost['attempt_ordinal'], row['attempt_ordinal'])
