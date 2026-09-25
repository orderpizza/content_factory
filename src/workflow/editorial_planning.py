"""Closed editorial strategy boundary; no research, rendering or platform choices."""
from __future__ import annotations

import json
from .model_trace import generate_json
from common.gemini import VertexGeminiClient, configured_model
from .store import canonical, digest, now
from .workers import local_operation
from .planning_context import model_context
from .gemini_generation import _source_reference_ids

SCHEMA_VERSION = 'editorial_plan_v2'
PLANNER_VERSION = 'editorial_planner_v2'
STRATEGIES = {
    'english': ('meaning_explanation', 'real_life_usage', 'contrast_misuse', 'scenario_teaching', 'common_misunderstanding', 'pragmatic_nuance'),
    'ai_tech': ('what_changed', 'why_it_matters', 'how_it_works', 'practical_use', 'limitations', 'comparison', 'misconception'),
    'psychology': ('observed_pattern', 'concept_explanation', 'possible_mechanism', 'everyday_scenario', 'alternative_explanation', 'practical_implication', 'misconception'),
}
QUALIFICATIONS = {
    'english': ['no_invented_etymology', 'no_unsupported_cultural_claims', 'usage_context'],
    'ai_tech': ['source_backed_claims', 'dated_context', 'availability_scope', 'limitations', 'provider_claim_distinction'],
    'psychology': ['observation_vs_inference', 'alternative_explanations', 'uncertainty', 'non_diagnostic'],
}
DIMENSIONS = ('domain_fit', 'audience_usefulness', 'evidence_strength', 'timeliness', 'novelty', 'explanatory_potential')


def string():
    return {'type': 'string', 'minLength': 1, 'maxLength': 800}


def strings(minimum=0, maximum=8):
    return {'type': 'array', 'items': string(), 'minItems': minimum, 'maxItems': maximum}


def obj(properties):
    return {'type': 'object', 'properties': properties, 'required': list(properties), 'additionalProperties': False}


CANDIDATE_SCHEMA = obj({
    'candidate_id': string(), 'angle': string(),
    'angle_type': {'type': 'string', 'enum': sorted({s for v in STRATEGIES.values() for s in v})},
    'reader_promise': string(), 'relevance': string(),
    'relevance_score': {'type': 'integer', 'minimum': 0, 'maximum': 4},
    'evidence_score': {'type': 'integer', 'minimum': 0, 'maximum': 4}, 'must_cover_points': strings(1),
    'evidence_reference_ids': strings(0, 12), 'evidence_requirements': strings(0),
    'qualification_requirements': strings(1, 12),
})
PLAN_SCHEMA = obj({
    'domain': {'type': 'string', 'enum': list(STRATEGIES)},
    'lane': {'type': 'string', 'enum': ['trend', 'evergreen', 'series', 'experiment']},
    'audience_intent': string(), 'why_now': {'anyOf': [string(), {'type': 'null'}]},
    'candidates': {'type': 'array', 'minItems': 2, 'maxItems': 4, 'items': CANDIDATE_SCHEMA},
    'selected_candidate_id': string(), 'selection_rationale': string(),
    'selection_dimensions': obj({d: string() for d in DIMENSIONS}),
    'series_key': {'anyOf': [string(), {'type': 'null'}]},
    'experiment_key': {'anyOf': [string(), {'type': 'null'}]},
    'experiment_intention': {'anyOf': [string(), {'type': 'null'}]},
})


def validate_shape(value, schema):
    """Validate exactly the small schema vocabulary emitted above, recursively."""
    if 'anyOf' in schema:
        for option in schema['anyOf']:
            try:
                validate_shape(value, option)
                return
            except ValueError:
                pass
        raise ValueError('invalid nullable editorial field')
    kind = schema['type']
    if kind == 'null':
        if value is not None:
            raise ValueError('expected null')
    elif kind == 'object':
        if not isinstance(value, dict) or set(value) != set(schema['properties']):
            raise ValueError('invalid closed editorial object')
        for key, child in schema['properties'].items():
            validate_shape(value[key], child)
    elif kind == 'array':
        if not isinstance(value, list) or not schema['minItems'] <= len(value) <= schema['maxItems']:
            raise ValueError('editorial list outside bounds')
        for child in value:
            validate_shape(child, schema['items'])
    elif kind == 'integer':
        if type(value) is not int or not schema['minimum'] <= value <= schema['maximum']:
            raise ValueError('editorial score outside bounds')
    elif kind == 'string':
        if not isinstance(value, str) or not value.strip() or len(value) > schema.get('maxLength', 800):
            raise ValueError('invalid editorial text')
        if 'enum' in schema and value not in schema['enum']:
            raise ValueError('unknown editorial enum')
    else:
        raise ValueError('unsupported schema type')


def validate_plan(value, snapshot):
    validate_shape(value, PLAN_SCHEMA)
    domain = snapshot['domain']
    if value['domain'] != domain or domain not in STRATEGIES:
        raise ValueError('editorial domain lineage mismatch')
    candidates = value['candidates']
    ids = [c['candidate_id'] for c in candidates]
    if len(set(ids)) != len(ids) or value['selected_candidate_id'] not in ids:
        raise ValueError('selection must identify exactly one unique candidate')
    if len({c['angle'].casefold().strip() for c in candidates}) != len(candidates):
        raise ValueError('duplicate candidate angles')
    for candidate in candidates:
        if candidate['angle_type'] not in STRATEGIES[domain]:
            raise ValueError('strategy outside domain remit')
        if not set(candidate['evidence_reference_ids']) <= set(snapshot['allowed_evidence_reference_ids']):
            raise ValueError('unknown evidence reference')
        if not set(QUALIFICATIONS[domain]) <= set(candidate['qualification_requirements']):
            raise ValueError('missing domain qualifications')
    if value['selected_candidate_id'] != select_candidate(candidates, snapshot.get('history', [])):
        raise ValueError('editorial selection does not respect bounded treatment recency scoring')
    if value['lane'] == 'trend' and value['why_now'] is None:
        raise ValueError('trend requires a dated why-now explanation')
    if value['lane'] != 'series' and value['series_key'] is not None:
        raise ValueError('series metadata outside series lane')
    if value['lane'] != 'experiment' and any(value[k] is not None for k in ('experiment_key', 'experiment_intention')):
        raise ValueError('experiment metadata outside experiment lane')
    if value['lane'] == 'experiment' and not value['experiment_intention']:
        raise ValueError('experiment needs deliberate editorial intention')
    if value['lane'] == 'trend' and not snapshot['allowed_evidence_reference_ids']:
        raise ValueError('trend requires frozen evidence provenance')
    selected = next(c for c in candidates if c['candidate_id'] == value['selected_candidate_id'])
    if value['lane'] == 'trend' and not selected['evidence_reference_ids']:
        raise ValueError('trend selection must cite frozen evidence')


def freeze_input(connection, revision, request_snapshot, route, route_id, moment):
    """Snapshot the latest 12 committed plans in this domain, ordered by ID.

    One destination per domain means domain history is also destination history.
    Freeze at handoff, so retries cannot change the planner's inputs.
    """
    history = []
    for row in connection.execute(
        'SELECT editorial_plan_id,plan_json,input_fingerprint FROM editorial_plans WHERE pipeline_id=? ORDER BY editorial_plan_id DESC LIMIT 12',
        (route['pipeline_id'],),
    ):
        plan = json.loads(row['plan_json'])
        selected = next(c for c in plan['candidates'] if c['candidate_id'] == plan['selected_candidate_id'])
        history.append({'editorial_plan_id': row['editorial_plan_id'], 'input_fingerprint': row['input_fingerprint'],
                        'lane': plan['lane'], 'angle': selected['angle'], 'angle_type': selected['angle_type'],
                        'reader_promise': selected['reader_promise']})
    source = model_context({'source_context': request_snapshot['source_context']})['source_context']
    def has_detection(value):
        if not isinstance(value, dict):
            return False
        return (value.get('kind') == 'selected_trend' and bool(value.get('evidence'))) or any(has_detection(v) for v in value.values())

    return {'has_detection_evidence': bool(has_detection(source)), 'schema_version': 'editorial_input_v1', 'brief_revision_id': revision['revision_id'],
            'determination_route_id': route_id, 'domain': route['pipeline_id'],
            'brief': json.loads(revision['brief_json']), 'source_context': source,
            'source_fingerprint': digest(request_snapshot['source_context']),
            'outputs': route['outputs'], 'route_reason': route['reason'], 'as_of': moment,
            'allowed_evidence_reference_ids': _source_reference_ids(source),
            'history_policy': 'latest_12_domain_plans_at_handoff', 'history': history}


def fixture_plan(snapshot):
    """Explicit offline fixture policy, never a fallback for a failed paid plan."""
    domain = snapshot['domain']; brief = snapshot['brief']
    candidates = []
    for index, strategy in enumerate(STRATEGIES[domain][:2]):
        candidates.append({'candidate_id': str(index + 1), 'angle': f'{strategy}: {brief["editorial_goal"] or brief["topic"]}'[:800],
                           'angle_type': strategy, 'reader_promise': (brief['desired_outcome'] or 'Understand the supplied subject.')[:800],
                           'relevance_score': 3, 'evidence_score': 2,
                           'relevance': (brief['editorial_goal'] or brief['topic'])[:800], 'must_cover_points': [brief['topic'][:800]],
                           'evidence_reference_ids': [], 'evidence_requirements': ['Use only frozen evidence; label hypothetical examples.'],
                           'qualification_requirements': QUALIFICATIONS[domain]})
    return {'domain': domain, 'lane': 'evergreen', 'audience_intent': brief['audience'] or 'Unspecified; use accessible language.',
            'why_now': None,
            'candidates': candidates, 'selected_candidate_id': select_candidate(candidates, snapshot.get('history', [])),
            'selection_rationale': 'Offline fixture chooses the first supported teaching treatment.',
            'selection_dimensions': {d: 'Offline fixture; no model assessment.' for d in DIMENSIONS},
            'series_key': None, 'experiment_key': None, 'experiment_intention': None}


class EditorialPlanningWorker:
    def __init__(self, store, *, instance_id='editorial-placeholder'):
        self.store, self.instance_id = store, instance_id

    def run_once(self):
        run = self.store.claim('editorial_plan_runs', 'editorial_plan_run_id', self.instance_id)
        return None if run is None else self._process(run)

    @local_operation('editorial_plan_runs', 'editorial_plan_run_id')
    def _process(self, run):
        return self.store.complete_editorial_plan(run, fixture_plan(json.loads(run['input_snapshot_json'])), planner_version='editorial_fixture_v1')


class GeminiEditorialPlanningWorker(EditorialPlanningWorker):
    def __init__(self, store, client=None, *, instance_id='editorial-gemini'):
        super().__init__(store, instance_id=instance_id)
        maximum = None if store.model_budget_policy is None else store.model_budget_policy.phase_limits['editorial_planning'][1]
        self.client = client or VertexGeminiClient(max_output_tokens=maximum, thinking_level='LOW' if configured_model().startswith('gemini-3') else None)

    @local_operation('editorial_plan_runs', 'editorial_plan_run_id')
    def _process(self, run):
        with self.store.transaction():
            if self.store._cancel_if_closed('editorial_plan_runs', run, now()):
                return None
        snapshot = json.loads(run['input_snapshot_json'])
        invocation = self.store.begin_model_invocation(
            phase='editorial_planning', table='editorial_plan_runs', key='editorial_plan_run_id', row=run,
            request_version='editorial_input_v1', prompt_version=PLANNER_VERSION,
            schema_version=SCHEMA_VERSION, request_value=planning_input(snapshot), model_id=str(getattr(self.client, 'model', 'gemini')))
        response = None
        try:
            response = generate_json(self.store, invocation, self.client, planning_prompt(snapshot), PLAN_SCHEMA, temperature=0.2)
            validate_plan(response, snapshot)
        except Exception as error:
            self.store.finish_model_invocation(invocation, outcome='schema_failed' if response is not None else 'transport_failed',
                                               usage=getattr(self.client, 'last_usage', None), error=str(error), response_value=response)
            raise
        self.store.finish_model_invocation(invocation, outcome='succeeded', usage=getattr(self.client, 'last_usage', None), response_value=response)
        return self.store.complete_editorial_plan(run, response, planner_version=PLANNER_VERSION)


def treatment_penalty(strategy, history):
    return min(2, sum(2 if i < 3 else 1 for i, h in enumerate(history[:12]) if h['angle_type'] == strategy))


def select_candidate(candidates, history):
    # Relevance can outweigh repetition; stable tie-break preserves proposal order.
    return max(candidates, key=lambda c: 3*c['relevance_score'] + c['evidence_score']
               - treatment_penalty(c['angle_type'], history))['candidate_id']


def planning_input(snapshot):
    domain = snapshot['domain']
    return {**{k: snapshot[k] for k in ('domain', 'brief', 'source_context', 'as_of', 'allowed_evidence_reference_ids')},
            'recent_treatments': [{k: h[k] for k in ('angle_type', 'angle', 'reader_promise')} for h in snapshot['history']],
            'treatment_penalties': {s: treatment_penalty(s, snapshot['history']) for s in STRATEGIES[domain]},
            'allowed_strategies': STRATEGIES[domain], 'required_qualifications': QUALIFICATIONS[domain]}


def planning_prompt(snapshot):
    from .prompt_policy import compose
    return compose("""Choose an educational treatment in the already-selected subject area.
Propose 2–4 distinct strategies, not factual answers or final copy. must_cover_points
are obligations such as 'explain meaning' or 'demonstrate usage', never unsupported
answers. evidence_requirements are actual conditions for factual support (empty
when none are needed), not writing instructions. Sparse human topics do not mandate
origin stories or an inferred audience. Generation may use domain-permitted knowledge
with honest authority; supplied topic text is not evidence for that knowledge.

Supplied evidence identifiers must be copied exactly, never synthesized.
Score each candidate's relevance_score and evidence_score from 0 (none) to 4 (strong).
Select the maximum of 3*relevance_score + evidence_score - treatment_penalties[angle_type],
using candidate order to break ties. Explain novelty comparatively against
recent_treatments, naming repeated treatments and why relevance outweighs repetition
when needed. Do not force an irrelevant novel treatment. The validator enforces
this bounded recency policy. Required qualification codes apply to every candidate.
Evergreen why_now may be null; never manufacture urgency. Trend requires actual
dated evidence; series means intentional recurrence; experiment needs an explicit
editorial test intention. Do not research or choose a platform, visuals or copy.
""", planning_input(snapshot), domain=snapshot['domain'], label='FROZEN_INPUT')
