"""Explainable historical scoring for emerging topics."""

from common.models import TrendCandidate
from common.models import TopicSnapshot


class TrendScorer:
    def score(self, topic: str, snapshots: list[TopicSnapshot]) -> TrendCandidate:
        if not snapshots:
            raise ValueError("At least one snapshot is required")
        ordered = sorted(snapshots, key=lambda item: item.observed_at)
        current = ordered[-1].activity
        previous = ordered[-2].activity if len(ordered) > 1 else 0.0
        short_history = [snapshot.activity for snapshot in ordered[-4:-1]]
        long_history = [snapshot.activity for snapshot in ordered[:-1]]
        short_baseline = self._average(short_history)
        long_baseline = self._average(long_history)
        velocity = self._relative_change(current, previous)
        baseline_growth = self._relative_change(current, long_baseline)
        acceleration = velocity - self._relative_change(previous, short_baseline)
        persistence = min(1.0, len(ordered) / 5.0)
        source_count = max(snapshot.source_count for snapshot in ordered)
        agreement = min(1.0, source_count / 3.0)
        unusual = min(1.0, max(0.0, baseline_growth) / 2.0)
        score = (max(0.0, velocity) * 0.25) + (max(0.0, acceleration) * 0.15) + (persistence * 0.20) + (agreement * 0.20) + (unusual * 0.20)
        stage = self.lifecycle(baseline_growth, persistence)
        supporting_sources = sorted({source for snapshot in ordered for source in snapshot.sources})
        return TrendCandidate(
            topic=topic,
            score=round(score, 4),
            lifecycle_stage=stage,
            score_breakdown={"velocity": round(velocity, 4), "acceleration": round(acceleration, 4), "baseline_growth": round(baseline_growth, 4), "persistence": round(persistence, 4), "source_agreement": round(agreement, 4), "unusual_activity": round(unusual, 4)},
            supporting_sources=supporting_sources,
            first_seen_at=ordered[0].observed_at,
            last_seen_at=ordered[-1].observed_at,
        )

    @staticmethod
    def _relative_change(current: float, previous: float) -> float:
        if previous <= 0:
            return 1.0 if current > 0 else 0.0
        return max(-1.0, min(1.0, (current - previous) / previous))

    @staticmethod
    def _average(values: list[float]) -> float:
        return sum(values) / len(values) if values else 0.0

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
