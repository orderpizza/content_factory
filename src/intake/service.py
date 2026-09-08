"""Turn persisted trend or human context into immutable route-neutral briefs."""

import json
from dataclasses import dataclass
from typing import Protocol

from common.gemini import VertexGeminiClient, estimated_cost_usd
from common.models import utc_now
from database.sqlite import Database


@dataclass(frozen=True)
class IntakeResult:
    brief: dict
    coverage_identity: str


class IntakeEvaluator(Protocol):
    def evaluate(self, snapshot: dict) -> IntakeResult:
        """Interpret frozen source context without choosing a pipeline or format."""


class DeterministicIntakeEvaluator:
    """Offline fixture evaluator used by tests; production uses GeminiIntakeEvaluator."""

    def evaluate(self, snapshot: dict) -> IntakeResult:
        candidate = snapshot.get("candidate", {})
        topic = candidate.get("topic") or snapshot.get("topic") or "untitled opportunity"
        brief = {
            "editorial_goal": f"Explain the opportunity around {topic}.",
            "topic": topic,
            "coverage_kind": "trend_topic",
            "canonical_target": topic,
            "audience": "general audience",
            "desired_outcome": "inform",
            "constraints": {},
            "source_context": f"Deterministically selected trend candidate: {topic}.",
            "open_questions": [],
        }
        return IntakeResult(brief, f"trend_topic:{topic.casefold()}")


class GeminiIntakeEvaluator:
    """Gemini-backed Intake interpreter with a closed, route-neutral schema."""

    def __init__(self, client: VertexGeminiClient | None = None):
        self.client = client or VertexGeminiClient()

    def evaluate(self, snapshot: dict) -> IntakeResult:
        data = self.client.generate_json(
            _intake_prompt(snapshot), _INTAKE_SCHEMA, temperature=0.2,
        )
        brief = {key: data[key] for key in _BRIEF_KEYS}
        if brief["open_questions"]:
            raise ValueError("Intake cannot create a Determination request while questions remain")
        return IntakeResult(brief, data["coverage_identity"])


class IdeaIntakeService:
    """Claims IntakeRequests and persists the immutable brief handoff."""

    def __init__(self, evaluator: IntakeEvaluator | None = None):
        self.evaluator = evaluator or DeterministicIntakeEvaluator()

    def consume_next_request(self, database: Database) -> int | None:
        pending = database.pending_intake_requests(limit=1)
        if not pending:
            return None
        request = pending[0]
        if not database.claim_intake_request(request["intake_request_id"], utc_now()):
            return None
        snapshot = json.loads(request["input_snapshot_json"])
        try:
            result = self.evaluator.evaluate(snapshot)
            determination_request_id = database.complete_intake_with_revision(
                request["intake_request_id"], result.brief, snapshot,
                result.coverage_identity, utc_now(),
            )
        except Exception as error:
            database.fail_intake_request(request["intake_request_id"], str(error), utc_now())
            raise
        client = getattr(self.evaluator, "client", None)
        usage = getattr(client, "last_usage", None)
        if usage is not None:
            database.record_api_usage(
                "idea_intake", request["intake_request_id"], usage.model,
                usage.input_tokens, usage.output_tokens, usage.total_tokens,
                estimated_cost_usd(usage), utc_now(),
            )
        return determination_request_id


_BRIEF_KEYS = (
    "editorial_goal", "topic", "coverage_kind", "canonical_target", "audience",
    "desired_outcome", "constraints", "source_context", "open_questions",
)

_INTAKE_SCHEMA = {
    "type": "object",
    "required": [*_BRIEF_KEYS, "coverage_identity"],
    "properties": {
        "editorial_goal": {"type": "string"}, "topic": {"type": "string"},
        "coverage_kind": {"type": "string"}, "canonical_target": {"type": "string"},
        "audience": {"type": "string"}, "desired_outcome": {"type": "string"},
        "constraints": {"type": "object"}, "source_context": {"type": "string"},
        "open_questions": {"type": "array", "items": {"type": "string"}},
        "coverage_identity": {"type": "string"},
    },
}


def _intake_prompt(snapshot: dict) -> str:
    return f"""You are Idea Intake for a content factory. Interpret the frozen source
context into a structured, route-neutral editorial brief. Do not select a pipeline,
platform, account, format, visual profile, or generate content. Use the supplied
evidence only as context. Return no open questions when the context is sufficient.

Frozen source context: {json.dumps(snapshot, ensure_ascii=False)}

Return only JSON matching the supplied schema."""
