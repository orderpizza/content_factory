"""Trend source contracts and a deterministic local source for the POC."""

from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class Observation:
    topic: str
    title: str
    source: str
    current_volume: float
    baseline_volume: float
    url: str | None = None
    raw_data: dict[str, object] | None = None


class TrendSource(Protocol):
    def collect(self) -> list[Observation]:
        """Return the observations available during this collection run."""


class FixtureTrendSource:
    def __init__(self, observations: list[Observation]):
        self.observations = observations

    def collect(self) -> list[Observation]:
        return list(self.observations)
