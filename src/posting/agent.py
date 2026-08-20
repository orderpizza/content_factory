"""Queue and publication-history rules for the POC posting agent."""

from datetime import datetime, timedelta, timezone
import json
from typing import Mapping, Protocol
from urllib.request import Request, urlopen

from common.models import PostRecord, utc_now
from database.sqlite import Database


class PackagePublisher(Protocol):
    """Platform adapter that publishes one ready, persisted content package."""

    def publish_package(self, package: Mapping[str, object]) -> str:
        """Return the platform's external post identifier."""


class PostingAgent:
    """Deterministically schedule and publish ready platform packages."""

    def __init__(self, database: Database, max_posts_per_day: int = 3, min_post_interval_minutes: int = 60,
                 max_delivery_attempts: int = 3, retry_delay_minutes: int = 15):
        self.database = database
        self.max_posts_per_day = max_posts_per_day
        self.min_post_interval = timedelta(minutes=min_post_interval_minutes)
        self.max_delivery_attempts = max_delivery_attempts
        self.retry_delay = timedelta(minutes=retry_delay_minutes)

    def queue(self, post: PostRecord, now: datetime | None = None) -> int:
        package = self.database.connection.execute(
            "SELECT pipeline_id, platform, account, status FROM content_packages WHERE content_id = ?",
            (post.content_id,),
        ).fetchone()
        if package is None:
            raise KeyError(f"Content package {post.content_id} was not found")
        if package["status"] != "ready_for_posting":
            raise ValueError("Content package is not ready for posting")
        if post.platform != package["platform"] or post.account != package["account"]:
            raise ValueError("Post destination must match the content package destination")
        if self._duplicate_exists(post):
            raise ValueError("This content is already queued for this platform/account")
        now = now or datetime.now(timezone.utc)
        scheduled_at = self._next_eligible_time(package["pipeline_id"], post.platform, post.account, now)
        post.status = "scheduled"
        post.scheduled_at = scheduled_at.isoformat()
        post.updated_at = utc_now()
        return self.database.queue_post(post)

    def mark_published(self, post_id: int, external_post_id: str, published_at: str | None = None) -> None:
        published_at = published_at or utc_now()
        self.database.connection.execute(
            "UPDATE posts SET status = 'published', published_at = ?, external_post_id = ?, error = NULL, next_attempt_at = NULL, updated_at = ? WHERE id = ?",
            (published_at, external_post_id, utc_now(), post_id),
        )
        self.database.connection.commit()

    def mark_failed(self, post_id: int, error: str) -> None:
        self.database.connection.execute(
            "UPDATE posts SET status = 'failed', error = ?, updated_at = ? WHERE id = ?",
            (error, utc_now(), post_id),
        )
        self.database.connection.commit()

    def queue_ready_packages(self, now: datetime | None = None) -> int:
        """Move every completed, unqueued package into its cadence-derived slot."""
        queued = 0
        for package in self.database.ready_packages_without_post():
            self.queue(
                PostRecord(package["content_id"], package["platform"], package["account"]),
                now=now,
            )
            queued += 1
        return queued

    def publish_due(self, publishers, now: datetime | None = None) -> int:
        """Publish due posts through platform adapters.

        A single legacy text publisher remains accepted for the existing Bluesky
        POC. New adapters receive the persisted package row and own their
        platform-specific upload protocol.
        """
        now = now or datetime.now(timezone.utc)
        published = 0
        for post in self.database.due_posts(now.isoformat()):
            attempt_id = self.database.start_post_attempt(post["id"], now.isoformat())
            try:
                publisher = publishers.get(post["platform"]) if isinstance(publishers, Mapping) else publishers
                if publisher is None:
                    raise RuntimeError(f"No publisher is configured for platform: {post['platform']}")
                if hasattr(publisher, "publish_package"):
                    if hasattr(publisher, "container_recorder"):
                        publisher.container_recorder = lambda container_id, container_type, asset_index, status, created_at: self.database.record_instagram_container(
                            post["id"], container_id, container_type, status, created_at, asset_index
                        )
                    external_post_id = publisher.publish_package(post)
                else:
                    hashtags = json.loads(post["hashtags"])
                    text = " ".join(part for part in [post["caption"], *hashtags] if part).strip()
                    external_post_id = publisher.publish(text)
                self.mark_published(post["id"], external_post_id, now.isoformat())
                self.database.finish_post_attempt(attempt_id, "published", now.isoformat())
                published += 1
            except Exception as error:
                retryable = not isinstance(error, (KeyError, ValueError))
                attempts = int(post["attempt_count"]) + 1
                if retryable and attempts < self.max_delivery_attempts:
                    next_attempt = now + self.retry_delay * (2 ** (attempts - 1))
                    self.database.connection.execute(
                        "UPDATE posts SET status = 'retryable_failure', error = ?, next_attempt_at = ?, updated_at = ? WHERE id = ?",
                        (str(error), next_attempt.isoformat(), utc_now(), post["id"]),
                    )
                    self.database.connection.commit()
                    self.database.finish_post_attempt(attempt_id, "retryable_failure", now.isoformat(), str(error))
                else:
                    self.mark_failed(post["id"], str(error))
                    self.database.finish_post_attempt(attempt_id, "failed", now.isoformat(), str(error))
        return published


    def _duplicate_exists(self, post: PostRecord) -> bool:
        row = self.database.connection.execute(
            "SELECT 1 FROM posts WHERE content_id = ? AND platform = ? AND account = ?",
            (post.content_id, post.platform, post.account),
        ).fetchone()
        return row is not None

    def _recent_posts(self, pipeline_id: str, platform: str, account: str) -> list[str]:
        rows = self.database.connection.execute(
            "SELECT COALESCE(published_at, scheduled_at, created_at) AS timestamp FROM posts WHERE pipeline_id = ? AND platform = ? AND account = ? AND status IN ('scheduled', 'published') ORDER BY timestamp",
            (pipeline_id, platform, account),
        ).fetchall()
        return [row["timestamp"] for row in rows]

    def _next_eligible_time(self, pipeline_id: str, platform: str, account: str, now: datetime) -> datetime:
        policy = self.database.posting_policy(pipeline_id, platform, account)
        daily_limit = int(policy["max_posts_per_day"]) if policy else self.max_posts_per_day
        interval = timedelta(minutes=int(policy["min_post_interval_minutes"]) if policy else int(self.min_post_interval.total_seconds() // 60))
        timestamps = [self._parse_time(value) for value in self._recent_posts(pipeline_id, platform, account)]
        scheduled = max(now, timestamps[-1] + interval) if timestamps else now
        while len([timestamp for timestamp in timestamps if scheduled - timedelta(days=1) < timestamp <= scheduled]) >= daily_limit:
            scheduled = min(timestamp for timestamp in timestamps if scheduled - timedelta(days=1) < timestamp <= scheduled) + timedelta(days=1)
        return scheduled

    @staticmethod
    def _parse_time(value: str) -> datetime:
        parsed = datetime.fromisoformat(value)
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


class BlueskyPublisher:
    """Publish text posts through Bluesky using an app password."""

    def __init__(self, handle: str, app_password: str, service_url: str = "https://bsky.social"):
        self.handle = handle
        self.app_password = app_password
        self.service_url = service_url.rstrip("/")

    def publish(self, text: str) -> str:
        session = self._request("com.atproto.server.createSession", {"identifier": self.handle, "password": self.app_password})
        record = {"$type": "app.bsky.feed.post", "text": text, "createdAt": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")}
        response = self._request("com.atproto.repo.createRecord", {"repo": session["did"], "collection": "app.bsky.feed.post", "record": record}, session["accessJwt"])
        return response["uri"]

    def _request(self, endpoint: str, payload: dict, token: str | None = None) -> dict:
        headers = {"Content-Type": "application/json"}
        if token:
            headers["Authorization"] = f"Bearer {token}"
        request = Request(f"{self.service_url}/xrpc/{endpoint}", data=json.dumps(payload).encode(), headers=headers, method="POST")
        with urlopen(request, timeout=20) as response:
            return json.load(response)
