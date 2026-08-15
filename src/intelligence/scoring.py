"""Explainable historical scoring for emerging topics."""

from dataclasses import dataclass

from common.models import TrendCandidate


@dataclass(frozen=True)
class TopicSnapshot:
    topic: str
    source: str
    activity: float
    observed_at: str


class TrendScorer:
    def score(self, topic: str, snapshots: list[TopicSnapshot]) -> TrendCandidate:
        if not snapshots:
            raise ValueError("At least one snapshot is required")
        ordered = sorted(snapshots, key=lambda item: item.observed_at)
        current = ordered[-1].activity
        previous = ordered[-2].activity if len(ordered) > 1 else 0.0
        velocity = self._relative_change(current, previous)
        persistence = min(1.0, len(ordered) / 5.0)
        source_count = len({snapshot.source for snapshot in ordered})
        agreement = min(1.0, source_count / 3.0)
        unusual = min(1.0, velocity / 2.0) if velocity > 0 else 0.0
        score = (velocity * 0.30) + (persistence * 0.20) + (agreement * 0.20) + (unusual * 0.15)
        stage = self.lifecycle(velocity, persistence)
        return TrendCandidate(
            topic=topic,
            score=round(score, 4),
            lifecycle_stage=stage,
            score_breakdown={"velocity": round(velocity, 4), "persistence": round(persistence, 4), "source_agreement": round(agreement, 4), "unusual_activity": round(unusual, 4)},
            supporting_sources=sorted({snapshot.source for snapshot in ordered}),
            first_seen_at=ordered[0].observed_at,
            last_seen_at=ordered[-1].observed_at,
        )

    @staticmethod
    def _relative_change(current: float, previous: float) -> float:
        if previous <= 0:
            return 1.0 if current > 0 else 0.0
        return max(-1.0, min(1.0, (current - previous) / previous))

    @staticmethod
    def lifecycle(velocity: float, persistence: float) -> str:
        if persistence <= 0.2:
            return "NEW"
        if velocity >= 0.5:
            return "EMERGING"
        if velocity > 0.05:
            return "RISING"
        if velocity >= -0.05:
            return "PEAK"
        if velocity >= -0.5:
            return "DECLINING"
        return "FADING"
