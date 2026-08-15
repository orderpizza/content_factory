"""Trend source contracts and a deterministic local source for the POC."""

from dataclasses import dataclass
import json
from urllib.parse import urljoin
from urllib.request import urlopen
from xml.etree import ElementTree
from datetime import date, timedelta
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
    source_item_id: str | None = None


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


class RssSource:
    """Collect recent entries from an RSS or Atom feed."""

    def __init__(self, feed_url: str, limit: int = 20):
        self.feed_url = feed_url
        self.limit = limit

    def collect(self) -> list[Observation]:
        with urlopen(self.feed_url, timeout=15) as response:
            root = ElementTree.fromstring(response.read())
        entries = root.findall(".//item") or root.findall(".//{http://www.w3.org/2005/Atom}entry")
        observations = []
        for entry in entries[: self.limit]:
            title = self._text(entry, "title")
            link = self._link(entry)
            if title:
                observations.append(Observation(
                    topic=title, title=title, source="rss", current_volume=1.0,
                    baseline_volume=0.0, url=link,
                ))
        return observations

    @staticmethod
    def _text(entry: ElementTree.Element, name: str) -> str:
        node = entry.find(name)
        if node is None:
            node = entry.find(f"{{http://www.w3.org/2005/Atom}}{name}")
        return (node.text or "").strip() if node is not None else ""

    @staticmethod
    def _link(entry: ElementTree.Element) -> str | None:
        node = entry.find("link")
        if node is not None and node.text:
            return node.text.strip()
        atom_node = entry.find("{http://www.w3.org/2005/Atom}link")
        return atom_node.get("href") if atom_node is not None else None


class CombinedTrendSource:
    def __init__(self, sources: list[TrendSource]):
        self.sources = sources

    def collect(self) -> list[Observation]:
        observations = []
        for source in self.sources:
            observations.extend(source.collect())
        return observations


class WikimediaPageviewSource:
    """Collect the previous day's most-viewed Wikipedia articles."""

    def __init__(self, project: str = "en.wikipedia.org", limit: int = 50, base_url: str = "https://wikimedia.org/api/rest_v1"):
        self.project = project
        self.limit = limit
        self.base_url = base_url.rstrip("/")

    def collect(self) -> list[Observation]:
        day = date.today() - timedelta(days=1)
        url = f"{self.base_url}/metrics/pageviews/top/{self.project}/all-access/{day:%Y/%m/%d}"
        with urlopen(url, timeout=20) as response:
            data = json.load(response)
        return [Observation(
            topic=item["article"].replace("_", " "), title=item["article"].replace("_", " "),
            source="wikimedia", current_volume=float(item.get("views", 0)), baseline_volume=0.0,
            url=f"https://{self.project}/wiki/{item['article']}",
            source_item_id=str(item.get("article")), raw_data={"rank": rank, "views": item.get("views", 0)},
        ) for rank, item in enumerate(data.get("items", [])[0].get("articles", [])[: self.limit], start=1)]
