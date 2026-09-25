"""Gemini-backed Idea Intake worker for the persisted workflow."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any
import json

from .model_trace import generate_json
from common.gemini import VertexGeminiClient, configured_model

from .store import WorkflowStore
from .workers import local_operation
from .planning_context import model_context


INTAKE_PROMPT_VERSION = "workflow_gemini_intake_prompt_v4"
INTAKE_SCHEMA_VERSION = "workflow_gemini_intake_result_v3"
BRIEF_FIELDS = (
    "editorial_goal",
    "topic",
    "coverage_kind",
    "canonical_target",
    "revision_scope",
    "audience",
    "desired_outcome",
    "constraints",
    "source_context",
    "open_questions",
)

INTAKE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "required": list(BRIEF_FIELDS),
    "additionalProperties": False,
    "properties": {
        "editorial_goal": {"anyOf": [{"type": "string"}, {"type": "null"}]},
        "topic": {"type": "string"},
        "coverage_kind": {"type": "string"},
        "canonical_target": {"type": "string"},
        "revision_scope": {"type": "string"},
        "audience": {"anyOf": [{"type": "string"}, {"type": "null"}]},
        "desired_outcome": {"anyOf": [{"type": "string"}, {"type": "null"}]},
        "constraints": {"type": "object"},
        "source_context": {"type": "string"},
        "open_questions": {"type": "array", "items": {"type": "string"}},
    },
}


class GeminiIntakeWorker:
    """Interpret a claimed conversation or trend without choosing a route."""

    def __init__(
        self,
        store: WorkflowStore,
        client: Any | None = None,
        *,
        instance_id: str = "intake-gemini",
    ):
        self.store = store
        maximum = None if store.model_budget_policy is None else store.model_budget_policy.phase_limits["intake"][1]
        self.client = client or VertexGeminiClient(
            max_output_tokens=maximum,
            thinking_level="LOW" if configured_model().startswith("gemini-3") else None,
        )
        self.instance_id = instance_id

    def run_once(self) -> int | None:
        request = self.store.claim(
            "intake_requests", "intake_request_id", self.instance_id
        )
        if request is None:
            return None
        return self._process(request)

    @local_operation("intake_requests", "intake_request_id")
    def _process(self, request: Any) -> int | None:
        snapshot = model_context(self._input_snapshot(request))
        invocation_id = self.store.begin_model_invocation(
            phase="intake",
            table="intake_requests",
            key="intake_request_id",
            row=request,
            request_version=str(request["context_version"]),
            prompt_version=INTAKE_PROMPT_VERSION,
            schema_version=INTAKE_SCHEMA_VERSION,
            request_value=snapshot,
            model_id=str(getattr(self.client, "model", "gemini")),
        )
        try:
            response = generate_json(self.store, invocation_id, self.client,
                _intake_prompt(snapshot), INTAKE_SCHEMA, temperature=0.2
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
            brief, clarification = _validate_intake_response(response, snapshot)
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
        if clarification is not None:
            self.store.clarify_intake(request, clarification)
            return None
        return self.store.complete_intake(
            request,
            brief,
            actor_message="Gemini Intake froze a route-neutral editorial brief.",
        )

    def _input_snapshot(self, request: Any) -> dict[str, Any]:
        context = json.loads(request["context_json"])
        if context.get("kind") == "human_conversation":
            source = self.store.intake_source_snapshot(request)
            previous = self.store.connection.execute(
                "SELECT brief_json FROM brief_revisions WHERE thread_id=? "
                "ORDER BY revision_number DESC LIMIT 1",
                (request["thread_id"],),
            ).fetchone()
            return {
                "kind": "human_conversation",
                "conversation": source,
                "previous_brief": None if previous is None else json.loads(previous["brief_json"]),
                "intake_context": context,
            }
        raise ValueError("Intake requires a human conversation context")


def _validate_intake_response(value: Any, snapshot=None) -> tuple[dict[str, Any], str | None]:
    if not isinstance(value, Mapping):
        raise ValueError("Gemini Intake response must be an object")
    questions = value.get("open_questions")
    if not isinstance(questions, list) or any(
        not isinstance(question, str) or not question.strip() for question in questions
    ):
        raise ValueError("open_questions must be a list of non-empty strings")
    if questions:
        return {}, questions[0].strip()

    missing = [field for field in BRIEF_FIELDS if field not in value]
    if missing:
        raise ValueError(f"Gemini Intake response is missing required fields: {', '.join(missing)}")
    if set(value) != set(BRIEF_FIELDS):
        raise ValueError("Intake returned unknown fields")
    for field in (
        "topic", "coverage_kind", "canonical_target", "revision_scope", "source_context",
    ):
        if not isinstance(value[field], str) or not value[field].strip():
            raise ValueError(f"{field} must be a non-empty string")
    if not isinstance(value["constraints"], Mapping):
        raise ValueError("constraints must be an object")
    brief = {field: value[field] for field in BRIEF_FIELDS}
    brief["constraints"] = dict(value["constraints"])
    brief["open_questions"] = []
    authority = {'topic': 'normalized_subject', 'canonical_target': 'normalized_subject',
                 'source_context': 'model_summary', 'constraints': 'human_explicit'}
    source = ''
    if snapshot is not None:
        source = ' '.join(m['body'] for m in snapshot['conversation'].get('messages', [])
                          if m.get('author_kind') == 'human').casefold()
    for field in ('editorial_goal', 'audience', 'desired_outcome'):
        item = brief[field]
        if item is not None and (not isinstance(item, str) or not item.strip()):
            raise ValueError(f'{field} must be null or nonempty text')
        # These fields preserve explicit requests, never model-authored strategy.
        if snapshot is not None and item is not None and item.casefold() not in source:
            item = None
        brief[field] = item
        authority[field] = 'unknown' if item is None else 'human_explicit'
    if snapshot is not None:
        previous = snapshot.get('previous_brief')
        brief['coverage_kind'] = previous['coverage_kind'] if previous else 'subject'
        authority['coverage_kind'] = 'preserved_identity' if previous else 'system_default'
        def explicit(value):
            if isinstance(value, str):
                return value.casefold() in source
            if isinstance(value, list):
                return all(explicit(v) for v in value)
            if isinstance(value, dict):
                return all(explicit(v) for v in value.values())
            return False
        from .human_constraints import extract_constraints, TYPED_KEYS, VERSION
        typed, provenance = extract_constraints(snapshot['conversation'].get('messages', []))
        brief['constraints'] = {k: v for k, v in brief['constraints'].items() if k not in TYPED_KEYS and explicit(v)}
        brief['constraints'].update(typed)
        brief['constraint_provenance'] = {'version': VERSION, 'events': provenance}
        from .human_constraints import editorial_scope
        requested, _ = editorial_scope({'topic': source})
        brief['requested_subject_domains'] = sorted(requested)
        # This invariant also catches accidental later normalizer changes.
        if any(brief['constraints'].get(k) != v for k, v in typed.items()):
            raise ValueError('recognized explicit human constraint disappeared')
    brief['field_authority'] = authority
    return brief, None


def _intake_prompt(snapshot: dict[str, Any]) -> str:
    from .prompt_policy import compose
    return compose("""Convert the supplied conversation into a structured description of
what the user actually requested. Do not choose a subject-area pipeline,
publication destination, teaching treatment or visual presentation; later stages do that.
Capture the subject in topic and canonical_target. coverage_kind is a structural
subject category, never an invented treatment such as etymology or usage guide.
Preserve previous coverage_kind/canonical_target on refinements.
For editorial_goal, audience and desired_outcome, copy explicit request wording
or return null. Do not infer a learner audience, historical-origin goal or strategy.
constraints contains explicit human restrictions only, copied in the human's exact wording.
The caller extracts typed slide counts, domain scope and output constraints directly
from human messages. Do not copy those typed fields. source_context summarizes
what was supplied, not facts inferred about the subject. Sparse ideas are valid.
Ask an open_question only when ambiguity prevents identifying the requested
subject or respecting a material constraint, not merely because intent is sparse.
Otherwise open_questions is empty. revision_scope describes the requested revision.
""", snapshot, label='SOURCE_CONTEXT')
