"""Convert detected trends into pipeline-neutral content jobs."""

from dataclasses import dataclass

from common.models import ContentJob, Trend


@dataclass(frozen=True)
class Determination:
    should_create: bool
    pipeline_id: str = "poc_pipeline"
    angle: str = "Explain why this topic is gaining attention."
    audience: str = "general audience"
    objective: str = "inform"
    key_points: tuple[str, ...] = ()
    sources: tuple[str, ...] = ()
    priority: int = 0


class DeterminationService:
    """Apply a small deterministic policy until the Gemini adapter is added."""

    def __init__(self, minimum_score: float = 0.25, pipeline_id: str = "poc_pipeline"):
        self.minimum_score = minimum_score
        self.pipeline_id = pipeline_id

    def evaluate(self, trend: Trend) -> Determination:
        should_create = trend.score >= self.minimum_score
        priority = max(0, min(100, round(trend.score * 10))) if should_create else 0
        return Determination(
            should_create=should_create,
            pipeline_id=self.pipeline_id,
            key_points=(trend.title, f"Growth score: {trend.score:.2f}"),
            sources=(trend.url,) if trend.url else (),
            priority=priority,
        )

    def create_job(self, trend: Trend, decision: Determination) -> ContentJob | None:
        if not decision.should_create:
            return None
        if trend.id is None:
            raise ValueError("A trend must be persisted before creating a ContentJob")
        return ContentJob(
            trend_id=trend.id,
            pipeline_id=decision.pipeline_id,
            topic=trend.topic,
            angle=decision.angle,
            audience=decision.audience,
            objective=decision.objective,
            key_points=list(decision.key_points),
            sources=list(decision.sources),
            priority=decision.priority,
        )

    def determine(self, trend: Trend) -> ContentJob | None:
        decision = self.evaluate(trend)
        return self.create_job(trend, decision)
