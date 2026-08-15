"""Queue and publication-history rules for the POC posting agent."""

from datetime import datetime, timedelta, timezone

from common.models import PostRecord, utc_now
from database.sqlite import Database


class PostingAgent:
    def __init__(self, database: Database, max_posts_per_day: int = 3, min_post_interval_minutes: int = 60):
        self.database = database
        self.max_posts_per_day = max_posts_per_day
        self.min_post_interval = timedelta(minutes=min_post_interval_minutes)

    def queue(self, post: PostRecord) -> int:
        if self._duplicate_exists(post):
            raise ValueError("This content is already queued for this platform/account")
        if self._daily_limit_reached(post):
            raise ValueError("Daily posting limit reached")
        if self._interval_too_short(post):
            raise ValueError("Minimum posting interval has not elapsed")
        return self.database.queue_post(post)

    def mark_published(self, post_id: int, external_post_id: str, published_at: str | None = None) -> None:
        published_at = published_at or utc_now()
        self.database.connection.execute(
            "UPDATE posts SET status = 'published', published_at = ?, external_post_id = ?, updated_at = ? WHERE id = ?",
            (published_at, external_post_id, utc_now(), post_id),
        )
        self.database.connection.commit()

    def mark_failed(self, post_id: int, error: str) -> None:
        self.database.connection.execute(
            "UPDATE posts SET status = 'failed', error = ?, updated_at = ? WHERE id = ?",
            (error, utc_now(), post_id),
        )
        self.database.connection.commit()

    def _duplicate_exists(self, post: PostRecord) -> bool:
        row = self.database.connection.execute(
            "SELECT 1 FROM posts WHERE content_id = ? AND platform = ? AND account = ?",
            (post.content_id, post.platform, post.account),
        ).fetchone()
        return row is not None

    def _recent_posts(self, post: PostRecord) -> list[str]:
        rows = self.database.connection.execute(
            "SELECT COALESCE(published_at, scheduled_at, created_at) AS timestamp FROM posts WHERE platform = ? AND account = ? AND status IN ('queued', 'scheduled', 'published') ORDER BY timestamp DESC",
            (post.platform, post.account),
        ).fetchall()
        return [row["timestamp"] for row in rows]

    def _daily_limit_reached(self, post: PostRecord) -> bool:
        cutoff = datetime.now(timezone.utc) - timedelta(days=1)
        recent = [timestamp for timestamp in self._recent_posts(post) if self._parse_time(timestamp) >= cutoff]
        return len(recent) >= self.max_posts_per_day

    def _interval_too_short(self, post: PostRecord) -> bool:
        timestamps = self._recent_posts(post)
        if not timestamps:
            return False
        return datetime.now(timezone.utc) - self._parse_time(timestamps[0]) < self.min_post_interval

    @staticmethod
    def _parse_time(value: str) -> datetime:
        parsed = datetime.fromisoformat(value)
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
