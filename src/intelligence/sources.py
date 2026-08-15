"""Trend source contracts and a deterministic local source for the POC."""

from dataclasses import dataclass
import json
import base64
import os
from urllib.parse import urlparse
from urllib.request import Request, urlopen
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
                    topic=title, title=title, source=f"rss_{urlparse(self.feed_url).netloc}", current_volume=1.0,
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
        data = None
        for offset in range(0, 12):
            day = date.today() - timedelta(days=30 * offset)
            url = f"{self.base_url}/metrics/pageviews/top/{self.project}/all-access/{day:%Y/%m}/all-days"
            request = Request(url, headers={"User-Agent": "content-factory-poc/0.1 (local trend research)"})
            try:
                with urlopen(request, timeout=20) as response:
                    data = json.load(response)
                break
            except Exception:
                if offset == 11:
                    raise
        if data is None:
            return []
        return [Observation(
            topic=item["article"].replace("_", " "), title=item["article"].replace("_", " "),
            source="wikimedia", current_volume=float(item.get("views", 0)), baseline_volume=0.0,
            url=f"https://{self.project}/wiki/{item['article']}",
            source_item_id=str(item.get("article")), raw_data={"rank": rank, "views": item.get("views", 0)},
        ) for rank, item in enumerate(data.get("items", [])[0].get("articles", [])[: self.limit], start=1)]


class RedditSource:
    """Collect recent Reddit posts using application-only OAuth."""

    def __init__(self, subreddits: list[str], client_id: str | None = None, client_secret: str | None = None, user_agent: str = "content-factory-poc/0.1", limit: int = 25):
        self.subreddits = subreddits
        self.client_id = client_id or os.getenv("REDDIT_CLIENT_ID")
        self.client_secret = client_secret or os.getenv("REDDIT_CLIENT_SECRET")
        self.user_agent = user_agent
        self.limit = limit

    def collect(self) -> list[Observation]:
        if not self.client_id or not self.client_secret:
            raise RuntimeError("Reddit credentials are not configured")
        token_request = Request(
            "https://www.reddit.com/api/v1/access_token",
            data=b"grant_type=client_credentials",
            headers={
                "Authorization": "Basic " + base64.b64encode(f"{self.client_id}:{self.client_secret}".encode()).decode(),
                "Content-Type": "application/x-www-form-urlencoded",
                "User-Agent": self.user_agent,
            }, method="POST",
        )
        with urlopen(token_request, timeout=20) as response:
            token = json.load(response)["access_token"]
        observations = []
        for subreddit in self.subreddits:
            request = Request(
                f"https://oauth.reddit.com/r/{subreddit}/hot.json?limit={self.limit}",
                headers={"Authorization": f"Bearer {token}", "User-Agent": self.user_agent},
            )
            with urlopen(request, timeout=20) as response:
                payload = json.load(response)
            for child in payload.get("data", {}).get("children", []):
                post = child.get("data", {})
                if post.get("title"):
                    observations.append(Observation(
                        topic=post["title"], title=post["title"], source=f"reddit_{subreddit}",
                        current_volume=float(post.get("score", 0) + post.get("num_comments", 0)), baseline_volume=0.0,
                        url=f"https://www.reddit.com{post.get('permalink', '')}", source_item_id=post.get("id"),
                        raw_data={"score": post.get("score", 0), "comments": post.get("num_comments", 0)},
                    ))
        return observations


class YouTubeSource:
    """Collect popular YouTube videos through the free Data API quota."""

    def __init__(self, api_key: str | None = None, region: str = "US", limit: int = 25):
        self.api_key = api_key or os.getenv("YOUTUBE_API_KEY")
        self.region = region
        self.limit = limit

    def collect(self) -> list[Observation]:
        if not self.api_key:
            raise RuntimeError("YouTube API key is not configured")
        url = f"https://www.googleapis.com/youtube/v3/videos?part=snippet,statistics&chart=mostPopular&regionCode={self.region}&maxResults={self.limit}&key={self.api_key}"
        with urlopen(Request(url, headers={"User-Agent": "content-factory-poc/0.1"}), timeout=20) as response:
            payload = json.load(response)
        return [Observation(
            topic=item["snippet"]["title"], title=item["snippet"]["title"], source=f"youtube_{self.region}",
            current_volume=float(item.get("statistics", {}).get("viewCount", 0)), baseline_volume=0.0,
            url=f"https://www.youtube.com/watch?v={item['id']}", source_item_id=item["id"],
            raw_data={"views": item.get("statistics", {}).get("viewCount", 0), "likes": item.get("statistics", {}).get("likeCount", 0)},
        ) for item in payload.get("items", [])]
