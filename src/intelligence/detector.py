"""Deterministic trend normalization, deduplication, and scoring."""

from collections.abc import Iterable

from common.models import Trend, utc_now
from intelligence.sources import Observation, TrendSource


class TrendDetector:
    def __init__(self, source: TrendSource):
        self.source = source

    def detect(self) -> list[Trend]:
        observations = self.source.collect()
        unique: dict[tuple[str, str], Observation] = {}
        for observation in observations:
            key = (observation.source.lower().strip(), observation.topic.lower().strip())
            if key not in unique or self._growth(observation) > self._growth(unique[key]):
                unique[key] = observation

        return [self._to_trend(observation) for observation in unique.values()]

    @staticmethod
    def _growth(observation: Observation) -> float:
        if observation.baseline_volume <= 0:
            return observation.current_volume if observation.current_volume > 0 else 0.0
        return (observation.current_volume - observation.baseline_volume) / observation.baseline_volume

    @classmethod
    def _to_trend(cls, observation: Observation) -> Trend:
        raw_data = dict(observation.raw_data or {})
        raw_data.update({"current_volume": observation.current_volume, "baseline_volume": observation.baseline_volume})
        return Trend(
            topic=observation.topic.strip(),
            title=observation.title.strip(),
            source=observation.source.strip(),
            url=observation.url,
            observed_at=utc_now(),
            score=cls._growth(observation),
            raw_data=raw_data,
        )
