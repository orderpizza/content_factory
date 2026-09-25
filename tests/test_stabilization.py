"""Human idea regression through the real persisted workers, with offline transports."""
from copy import deepcopy
import json
import unittest

from workflow import (WorkflowStore, GeminiIntakeWorker, GeminiDeterminationWorker,
                      GeminiPipelineRunner, GeminiAdaptationWorker, VisualPlanner)
from workflow.editorial_planning import (GeminiEditorialPlanningWorker, fixture_plan,
    finalize_proposal, PROPOSAL_SCHEMA, QUALIFICATIONS, validate_plan)
from workflow.gemini_generation import _validate_content, required_public_claims
from workflow.gemini_intake import _validate_intake_response
from workflow.gemini_determination import _validate_decision
from workflow.content_contract import resolve_content_contract, validate_content_contract, CapacityError
from workflow.human_constraints import extract_constraints
from workflow.storyboard_planner import StoryboardPlanner
from workflow.gemini_adaptation import _validate_package, _visual_unit
from common.gemini import retryable_provider_error
import test_gemini_workflow as fixtures
from test_gemini_workflow import FakeGeminiClient, brief

TARGET = 'Cat got your tongue?'


def content():
    texts = [
        ('hook', 'A question for a quiet moment', 'editorial_framing'),
        ('meaning', 'A teasing question asking why someone is silent.', 'model_general_knowledge'),
        ('tone', 'It can sound playful or impatient depending on tone.', 'model_general_knowledge'),
        ('register', 'This is informal conversational English.', 'model_general_knowledge'),
        ('usage', 'Consider your relationship with the listener.', 'model_general_knowledge'),
        ('avoid', 'Avoid it when someone seems uncomfortable.', 'model_general_knowledge'),
        ('example1', 'You usually have an opinion. Cat got your tongue?', 'generated_example'),
        ('example2', 'You went quiet, Sam. Cat got your tongue?', 'generated_example'),
        ('dialogue', 'A: Cat got your tongue? B: I am thinking. A: Take your time.', 'generated_example'),
        ('optional', 'This phrase is a question.', 'model_general_knowledge'),
    ]
    ref = lambda key: {'claim_id': key}
    return dict(hook=ref('hook'), context=ref('register'), key_points=[ref('meaning'), ref('tone')],
        examples=[ref('example1'), ref('example2')], takeaway=ref('usage'), cta=None,
        claims=[dict(claim_id=k,text=t,claim_kind=kind,evidence_reference_ids=[],
                     qualification='Invented example.' if kind=='generated_example' else 'Unverified standard English knowledge.' if kind=='model_general_knowledge' else 'Nonfactual invitation.') for k,t,kind in texts],
        domain_payload=dict(target=TARGET,target_kind='idiom',plain_meaning=ref('meaning'),nuance=ref('tone'),
            register_and_region=ref('register'),usage_notes=[ref('usage')],avoid_misuse=[ref('avoid')]))


def response(count):
    units = [
        dict(role='hook',title=TARGET,body_lines=['A teasing question about silence.'],claim_ids=['meaning']),
        dict(role='explanation',title='A teasing question',body_lines=['It asks why someone is silent.', 'Your tone can sound playful or impatient.'],claim_ids=['meaning','tone']),
        dict(role='explanation',title='Consider your listener',body_lines=['Think about your relationship.', 'Keep the tone friendly.', 'Avoid making discomfort worse.'],claim_ids=['usage','avoid']),
        dict(role='example',title='When someone goes quiet',body_lines=['You usually have an opinion. Cat got your tongue?', 'You went quiet, Sam. Cat got your tongue?'],claim_ids=['example1','example2']),
        dict(role='example',title='Give them time',body_lines=['A: Cat got your tongue?', 'B: I am thinking.', 'A: Take your time.'],claim_ids=['dialogue']),
        dict(role='takeaway',title='Keep the tone friendly',body_lines=['Consider your relationship with the listener.', 'A teasing question can sound impatient.'],claim_ids=['usage','tone']),
    ]
    from workflow.content_contract import english_positions
    return dict(visual_units=[units[i] for i in english_positions(count)],visual_cues=[],
        caption_summary='A teasing question asking why someone is silent. Tone matters.',cta=None,
        public_text_claim_ids=['hook','meaning','tone'],private_tags=['english','expressions'],
        hashtags=[],alt_text='An English lesson with examples and a conversation.')


class StabilizationTests(unittest.TestCase):
    def fixture(self):
        fixture = fixtures.GeminiWorkflowTests(); fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        return fixture

    def test_constraints_survive_omission_and_latest_message_wins(self):
        for phrase, count in [('4 slides',4),('four slides',4),('5 slides',5),('five slides',5),
                              ('6 slides',6),('six slides',6),('create a six-slide carousel',6)]:
            value=brief(TARGET); value['constraints']={}
            messages=[dict(message_id=1,author_kind='human',body=phrase+'; English only; do not discuss psychology')]
            result,_=_validate_intake_response(value,dict(conversation=dict(messages=messages)))
            self.assertEqual(result['constraints']['content_slide_count'], count)
            self.assertEqual(result['constraints']['included_domains'], ['english'])
            self.assertEqual(result['constraints']['excluded_domains'], ['psychology'])
            messages.append(dict(message_id=2,author_kind='human',body='Actually five slides; psychology only'))
            typed,_=extract_constraints(messages)
            self.assertEqual(typed['content_slide_count'],5)
            self.assertEqual(typed['included_domains'],['psychology'])
            self.assertNotIn('psychology', typed.get('excluded_domains', []))

    def test_domain_adjacency_uses_requested_subject(self):
        fixture=self.fixture()
        with WorkflowStore(fixture.path) as store:
            fixture.register_catalog(store)
            catalog=store.catalog()
            for topic in [f"English expression '{TARGET}'", "English idiom 'blow a fuse'"]:
                decision=fixture.decision(catalog)
                route=next(r for r in decision['routes'] if r['pipeline_id']=='psychology')
                route.update(disposition='selected',outputs=next(c for c in catalog if c['pipeline_id']=='psychology')['outputs'])
                normalized=_validate_decision(decision,catalog,dict(topic=topic))
                self.assertEqual([r['pipeline_id'] for r in normalized['routes'] if r['disposition']=='selected'],['english'])
            psych=fixture.decision(catalog,selected_pipeline='psychology')
            self.assertEqual(_validate_decision(psych,catalog,dict(topic='Why do people suddenly go silent when questioned?'))['outcome'],'accepted')

    def test_selection_policy_and_qualifications_are_deterministic(self):
        for domain in QUALIFICATIONS:
            snapshot=dict(domain=domain,brief=brief(),history=[dict(angle_type='meaning_explanation')],allowed_evidence_reference_ids=['message:1'])
            value=fixture_plan(snapshot)
            value['selected_candidate_id']='wrong'; value['candidates'][0]['evidence_score']=4
            for c in value['candidates']:
                c['qualification_requirements']=[];c['evidence_reference_ids']=['message:1']
            plan=finalize_proposal(value,snapshot)
            validate_plan(plan,snapshot)
            self.assertEqual(plan['selected_candidate_id'],'candidate:2' if domain=='english' else 'candidate:1')
            for c in plan['candidates']:
                self.assertEqual(c['qualification_requirements'],QUALIFICATIONS[domain])
                self.assertEqual(c['evidence_score'],0)

    def test_claim_references_and_optional_public_coverage(self):
        c=_validate_content(content(),'english',set())
        self.assertNotIn('idiom',[claim['text'] for claim in c['claims']])
        c['required_public_claim_ids']=required_public_claims(c,'english')
        package=_validate_package(response(5),c,platform='instagram',account='test',content_format='instagram_static_carousel_v2',archetype_id='expression_breakdown_v1')
        self.assertNotIn('optional',[m['claim_id'] for m in package['claim_mappings']])
        c['domain_payload']['nuance']={'claim_id':'missing'}
        with self.assertRaisesRegex(ValueError,'not registered'): _validate_content({k:v for k,v in c.items() if k!='required_public_claim_ids'},'english',set())

    def test_structured_lines_precise_limits_and_alternating_dialogue(self):
        c=content();c['requested_slide_count']=6
        contract=resolve_content_contract(c,'expression_breakdown_v1')
        units=[_visual_unit(u,{v['claim_id'] for v in c['claims']}) for u in response(6)['visual_units']]
        validate_content_contract(units,contract)
        self.assertEqual(len(units[3]['body_lines']),2)
        bad=deepcopy(units);bad[1]['body_lines']=[' '.join(['word']*50)];bad[1]['body']='\n'.join(bad[1]['body_lines'])
        with self.assertRaises(CapacityError) as error: validate_content_contract(bad,contract)
        self.assertEqual(error.exception.diagnostic,dict(slide=2,field='body_lines[0]',rule='max_words',actual=50,limit=35))
        bad=deepcopy(units);bad[3]['body_lines']=bad[3]['body_lines'][:1];bad[3]['body']='\n'.join(bad[3]['body_lines'])
        with self.assertRaises(CapacityError) as error: validate_content_contract(bad,contract)
        self.assertEqual(error.exception.diagnostic['rule'],'min_lines')
        bad=deepcopy(units);bad[4]['body_lines'][1]='A: I am thinking.';bad[4]['body']='\n'.join(bad[4]['body_lines'])
        with self.assertRaisesRegex(ValueError,'alternating'): validate_content_contract(bad,contract)

    def test_sparse_and_explicit_six_reach_render_eligibility(self):
        for explicit in (False,True):
            fixture=self.fixture()
            with WorkflowStore(fixture.path) as store:
                fixture.register_catalog(store)
                human=f"English expression '{TARGET}'"+(' Make it a six-slide lesson.' if explicit else '')
                store.create_human_idea(human,command_id='idea')
                intake=brief(TARGET);intake['constraints']={}
                self.assertIsNotNone(GeminiIntakeWorker(store,FakeGeminiClient(intake)).run_once())
                frozen=json.loads(store.connection.execute('SELECT brief_json FROM brief_revisions').fetchone()[0])
                self.assertIsNone(frozen['audience']);self.assertIsNone(frozen['desired_outcome'])
                snapshot=json.loads(store.connection.execute('SELECT input_snapshot_json FROM determination_requests').fetchone()[0])
                self.assertIsNotNone(GeminiDeterminationWorker(store,FakeGeminiClient(fixture.decision(snapshot['catalog']))).run_once())
                plan_input=json.loads(store.connection.execute('SELECT input_snapshot_json FROM editorial_plan_runs').fetchone()[0])
                proposal=fixture_plan(plan_input)
                proposal={k:v for k,v in proposal.items() if k in PROPOSAL_SCHEMA['properties']}
                proposal['candidates']=[{k:v for k,v in c.items() if k in PROPOSAL_SCHEMA['properties']['candidates']['items']['properties']} for c in proposal['candidates']]
                self.assertIsNotNone(GeminiEditorialPlanningWorker(store,FakeGeminiClient(proposal)).run_once())
                self.assertIsNotNone(GeminiPipelineRunner(store,FakeGeminiClient(content())).run_once())
                self.assertIsNotNone(VisualPlanner(store).run_once())
                self.assertIsNotNone(GeminiAdaptationWorker(store,FakeGeminiClient(response(6 if explicit else 5))).run_once())
                self.assertIsNotNone(StoryboardPlanner(store).run_once())
                self.assertEqual(store.connection.execute('SELECT status FROM render_runs').fetchone()[0],'pending')
                package=json.loads(store.connection.execute('SELECT package_json FROM content_packages').fetchone()[0])
                self.assertEqual(len(package['visual_units']),6 if explicit else 5)
                self.assertEqual(package['semantic_qa']['outcome'],'passed')
                self.assertEqual(store.connection.execute("SELECT COUNT(*) FROM content_jobs WHERE pipeline_id!='english'").fetchone()[0],0)

    def test_capacity_diagnostic_persists_and_missing_usage_is_not_free(self):
        from workflow import ModelBudgetPolicy
        from acceptance.adapters.pipeline import _ledger
        fixture=self.fixture()
        with WorkflowStore(fixture.path) as store:
            fixture.prepare_english_canonical(store)
            bad=fixture.adaptation_response('instagram')
            bad['visual_units'][1]['body_lines']=[' '.join(['word']*50)]
            self.assertIsNone(GeminiAdaptationWorker(store,FakeGeminiClient(bad)).run_once())
            error=json.loads(store.connection.execute("SELECT safe_error FROM model_invocations WHERE phase='adaptation'").fetchone()[0])
            self.assertEqual((error['slide'],error['field'],error['rule'],error['actual'],error['limit']),
                             (2,'body_lines[0]','max_words',50,35))
        fixture=self.fixture()
        policy=ModelBudgetPolicy.from_environment('fake-gemini', {
            'GEMINI_INPUT_COST_PER_MILLION_USD':'1', 'GEMINI_OUTPUT_COST_PER_MILLION_USD':'2',
            'GEMINI_DAILY_WARNING_USD':'5', 'GEMINI_DAILY_HARD_LIMIT_USD':'10', 'GEMINI_JOB_HARD_LIMIT_USD':'2'})
        class ProviderError(Exception): code=504
        class FailingClient(FakeGeminiClient):
            def generate_json(self,*a,**kw):
                self.last_usage=None
                raise ProviderError('deadline exceeded')
        with WorkflowStore(fixture.path,model_budget_policy=policy) as store:
            store.create_human_idea('An English expression',command_id='uncertain')
            GeminiIntakeWorker(store,FailingClient({})).run_once()
            reservation=store.connection.execute('SELECT * FROM gemini_budget_reservations').fetchone()
            self.assertEqual(reservation['status'],'uncertain')
            self.assertIsNone(reservation['settled_micro_usd'])
            self.assertEqual(_ledger(store,['intake'])[3],reservation['worst_case_micro_usd'])

    def test_transport_retries_are_bounded_and_semantic_failures_terminal(self):
        class ProviderError(Exception): code=504
        class FailingClient(FakeGeminiClient):
            def generate_json(self,*a,**kw):
                self.calls.append(1)
                raise ProviderError('deadline exceeded')
        fixture=self.fixture()
        with WorkflowStore(fixture.path) as store:
            store.create_human_idea('English expression test',command_id='retry')
            client=FailingClient({});worker=GeminiIntakeWorker(store,client)
            worker.run_once()
            row=store.connection.execute('SELECT * FROM intake_requests').fetchone()
            self.assertEqual(row['status'],'retry_wait')
            for _ in range(row['attempt_limit']-1):
                store.connection.execute('UPDATE intake_requests SET next_attempt_at=NULL');store.connection.commit()
                worker.run_once()
            self.assertEqual(store.connection.execute('SELECT status FROM intake_requests').fetchone()[0],'failed')
            self.assertEqual(len(client.calls),row['attempt_limit'])
            self.assertFalse(retryable_provider_error(ValueError('504')))
            self.assertFalse(retryable_provider_error(TimeoutError()))
            store.create_human_idea('another subject',command_id='schema')
            client=FakeGeminiClient({});worker=GeminiIntakeWorker(store,client);worker.run_once();worker.run_once()
            self.assertEqual(len(client.calls),1)
