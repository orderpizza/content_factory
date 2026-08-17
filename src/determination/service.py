"""Turn persisted determination handoffs into explicit production recipes."""

from dataclasses import dataclass
import json
from typing import Protocol

from common.gemini import VertexGeminiClient
from common.models import ContentJob, Trend, utc_now
from database.sqlite import Database


@dataclass(frozen=True)
class PipelineCapability:
    pipeline_id: str
    platform: str
    account: str
    content_format: str
    visual_profile_id: str
    description: str


POC_PIPELINE_CATALOG = (
    PipelineCapability("poc_pipeline", "bluesky", "default", "text_card", "poc_card", "A concise Bluesky post with a deterministic visual card."),
    PipelineCapability("o2_english_instagram", "instagram", "o2_english", "instagram_idiom_carousel", "o2_english_idiom_carousel_v1", "A fixed 5-8 slide Instagram idiom carousel for English learners."),
)


@dataclass(frozen=True)
class Determination:
    should_create: bool
    pipeline: PipelineCapability = POC_PIPELINE_CATALOG[0]
    angle: str = "Explain why this topic is gaining attention."
    audience: str = "general audience"
    objective: str = "inform"
    key_points: tuple[str, ...] = ()
    sources: tuple[str, ...] = ()
    priority: int = 0
    reasoning: str = ""


class CandidateEvaluator(Protocol):
    def evaluate(self, candidate: dict, evidence: list[dict], catalog: tuple[PipelineCapability, ...]) -> Determination:
        """Return the decision and high-level recipe for one trend candidate."""


class ThresholdCandidateEvaluator:
    """Offline fixture evaluator; production execution uses GeminiCandidateEvaluator."""

    def __init__(self, minimum_score: float):
        self.minimum_score = minimum_score

    def evaluate(self, candidate: dict, evidence: list[dict], catalog: tuple[PipelineCapability, ...]) -> Determination:
        score = float(candidate["score"])
        should_create = score >= self.minimum_score
        topic = candidate.get("topic", "trend")
        sources = tuple(item["url"] for item in evidence if item.get("url"))
        return Determination(
            should_create=should_create,
            pipeline=catalog[0],
            key_points=(topic, f"Detection score: {score:.2f}"),
            sources=sources,
            priority=max(0, min(100, round(score * 10))) if should_create else 0,
            reasoning=("Candidate meets the configured offline fixture threshold."
                       if should_create else "Candidate is below the configured offline fixture threshold."),
        )


class GeminiCandidateEvaluator:
    """Gemini selects only whether and how to consume a persisted candidate."""

    def __init__(self, client: VertexGeminiClient | None = None):
        self.client = client or VertexGeminiClient()

    def evaluate(self, candidate: dict, evidence: list[dict], catalog: tuple[PipelineCapability, ...]) -> Determination:
        capabilities = [capability.__dict__ for capability in catalog]
        data = self.client.generate_json(
            _determination_prompt(candidate, evidence, capabilities), _DETERMINATION_SCHEMA, temperature=0.2,
        )
        if not data["should_create"]:
            return Determination(should_create=False, reasoning=data["reasoning"])
        selected = next((item for item in catalog if item.pipeline_id == data["pipeline_id"]), None)
        if selected is None:
            raise ValueError("Gemini selected a pipeline outside the capability catalog")
        if data["visual_profile_id"] != selected.visual_profile_id:
            raise ValueError("Gemini selected a visual profile unavailable to the selected pipeline")
        return Determination(
            should_create=True,
            pipeline=selected,
            angle=data["angle"], audience=data["audience"], objective=data["objective"],
            key_points=tuple(data["key_points"]),
            sources=tuple(item["url"] for item in evidence if item.get("url")),
            priority=max(0, min(100, int(data["priority"]))), reasoning=data["reasoning"],
        )


class DeterminationService:
    """Persisted-handoff determination with a deterministic placeholder policy.

    Gemini will replace ``evaluate_candidate`` once credentials are configured.
    This service owns only the consume/reject decision and recipe; it never
    invokes a content pipeline.
    """

    def __init__(self, minimum_score: float = 0.25, catalog: tuple[PipelineCapability, ...] = POC_PIPELINE_CATALOG,
                 evaluator: CandidateEvaluator | None = None):
        self.minimum_score = minimum_score
        self.catalog = catalog
        self.evaluator = evaluator or ThresholdCandidateEvaluator(minimum_score)

    def evaluate_candidate(self, candidate: dict, evidence: list[dict]) -> Determination:
        return self.evaluator.evaluate(candidate, evidence, self.catalog)

    @staticmethod
    def _recipe(decision: Determination) -> dict:
        return {
            "pipeline_id": decision.pipeline.pipeline_id,
            "target_platform": decision.pipeline.platform,
            "target_account": decision.pipeline.account,
            "content_format": decision.pipeline.content_format,
            "visual_profile_id": decision.pipeline.visual_profile_id,
            "angle": decision.angle,
            "audience": decision.audience,
            "objective": decision.objective,
            "key_points": list(decision.key_points),
            "sources": list(decision.sources),
            "priority": decision.priority,
        }

    def consume_next_handoff(self, database: Database) -> ContentJob | None:
        handoffs = database.pending_handoffs(limit=1)
        if not handoffs:
            return None
        handoff = handoffs[0]
        claimed_at = utc_now()
        if not database.claim_handoff(handoff["handoff_id"], claimed_at):
            return None

        payload = json.loads(handoff["payload_json"])
        candidate = payload["candidate"]
        decision = self.evaluate_candidate(candidate, payload.get("evidence", []))
        completed_at = utc_now()
        database.save_determination_decision(
            handoff["handoff_id"],
            "accepted" if decision.should_create else "rejected",
            self._recipe(decision) if decision.should_create else {},
            decision.reasoning,
            completed_at,
        )
        if not decision.should_create:
            database.complete_handoff(handoff["handoff_id"], completed_at, status="rejected")
            return None

        job = ContentJob(
            trend_id=None,
            determination_handoff_id=handoff["handoff_id"],
            candidate_id=candidate["candidate_id"],
            pipeline_id=decision.pipeline.pipeline_id,
            target_platform=decision.pipeline.platform,
            target_account=decision.pipeline.account,
            content_format=decision.pipeline.content_format,
            visual_profile_id=decision.pipeline.visual_profile_id,
            topic=candidate["topic"],
            angle=decision.angle,
            audience=decision.audience,
            objective=decision.objective,
            key_points=list(decision.key_points),
            sources=list(decision.sources),
            priority=decision.priority,
        )
        job.job_id = database.save_content_job(job)
        database.complete_handoff(handoff["handoff_id"], completed_at)
        return job

    # Temporary compatibility path for the offline fixture. Production code
    # consumes DeterminationRequest records through consume_next_handoff.
    def determine(self, trend: Trend) -> ContentJob | None:
        candidate = {"topic": trend.topic, "score": trend.score}
        decision = self.evaluate_candidate(candidate, [{"url": trend.url}] if trend.url else [])
        if not decision.should_create:
            return None
        if trend.id is None:
            raise ValueError("A trend must be persisted before creating a ContentJob")
        return ContentJob(
            trend_id=trend.id,
            pipeline_id=decision.pipeline.pipeline_id,
            target_platform=decision.pipeline.platform,
            target_account=decision.pipeline.account,
            content_format=decision.pipeline.content_format,
            visual_profile_id=decision.pipeline.visual_profile_id,
            topic=trend.topic,
            angle=decision.angle,
            audience=decision.audience,
            objective=decision.objective,
            key_points=list(decision.key_points),
            sources=list(decision.sources),
            priority=decision.priority,
        )


_DETERMINATION_SCHEMA = {
    "type": "object",
    "required": ["should_create", "reasoning"],
    "properties": {
        "should_create": {"type": "boolean"},
        "pipeline_id": {"type": "string"},
        "visual_profile_id": {"type": "string"},
        "angle": {"type": "string"}, "audience": {"type": "string"},
        "objective": {"type": "string"},
        "key_points": {"type": "array", "items": {"type": "string"}},
        "priority": {"type": "integer", "minimum": 0, "maximum": 100},
        "reasoning": {"type": "string"},
    },
}


def _determination_prompt(candidate: dict, evidence: list[dict], capabilities: list[dict]) -> str:
    return f"""You are the determination layer of a content factory. Decide whether a
quantitatively detected candidate should be consumed. If it should, select exactly
one pipeline and its listed visual profile, then write a concise ContentJob recipe.
You must not create the content, write captions, tags, hashtags, or concrete visual
templates. Those belong to the selected pipeline.

Candidate: {json.dumps(candidate, ensure_ascii=False)}
Evidence: {json.dumps(evidence, ensure_ascii=False)}
Available pipeline capabilities: {json.dumps(capabilities, ensure_ascii=False)}

Return only JSON matching the supplied schema. Reject weak, unsafe, stale, or
unsupported candidates. If rejecting, provide only should_create and reasoning; if
accepting, include all recipe fields and choose only IDs from the capability list."""
