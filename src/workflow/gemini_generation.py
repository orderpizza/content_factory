"""Gemini-backed, domain-validated canonical generation for the workflow."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any
import json
import re

from .model_trace import generate_json
from common.gemini import VertexGeminiClient, configured_model

from .store import WORKFLOW_PIPELINES, WorkflowStore
from .workers import local_operation


GENERATION_PROMPT_VERSION = "workflow_gemini_generation_prompt_v7"
GENERATION_SCHEMA_VERSION = "canonical_content_v4"
CLAIM_KINDS = ("source_bound_fact", "qualified_inference", "generated_example", "model_general_knowledge", "editorial_framing")


def _string() -> dict[str, Any]:
    return {"type": "string", "minLength": 1}


def _string_list(*, minimum: int = 1, maximum: int = 12) -> dict[str, Any]:
    return {
        "type": "array",
        "minItems": minimum,
        "maxItems": maximum,
        "items": _string(),
    }


DOMAIN_FIELDS: dict[str, dict[str, str]] = {
    "english": {
        "target_kind": "string",
        "target": "string",
        "plain_meaning": "string",
        "nuance": "string",
        "register_and_region": "string",
        "usage_notes": "list",
        "avoid_misuse": "list",
    },
    "ai_tech": {
        "product_or_feature": "string",
        "change_summary": "string",
        "as_of_context": "string",
        "availability_scope": "string",
        "capabilities": "list",
        "use_cases": "list",
        "limitations": "list",
    },
    "psychology": {
        "observed_behavior": "string",
        "context": "string",
        "concept": "string",
        "possible_mechanism": "nullable_string",
        "alternative_explanations": "list",
        "example": "string",
        "practical_implications": "list",
        "qualification": "string",
    },
}


IDENTITY_FIELDS = {'english': {'target', 'target_kind'}, 'ai_tech': set(), 'psychology': set()}


def claim_reference():
    return {'type': 'object', 'required': ['claim_id'], 'additionalProperties': False,
            'properties': {'claim_id': _string()}}


def reference_list(minimum=1, maximum=12):
    return {'type': 'array', 'minItems': minimum, 'maxItems': maximum, 'items': claim_reference()}


def generation_schema(pipeline_id: str) -> dict[str, Any]:
    """Return the closed response schema for one frozen domain pipeline."""
    if pipeline_id not in DOMAIN_FIELDS:
        raise ValueError(f"unsupported workflow pipeline: {pipeline_id}")
    domain_fields = DOMAIN_FIELDS[pipeline_id]
    domain_properties = {
        field: (_string() if field in IDENTITY_FIELDS[pipeline_id] else
                claim_reference() if kind == 'string' else
                {'anyOf': [claim_reference(), {'type': 'null'}]} if kind == 'nullable_string' else
                reference_list()) for field, kind in domain_fields.items()
    }
    return {
        "type": "object",
        "required": [
            "hook", "context", "key_points", "examples", "takeaway", "claims",
            "domain_payload",
        ],
        "additionalProperties": False,
        "properties": {
            "hook": claim_reference(),
            "context": claim_reference(),
            "key_points": reference_list(2, 8),
            "examples": reference_list(0, 8),
            "takeaway": claim_reference(),
            "cta": {"anyOf": [claim_reference(), {"type": "null"}]},
            "claims": {
                "type": "array",
                "maxItems": 30,
                "items": {
                    "type": "object",
                    "required": [
                        "claim_id", "text", "claim_kind",
                        "evidence_reference_ids", "qualification",
                    ],
                    "additionalProperties": False,
                    "properties": {
                        "claim_id": {**_string(), "maxLength": 120, "pattern": r"^[A-Za-z0-9._:-]{1,120}$"},
                        "text": _string(),
                        "claim_kind": {"type": "string", "enum": list(CLAIM_KINDS)},
                        "evidence_reference_ids": _string_list(minimum=0, maximum=12),
                        "qualification": _string(),
                    },
                },
            },
            "domain_payload": {
                "type": "object",
                "required": list(domain_fields),
                "additionalProperties": False,
                "properties": domain_properties,
            },
        },
    }


class GeminiPipelineRunner:
    """Turn one persisted ContentJob into immutable canonical domain content."""

    def __init__(
        self,
        store: WorkflowStore,
        client: Any | None = None,
        *,
        instance_id: str = "pipeline-gemini",
    ):
        self.store = store
        maximum = None if store.model_budget_policy is None else store.model_budget_policy.phase_limits["generation"][1]
        self.client = client or VertexGeminiClient(
            max_output_tokens=maximum,
            thinking_level="LOW" if configured_model().startswith("gemini-3") else None,
        )
        self.instance_id = instance_id

    def run_once(self) -> int | None:
        run = self.store.claim(
            "generation_runs", "generation_run_id", self.instance_id, lease_seconds=600
        )
        if run is None:
            return None
        return self._process(run)

    @local_operation("generation_runs", "generation_run_id")
    def _process(self, run: Any) -> int | None:
        job = self.store.connection.execute(
            "SELECT recipe_json FROM content_jobs WHERE content_job_id=?",
            (run["content_job_id"],),
        ).fetchone()
        if job is None:
            raise ValueError("generation run references a missing ContentJob")
        recipe = json.loads(job["recipe_json"])
        pipeline_id = recipe.get("pipeline_id")
        if pipeline_id not in WORKFLOW_PIPELINES:
            raise ValueError("ContentJob has an unsupported pipeline")
        for field in ("brief", "angle", "source_context", "editorial_plan"):
            if not isinstance(recipe.get(field), Mapping):
                raise ValueError(f"ContentJob recipe is missing frozen {field}")

        reference_ids = _source_reference_ids(recipe["source_context"])
        request_value = {
            "pipeline_id": pipeline_id,
            "brief": {k: recipe["brief"][k] for k in ("topic", "constraints", "audience", "desired_outcome")},
            "selected_treatment": selected_treatment(recipe["editorial_plan"]),
            "source_context": recipe["source_context"],
            "allowed_source_reference_ids": reference_ids,
        }
        schema = generation_schema(pipeline_id)
        invocation_id = self.store.begin_model_invocation(
            phase="generation",
            table="generation_runs",
            key="generation_run_id",
            row=run,
            request_version="content_job_recipe_v3",
            prompt_version=GENERATION_PROMPT_VERSION,
            schema_version=GENERATION_SCHEMA_VERSION,
            request_value=request_value,
            model_id=str(getattr(self.client, "model", "gemini")),
        )
        try:
            response = generate_json(self.store, invocation_id, self.client,
                _generation_prompt(request_value), schema, temperature=0.35
            )
        except Exception as error:
            outcome = "parse_failed" if "json" in str(error).casefold() else "transport_failed"
            self.store.finish_model_invocation(
                invocation_id,
                outcome=outcome,
                usage=getattr(self.client, "last_usage", None),
                error=str(error),
            )
            raise

        try:
            content = _validate_content(response, pipeline_id, set(reference_ids), recipe["source_context"])
        except Exception as error:
            self.store.finish_model_invocation(
                invocation_id,
                outcome="schema_failed",
                usage=getattr(self.client, "last_usage", None),
                response_value=response,
                error=str(error),
            )
            raise

        self.store.finish_model_invocation(
            invocation_id,
            outcome="succeeded",
            usage=getattr(self.client, "last_usage", None),
            response_value=response,
        )
        canonical = {
            "schema_version": GENERATION_SCHEMA_VERSION,
            "pipeline_id": pipeline_id,
            **content,
        }
        requested = recipe['brief'].get('constraints', {}).get('content_slide_count')
        if requested is not None:
            if type(requested) is not int:
                raise ValueError('content_slide_count must be a typed integer')
            canonical['requested_slide_count'] = requested
        canonical['required_public_claim_ids'] = required_public_claims(content, pipeline_id)
        if pipeline_id == 'english':
            target = content['domain_payload']['target']
            references = [ref for ref, text in source_evidence(recipe['source_context']).items() if target in text]
            canonical['target_provenance'] = {
                'authority': 'human_explicit' if references and all(ref.startswith('message:') for ref in references) else 'supplied_subject' if references else 'normalized_subject',
                'evidence_reference_ids': references,
            }
        return self.store.create_canonical(run, canonical)


def _validate_content(
    value: Any, pipeline_id: str, allowed_reference_ids: set[str], source_context=None
) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise ValueError("Gemini generation response must be an object")
    required = {"hook", "context", "key_points", "examples", "takeaway", "claims", "domain_payload"}
    optional = {"cta"}
    if not required.issubset(value) or set(value) - required - optional:
        raise ValueError("canonical response has missing or unknown fields")
    normalized: dict[str, Any] = {}
    for field in ("hook", "context", "takeaway"):
        normalized[field] = _reference(value[field], field)
    cta = value.get("cta")
    if cta is not None:
        cta = _reference(cta, "cta")
    normalized["cta"] = cta
    normalized["key_points"] = _references(value["key_points"], "key_points", 2, 8)
    normalized["examples"] = _references(value["examples"], "examples", 0, 8)

    claims = value["claims"]
    if not isinstance(claims, list) or len(claims) > 30:
        raise ValueError("claims must be a list containing at most 30 entries")
    normalized_claims = []
    seen_claim_ids: set[str] = set()
    for claim in claims:
        if not isinstance(claim, Mapping) or set(claim) != {
            "claim_id", "text", "claim_kind", "evidence_reference_ids", "qualification"
        }:
            raise ValueError("each claim must have the complete closed claim shape")
        claim_id = _nonempty(claim["claim_id"], "claim_id")
        if not re.fullmatch(r"[A-Za-z0-9._:-]{1,120}", claim_id) or claim_id in seen_claim_ids:
            raise ValueError("claim IDs must be unique stable identifiers")
        seen_claim_ids.add(claim_id)
        claim_kind = claim["claim_kind"]
        if claim_kind not in CLAIM_KINDS:
            raise ValueError(f"invalid claim kind for {claim_id}")
        references = _validated_strings(
            claim["evidence_reference_ids"], "evidence_reference_ids", 0, 12
        )
        if len(references) != len(set(references)) or not set(references).issubset(allowed_reference_ids):
            raise ValueError(f"claim {claim_id} references evidence outside the frozen job")
        if claim_kind == "source_bound_fact" and not references:
            raise ValueError(f"source-bound claim {claim_id} requires frozen evidence")
        if claim_kind in {'model_general_knowledge', 'generated_example', 'editorial_framing'} and references:
            raise ValueError('model knowledge, framing and invented examples cannot cite source evidence')
        if claim_kind == 'model_general_knowledge' and pipeline_id != 'english':
            raise ValueError('model general knowledge is permitted only for standard English teaching')
        if claim_kind == 'source_bound_fact':
            evidence = source_evidence(source_context or {})
            text = _nonempty(claim['text'], 'claim text')
            if not all(ref in evidence for ref in references) or not any(text in evidence[ref] for ref in references):
                raise ValueError('source-bound text must be a literal excerpt of cited supplied evidence')
        normalized_claims.append({
            "claim_id": claim_id,
            "text": _nonempty(claim["text"], "claim text"),
            "claim_kind": claim_kind,
            "evidence_reference_ids": references,
            "qualification": _nonempty(claim["qualification"], "claim qualification"),
        })
    normalized["claims"] = normalized_claims

    payload = value["domain_payload"]
    field_kinds = DOMAIN_FIELDS[pipeline_id]
    if not isinstance(payload, Mapping) or set(payload) != set(field_kinds):
        raise ValueError(f"{pipeline_id} domain payload does not match its closed schema")
    normalized_payload = {}
    for field, kind in field_kinds.items():
        normalized_payload[field] = (
            _nonempty(payload[field], field) if field in IDENTITY_FIELDS[pipeline_id] else
            _reference(payload[field], field) if kind == 'string' else
            (None if payload[field] is None else _reference(payload[field], field)) if kind == 'nullable_string' else
            _references(payload[field], field, 1, 12)
        )
    normalized["domain_payload"] = normalized_payload
    validate_semantic_registry(normalized, pipeline_id)
    return normalized


def _nonempty(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field} must be a non-empty string")
    return value.strip()


def _validated_strings(value: Any, field: str, minimum: int, maximum: int) -> list[str]:
    if not isinstance(value, list) or not minimum <= len(value) <= maximum:
        raise ValueError(f"{field} must contain between {minimum} and {maximum} strings")
    return [_nonempty(item, field) for item in value]


def source_evidence(source_context):
    """Only actual source/message records establish evidence IDs, never arbitrary IDs."""
    result = {}
    def visit(value):
        if isinstance(value, Mapping):
            reference = value.get('reference_id')
            if reference is None and 'message_id' in value and value.get('author_kind', 'human') == 'human':
                reference = 'message:' + str(value['message_id'])
            if reference is None and 'observation_id' in value and 'source' in value:
                reference = 'observation:' + str(value['observation_id'])
            if reference is not None:
                texts = [value[k] for k in ('body', 'text', 'title', 'summary', 'content', 'detail')
                         if isinstance(value.get(k), str)]
                if texts:
                    result[str(reference)] = '\n'.join(texts)
            for child in value.values():
                visit(child)
        elif isinstance(value, list):
            for child in value:
                visit(child)
    visit(source_context)
    return result


def _source_reference_ids(source_context: Mapping[str, Any]) -> list[str]:
    return sorted(source_evidence(source_context))


def _reference(value, field):
    if not isinstance(value, Mapping) or set(value) != {'claim_id'}:
        raise ValueError(f'{field} must be a canonical claim reference')
    return {'claim_id': _nonempty(value['claim_id'], field)}


def _references(value, field, minimum, maximum):
    if not isinstance(value, list) or not minimum <= len(value) <= maximum:
        raise ValueError(f'{field} reference list outside bounds')
    return [_reference(v, field) for v in value]


def semantic_values(content):
    """Enumerate substantive semantic slots, excluding structural identity."""
    def leaves(value, path):
        if isinstance(value, dict) and set(value) == {'claim_id'}:
            yield path, value
        elif isinstance(value, dict):
            for key, child in value.items():
                if path == 'domain_payload' and key in {'target', 'target_kind'}:
                    continue
                yield from leaves(child, path + '.' + key)
        elif isinstance(value, list):
            for index, child in enumerate(value):
                yield from leaves(child, path + '.' + str(index))
        elif value is not None:
            yield path, value
    for field in ('hook', 'context', 'key_points', 'examples', 'takeaway', 'cta', 'domain_payload'):
        yield from leaves(content.get(field), field)


def validate_semantic_registry(content, pipeline_id=None):
    by_id = {claim['claim_id']: claim for claim in content['claims']}
    for path, ref in semantic_values(content):
        _reference(ref, path)
        if ref['claim_id'] not in by_id:
            raise ValueError(f'canonical semantic reference is not registered: {path}')
        kind = by_id[ref['claim_id']]['claim_kind']
        if kind == 'editorial_framing' and path not in {'hook', 'cta'}:
            raise ValueError('editorial framing is allowed only in hook and CTA')
        if path.startswith('examples.') and kind != 'generated_example':
            raise ValueError('teaching examples must identify invented example authority')


def resolved_content(content):
    """Read-only projection of v4 references for semantic selection and rendering."""
    if content.get('schema_version') == 'canonical_content_v3':
        raise ValueError('legacy canonical contract requires a fresh database')
    by_id = {c['claim_id']: c['text'] for c in content.get('claims', [])}
    def resolve(value):
        if isinstance(value, dict):
            if set(value) == {'claim_id'}:
                if value['claim_id'] not in by_id: raise ValueError('unknown canonical claim reference')
                return by_id[value['claim_id']]
            return {k: resolve(v) for k, v in value.items()}
        if isinstance(value, list): return [resolve(v) for v in value]
        return value
    return resolve(content)


def required_public_claims(content, domain):
    # Key points execute the selected treatment's must-cover obligations. Details
    # outside these fields support the lesson without forcing public repetition.
    refs = content['key_points'] + [content['takeaway']]
    payload = content['domain_payload']
    fields = {'english': ['plain_meaning', 'nuance'],
              'ai_tech': ['availability_scope', 'limitations'],
              'psychology': ['qualification', 'alternative_explanations']}[domain]
    for field in fields:
        value = payload[field]
        refs.extend(value if isinstance(value, list) else [value])
    return sorted({v['claim_id'] for v in refs})


def selected_treatment(plan):
    selected = next(c for c in plan['candidates'] if c['candidate_id'] == plan['selected_candidate_id'])
    return {k: selected[k] for k in ('angle', 'angle_type', 'reader_promise', 'must_cover_points',
                                    'evidence_requirements', 'qualification_requirements')}


def _generation_prompt(request_value: dict[str, Any]) -> str:
    from .prompt_policy import compose
    return compose("""Write reusable educational content for the supplied subject area.
selected_treatment fixes what to teach, not the factual answers. Execute its
reader promise and coverage obligations; do not invent evidence to fulfill them.
Do not choose a new strategy, publication destination, slide layout or hashtags.

The claims registry owns substantive semantics. Semantic fields contain objects
{"claim_id": "c1"} referencing that registry, not duplicated prose. Lists contain
reference objects. Only English target and target_kind are identity metadata and
remain ordinary strings; target_kind classifies the requested language item.
The target preserves the human's requested expression, not evidence for its meaning.
key_points are the minimal teaching claims that fulfill selected_treatment.must_cover_points;
they and takeaway must survive publicly, along with domain qualification/meaning.
Keep supporting details optional. Register at most 30 claims.
source_bound_fact is a literal excerpt from cited supplied evidence, not a
paraphrase or an inference. A source naming a topic cannot support other facts.
qualified_inference is an explicitly cautious interpretation, with its uncertainty
visible in text. generated_example is an invented teaching example. Only standard
English meaning/usage may use model_general_knowledge: unverified model knowledge,
no evidence references. editorial_framing is nonfactual invitation/question wording
for hook or CTA only; it cannot classify factual assertions as mere framing.
Model knowledge, framing and invented examples must have empty evidence references.
Every substantive uncertainty belongs in public text as well as qualification.
A reference proves membership, not entailment. Do not claim independent verification.
""", request_value, domain=request_value['pipeline_id'], label='FROZEN_JOB')
