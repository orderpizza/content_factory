"""Trend source contracts and a deterministic local source for the POC."""

from dataclasses import dataclass
import json
from urllib.request import urlopen
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


class HackerNewsSource:
    """Collect top Hacker News stories using the public Firebase API."""

    def __init__(self, limit: int = 20, base_url: str = "https://hacker-news.firebaseio.com/v0"):
        self.limit = limit
        self.base_url = base_url.rstrip("/")

    def collect(self) -> list[Observation]:
        with urlopen(f"{self.base_url}/topstories.json", timeout=15) as response:
            story_ids = json.load(response)[: self.limit]
        observations = []
        for story_id in story_ids:
            with urlopen(f"{self.base_url}/item/{story_id}.json", timeout=15) as response:
                story = json.load(response)
            if story and story.get("type") == "story" and story.get("title"):
                observations.append(Observation(
                    topic=story["title"], title=story["title"], source="hacker_news",
                    current_volume=float(story.get("score", 0)), baseline_volume=0.0,
                    url=story.get("url"), raw_data={"id": story.get("id"), "score": story.get("score", 0)},
                ))
        return observations
