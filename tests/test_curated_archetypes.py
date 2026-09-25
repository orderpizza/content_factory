"""Nine curated templates, immutable pre-adaptation selection and exact prompt coverage."""
from claim_fixtures import register_fixture_semantics
from workflow.editorial_planning import EditorialPlanningWorker
from workflow.storyboard_planner import StoryboardPlanner, paginate

from copy import deepcopy
from dataclasses import asdict
from hashlib import sha256
from pathlib import Path
import json
import sqlite3
import unittest
from unittest.mock import patch

from workflow import WorkflowStore, VisualPlanner, GeminiAdaptationWorker, GeminiDeterminationWorker, GeminiPipelineRunner
from workflow.active_visual_profiles import (ARCHETYPES, ACCOUNT_PROFILES, DEFAULT_ARCHETYPE_BY_DOMAIN,
    active_recipe, validate_recipe, validate_archetype_units)
from workflow.archetype_selection import select_archetype
from workflow.gemini_adaptation import _validate_package, adaptation_schema
from workflow.gemini_prompt_compiler import (build_storyboard_prompt,
    EXPRESSION_BREAKDOWN_ACCEPTED_PROMPT_PREFIX_V1)
from workflow.visual_art_direction import EXPRESSION_BREAKDOWN_ACCEPTED_DESIGNER_BRIEF_V1
from test_domain_boundaries import prepare_domain, domain_response
import test_gemini_workflow as workflow_fixtures
from test_gemini_workflow import FakeGeminiClient
import test_gemini_image_renderer as image_fixtures
from test_gemini_image_renderer import FakeImageClient
from workflow.gemini_image_renderer import DispatchVisualRenderer


def canonical_fixture(id):
    a = ARCHETYPES[id]
    c = workflow_fixtures.GeminiWorkflowTests.canonical_response(a.domain)
    p = c['domain_payload']
    for key, value in p.items():
        p[key] = ['General bounded content.'] if isinstance(value, list) else 'General bounded content.'
    c['examples'] = ['An illustrative example.']
    c['key_points'] = ['A bounded explanation.', 'A qualified takeaway.']
    if id == 'expression_story_scene_v1':
        p.update(plain_meaning='Help people start a conversation.', usage_notes=['At a meeting with coworkers.'])
        c['examples'] = ['A: Shall we talk? B: Yes, please.']
    elif id == 'expression_cards_v1':
        p.update(plain_meaning='An abstract degree of certainty.', nuance='Distinguish probability from certainty.',
                 usage_notes=['A first use.', 'A second use.', 'A third use.'])
    elif id == 'ai_tech_product_ui_v1':
        p.update(product_or_feature='A software editor feature.', capabilities=['Draft code.', 'Explain code.'],
                 use_cases=['Help a developer draft code.'])
    elif id == 'ai_tech_system_diagram_v1':
        p.update(change_summary='How a retrieval pipeline sends input through components.')
        c['key_points'] = ['First retrieve documents.', 'Then pass input to the agent.', 'Return the output.']
    elif id == 'psychology_human_scenario_v1':
        p.update(observed_behavior='Colleagues hesitate in a conversation.', context='A social meeting.',
                 example='A colleague waits in a meeting.')
    elif id == 'psychology_concept_cards_v1':
        p.update(concept='Cognitive attribution bias.', possible_mechanism='Distinguish observation from interpretation.',
                 alternative_explanations=['One possibility.', 'Another possibility.', 'A third possibility.'])
    if a.domain == 'english':
        p['target'] = 'break the ice'
        p['usage_notes'] = (p['usage_notes'] * 3)[:3]
    return register_fixture_semantics(c)


def recipe_fixture(id, history=None):
    a = ARCHETYPES[id]
    selected, provenance = select_archetype(canonical_fixture(id), a.domain, history or [])
    assert selected == id, (id, selected)
    return active_recipe(a.domain, account='fixture', archetype_id=id, selection=provenance)


def prompt_fixture(id):
    a = ARCHETYPES[id]
    response = domain_response(workflow_fixtures.GeminiWorkflowTests(), a.domain)
    response['public_text_claim_ids'] = [c['claim_id'] for c in canonical_fixture(id)['claims']]
    response['visual_units'][3]['claim_ids'] = [f'{a.domain}.example.1']
    response['visual_cues'] = [{'slide': 4, 'subject_claim_id': f'{a.domain}.example.1',
                              'semantic_emphasis': 'situation', 'participants_count': 2}]
    # Frozen renderer fixture preserves accepted baseline copy independently of
    # newer adaptation title ownership and content-count planning.
    if a.domain == 'english':
        from visual_fixtures import EXPRESSION_UNITS
        response['visual_units'] = deepcopy(EXPRESSION_UNITS)
        response['visual_units'][3]['claim_ids'] = [f'{a.domain}.example.1']
    for u in response['visual_units']:
        if 'body_lines' in u: u['body'] = '\n'.join(u.pop('body_lines'))
    package = dict(platform='instagram', account='fixture', **response)
    return build_storyboard_prompt(package, recipe_fixture(id), pipeline_id=a.domain, board=paginate(package['visual_units'],a.domain)[0])



class CuratedContractTests(unittest.TestCase):
    def test_account_identities_contain_only_reusable_art_direction(self):
        fields = {'id', 'domain', 'personality', 'color_behavior', 'illustration_character',
                  'typography_character', 'whitespace', 'polish',
                  'general_positive_rules', 'general_negative_rules'}
        for domain, identity in ACCOUNT_PROFILES.items():
            with self.subTest(domain=domain):
                value = asdict(identity)
                self.assertEqual(set(value), fields)
                serialized = json.dumps(value, ensure_ascii=False).lower()
                for forbidden in ('accepted_brief', 'storyboard', '3×2', '5:4', 'six-slide',
                                  'panel ordering', 'left-to-right', 'top-to-bottom',
                                  'top 10%', 'bottom 14%', 'do not rewrite', 'slide_content'):
                    self.assertNotIn(forbidden, serialized)
        english = json.dumps(asdict(ACCOUNT_PROFILES['english'])).lower()
        for direction in ('friendly', 'premium', 'editorial', 'controlled', 'hierarchy',
                          'meaningful', 'breathing room', 'scrapbook', 'poster', 'worksheet'):
            self.assertIn(direction, english)

    def test_generic_prompts_have_one_geometry_and_clean_ordered_sections(self):
        for id, a in ARCHETYPES.items():
            if id == 'expression_breakdown_v1':
                continue
            with self.subTest(id=id):
                prompt = prompt_fixture(id)
                self.assertIn('3 columns and 2 rows', prompt)
                self.assertIn('No outer margins. No gutters.', prompt)
                self.assertIn(a.art_direction, prompt)
                self.assertIn(ACCOUNT_PROFILES[a.domain].personality, prompt)
                for internal in ('subject_claim_id', 'profile_fingerprint', 'title_words', 'body_words', id):
                    self.assertNotIn(internal, prompt)
                exact = json.loads(prompt.split('SLIDE_CONTENT\n')[1])
                self.assertEqual([u['slide'] for u in exact['slides']], list(range(1, 7)))
                self.assertEqual([u['panel'] for u in exact['slides']], list(range(1, 7)))
                self.assertEqual(prompt.count('top 10%'), 1)
                self.assertNotIn(EXPRESSION_BREAKDOWN_ACCEPTED_DESIGNER_BRIEF_V1, prompt)

    def test_accepted_baseline_compilation_is_independent_of_account_identity(self):
        expected = prompt_fixture('expression_breakdown_v1')
        # Only the compiler's account lookup is unavailable; recipe validation still runs.
        with patch('workflow.gemini_prompt_compiler.ACCOUNT_PROFILES', {}):
            actual = prompt_fixture('expression_breakdown_v1')
        self.assertEqual(actual, expected)
        self.assertTrue(actual.startswith(EXPRESSION_BREAKDOWN_ACCEPTED_PROMPT_PREFIX_V1 + '\nSEMANTIC_CUES'))
        self.assertNotIn('ACCOUNT_VISUAL_IDENTITY', actual)

    def test_exactly_three_closed_archetypes_per_account(self):
        self.assertEqual(len(ARCHETYPES), 9)
        self.assertEqual(len(ACCOUNT_PROFILES), 3)
        for domain, identity in ACCOUNT_PROFILES.items():
            items = [a for a in ARCHETYPES.values() if a.domain == domain]
            self.assertEqual(len(items), 3)
            for a in items:
                self.assertEqual(a.account_visual_profile_id, identity.id)
                self.assertEqual(a.version, 1)
                self.assertEqual([s.ordinal for s in a.slides], list(range(1, 7)))
                self.assertTrue(all(s.composition and s.visual_mode and s.body_words > 0 for s in a.slides))
                validate_recipe(recipe_fixture(a.archetype_id))

    def test_every_archetype_selected_from_canonical_and_fallback_stays_safe(self):
        for id, a in ARCHETYPES.items():
            with self.subTest(id=id):
                result = select_archetype(canonical_fixture(id), a.domain, [])
                self.assertEqual(result[0], id)
                self.assertEqual(result, select_archetype(canonical_fixture(id), a.domain, []))
        for domain, baseline in DEFAULT_ARCHETYPE_BY_DOMAIN.items():
            history = [{'visual_recipe_id': n, 'archetype_id': baseline} for n in range(8, 0, -1)]
            self.assertEqual(select_archetype({}, domain, history)[0], baseline)

    def test_close_fit_history_and_clearly_superior_fit(self):
        c = canonical_fixture('ai_tech_product_ui_v1')
        c['domain_payload']['use_cases'] = ['General use.']
        c['domain_payload']['change_summary'] = 'A process that first sends input then returns output.'
        first, selection = select_archetype(c, 'ai_tech', [])
        self.assertEqual(first, 'ai_tech_product_ui_v1')  # stable lexical tie break
        history = [{'visual_recipe_id': n, 'archetype_id': first} for n in range(8, 0, -1)]
        selected, evidence = select_archetype(c, 'ai_tech', history)
        self.assertEqual(selected, 'ai_tech_system_diagram_v1')
        self.assertEqual(selection['fit_score'], evidence['fit_score'])
        strong, evidence = select_archetype(canonical_fixture(first), 'ai_tech', history)
        self.assertEqual(strong, first)
        self.assertEqual(evidence['recent_use_penalty'], 1)

    def test_recipe_rejects_wrong_identity_versions_and_forged_selection(self):
        recipe = recipe_fixture('expression_story_scene_v1')
        changes = {'account_visual_profile_id': 'psychology_visual_identity_v1',
                   'archetype_version': True, 'prompt_compiler_version': 'unknown',
                   'renderer_contract_id': 'unknown', 'overlay_profile_id': 'unknown',
                   'profile_fingerprint': '0'*64, 'account': ''}
        for key, value in changes.items():
            with self.subTest(key=key), self.assertRaises(ValueError):
                validate_recipe({**recipe, key: value})
        with self.assertRaises(ValueError):
            validate_recipe({**recipe, 'theme_id': 'invented'})
        for key, value in [('fit_score', 99), ('recent_use_penalty', 8), ('reason_codes', ['invented']), ('strategy', 'random')]:
            with self.subTest(key=key), self.assertRaises(ValueError):
                validate_recipe({**recipe, 'selection': {**recipe['selection'], key: value}})
        with self.assertRaises(ValueError):
            active_recipe('psychology', archetype_id='expression_breakdown_v1')

    def test_adaptation_capacity_claims_and_closed_cues(self):
        id = 'expression_story_scene_v1'
        c = canonical_fixture(id)
        response = domain_response(workflow_fixtures.GeminiWorkflowTests(), 'english')
        response['public_text_claim_ids'] = [claim['claim_id'] for claim in c['claims']]
        def validate(value):
            return _validate_package(value, c, platform='instagram', account='fixture',
                content_format='instagram_static_carousel_v2', pipeline_id='english', archetype_id=id)
        self.assertEqual(validate(response)['archetype_id'], id)
        self.assertNotIn('visual_intent', adaptation_schema('instagram', 'instagram_static_carousel_v2')['properties'])
        for field in ('archetype_id', 'theme', 'prompt'):
            with self.assertRaises(ValueError):
                validate({**response, field: 'invented'})
        over = deepcopy(response)
        over['visual_units'][0]['body_lines'] = [' '.join(['word'] * 19)]
        with self.assertRaises(ValueError):
            validate(over)
        flat = [{**u, 'body': '\n'.join(u['body_lines'])} for u in over['visual_units']]
        validate_archetype_units(flat, 'expression_breakdown_v1')
        with self.assertRaises(ValueError):
            validate({**response, 'public_text_claim_ids': ['unknown']})
        cue = {'slide': 4, 'subject_claim_id': 'english.example.1', 'semantic_emphasis': 'situation', 'participants_count': 2}
        response['visual_units'][3]['claim_ids'] = ['english.example.1']
        validate({**response, 'visual_cues': [cue]})
        invalids = [{**cue, 'prompt': 'Use a blue theme'}, {**cue, 'subject_claim_id': 'unknown'},
                    {**cue, 'semantic_emphasis': 'blue'}, {**cue, 'slide': 0},
                    {**cue, 'participants_count': 5}, {**cue, 'slide': True}]
        for bad in invalids:
            with self.subTest(cue=bad), self.assertRaises(ValueError):
                validate({**response, 'visual_cues': [bad]})

    def test_nine_frozen_prompt_hashes_and_content(self):
        hashes = json.loads((Path(__file__).parent/'fixtures'/'curated_prompt_hashes.json').read_text())
        self.assertEqual(set(hashes), set(ARCHETYPES))
        for id, a in ARCHETYPES.items():
            with self.subTest(id=id):
                prompt = prompt_fixture(id)
                self.assertEqual(sha256(prompt.encode()).hexdigest(), hashes[id])
                essentials = ('3×2 storyboard', '5:4', 'Do not rewrite', id, 'subject_claim_id', 'participants_count') if id == 'expression_breakdown_v1' else ('3 columns and 2 rows', 'Provider board aspect ratio 5:4', 'Do not omit, summarize, expand', 'participants')
                for text in essentials + ('top 10%', 'bottom 14%'):
                    self.assertIn(text, prompt)
                content = json.loads(prompt.split('SLIDE_CONTENT\n')[1])
                response = domain_response(workflow_fixtures.GeminiWorkflowTests(), a.domain)
                self.assertEqual([s['body'] for s in content['slides']], ['\n'.join(s['body_lines']) for s in response['visual_units']])
                for slide in a.slides:
                    self.assertIn(slide.composition, prompt)
                for other in ARCHETYPES:
                    if other != id:
                        self.assertNotIn(other, prompt)
                if id != 'expression_breakdown_v1':
                    self.assertIn(ACCOUNT_PROFILES[a.domain].personality, prompt)
                    markers = ['ACCOUNT_VISUAL_IDENTITY', 'ART_DIRECTION', 'SEMANTIC_CUES', 'NEGATIVE_CONSTRAINTS', 'SLIDE_CONTENT']
                    self.assertEqual([prompt.index(s) for s in markers], sorted(prompt.index(s) for s in markers))


class CuratedWorkflowTests(unittest.TestCase):
    def fixture(self):
        f = workflow_fixtures.GeminiWorkflowTests()
        f.setUp()
        self.addCleanup(f.doCleanups)
        return f

    def test_all_nine_flow_through_preselection_adaptation_compiler_and_renderer(self):
        for id, a in ARCHETYPES.items():
            with self.subTest(id=id):
                f = self.fixture()
                with WorkflowStore(f.path) as store:
                    prepare_domain(store, f, a.domain, canonical_content=canonical_fixture(id))
                    recipe_row = store.connection.execute('SELECT * FROM visual_recipes').fetchone()
                    recipe = json.loads(recipe_row['recipe_json'])
                    self.assertEqual(recipe['archetype_id'], id)
                    self.assertEqual(store.connection.execute('SELECT COUNT(*) FROM content_packages').fetchone()[0], 0)
                    response = domain_response(f, a.domain)
                    response['public_text_claim_ids'] = [claim['claim_id'] for claim in canonical_fixture(id)['claims']]
                    client = FakeGeminiClient(response)
                    self.assertIsNotNone(GeminiAdaptationWorker(store, client).run_once())
                    request = json.loads(client.calls[0]['prompt'].split('<FROZEN_OUTPUT>\n')[1].split('\n</FROZEN_OUTPUT>')[0])
                    self.assertEqual(request['content_contract']['archetype_id'], id)
                    self.assertNotIn('selected_archetype', request)
                    self.assertNotIn('visual_recipe_hash', request)
                    image = FakeImageClient()
                    StoryboardPlanner(store).run_once()
                    renderer = DispatchVisualRenderer(store, Path(f.temporary.name)/'assets', image_client=image)
                    renderer.image_renderer.budget_policy = image_fixtures.ImageWorkflowTests.image_policy(self)
                    self.assertIsNotNone(renderer.run_once())
                    self.assertEqual(len(image.calls), 1)
                    package = json.loads(store.connection.execute('SELECT package_json FROM content_packages').fetchone()[0])
                    self.assertEqual(image.calls[0], build_storyboard_prompt(package, recipe, pipeline_id=a.domain, board=paginate(package['visual_units'],a.domain)[0]))
                    manifest = json.loads(store.connection.execute('SELECT manifest_json FROM render_runs').fetchone()[0])
                    for key in ('archetype_id', 'archetype_version', 'account_visual_profile_id', 'prompt_compiler_version', 'renderer_contract_id', 'overlay_profile_id', 'selection'):
                        self.assertEqual(manifest[key], recipe[key])
                    self.assertEqual(store.connection.execute('SELECT COUNT(*) FROM render_assets').fetchone()[0], 6)
                    self.assertEqual(store.connection.execute('PRAGMA foreign_key_check').fetchall(), [])
                    self.assertEqual(store.connection.execute("SELECT COUNT(*) FROM model_invocations WHERE phase='adaptation'").fetchone()[0], 1)

    def test_selection_history_is_destination_scoped_and_recipe_is_immutable(self):
        f = self.fixture()
        with WorkflowStore(f.path) as store:
            f.prepare_english_canonical(store, command_id='first')
            first = store.connection.execute('SELECT * FROM visual_recipes').fetchone()
            def plan_next(domain, target):
                f.create_determination_request(store, target=target, command_id=target)
                snapshot = store.connection.execute("SELECT input_snapshot_json FROM determination_requests WHERE status='pending'").fetchone()
                decision = f.decision(json.loads(snapshot[0])['catalog'], selected_pipeline=domain)
                self.assertIsNotNone(GeminiDeterminationWorker(store, FakeGeminiClient(decision)).run_once())
                EditorialPlanningWorker(store).run_once()
                self.assertIsNotNone(GeminiPipelineRunner(store, FakeGeminiClient(f.canonical_response(domain))).run_once())
                self.assertIsNotNone(VisualPlanner(store).run_once())
            plan_next('english', 'a second expression')
            second = store.connection.execute('SELECT recipe_json FROM visual_recipes ORDER BY visual_recipe_id DESC').fetchone()
            history = json.loads(second[0])['selection']['history']
            self.assertEqual(history, [{'visual_recipe_id': first['visual_recipe_id'], 'archetype_id': json.loads(first['recipe_json'])['archetype_id']}])
            self.assertEqual(json.loads(second[0])['selection']['recent_use_penalty'], .25)
            with self.assertRaises(sqlite3.IntegrityError):
                store.connection.execute("UPDATE visual_recipes SET recipe_json='{}'")
            store.connection.rollback()
            recipes = store.connection.execute('SELECT visual_recipe_id,output_request_id FROM visual_recipes ORDER BY visual_recipe_id').fetchall()
            with self.assertRaises(sqlite3.IntegrityError):
                store.connection.execute("INSERT INTO adaptation_runs(output_request_id,visual_recipe_id,run_number,status,attempt_limit,created_at) VALUES (?,?,2,'pending',2,'2026-09-23T00:00:00')", (recipes[0]['output_request_id'], recipes[1]['visual_recipe_id']))
            store.connection.rollback()
            model = FakeGeminiClient(f.adaptation_response('instagram'))
            package_id = GeminiAdaptationWorker(store, model).run_once()
            self.assertIsNotNone(package_id)
            with self.assertRaises(sqlite3.IntegrityError):
                store.connection.execute("INSERT INTO render_runs(content_package_id,visual_recipe_id,run_number,status,attempt_limit,created_at) VALUES (?,?,2,'pending',2,'2026-09-23T00:00:00')", (package_id, recipes[1]['visual_recipe_id']))
            store.connection.rollback()
            with self.assertRaises(sqlite3.IntegrityError):
                store.connection.execute("UPDATE content_packages SET visual_recipe_id=? WHERE content_package_id=?", (recipes[1]['visual_recipe_id'], package_id))
            store.connection.rollback()
            plan_next('ai_tech', 'an assistant feature')
            other = json.loads(store.connection.execute('SELECT recipe_json FROM visual_recipes ORDER BY visual_recipe_id DESC').fetchone()[0])
            self.assertEqual(other['selection']['history'], [])
            self.assertNotEqual(other['account'], json.loads(second[0])['account'])

    def test_planning_rolls_back_handoff_and_stale_claim_cannot_persist(self):
        f = self.fixture()
        with WorkflowStore(f.path) as store:
            # Stop between canonical and planning to inspect the real worker gate.
            with patch.object(VisualPlanner, 'run_once', return_value=1):
                f.prepare_english_canonical(store)
            self.assertEqual(store.connection.execute('SELECT COUNT(*) FROM adaptation_runs').fetchone()[0], 0)
            model = FakeGeminiClient(f.adaptation_response('instagram'))
            self.assertIsNone(GeminiAdaptationWorker(store, model).run_once())
            self.assertEqual(model.calls, [])
            run = store.claim('visual_plan_runs', 'visual_plan_run_id', 'planner')
            store.connection.execute("CREATE TEMP TRIGGER stop_adaptation BEFORE INSERT ON adaptation_runs BEGIN SELECT RAISE(ABORT,'fixture failure'); END")
            with self.assertRaises(sqlite3.IntegrityError):
                store.create_visual_recipe(run)
            self.assertEqual(store.connection.execute('SELECT COUNT(*) FROM visual_recipes').fetchone()[0], 0)
            store.connection.execute('DROP TRIGGER stop_adaptation')
            store.connection.execute("UPDATE visual_plan_runs SET lease_expires_at='2000-01-01T00:00:00'")
            store.connection.commit()
            with self.assertRaises(RuntimeError):
                store.create_visual_recipe(run)
            self.assertEqual(store.connection.execute('SELECT COUNT(*) FROM visual_recipes').fetchone()[0], 0)

    def test_old_schema_is_refused_without_rewriting_existing_data(self):
        from database.current import initialize_database, connect, SchemaError
        f = self.fixture()
        c = connect(f.path)
        c.execute('PRAGMA user_version=9')
        c.commit()
        before = c.execute('SELECT * FROM schema_migrations').fetchall()
        with self.assertRaises(SchemaError):
            initialize_database(f.path)
        with self.assertRaises(SchemaError):
            WorkflowStore(f.path)
        self.assertEqual(c.execute('PRAGMA user_version').fetchone()[0], 9)
        self.assertEqual(c.execute('SELECT * FROM schema_migrations').fetchall(), before)
        c.close()
