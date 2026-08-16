"""Small SQLite persistence layer for the POC state."""

import json
import sqlite3
from pathlib import Path

from common.models import ContentJob, ContentPackage, PostRecord, TopicSnapshot, Trend
from intelligence.sources import Observation


SCHEMA = """
CREATE TABLE IF NOT EXISTS trends (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    topic TEXT NOT NULL,
    title TEXT NOT NULL,
    source TEXT NOT NULL,
    url TEXT,
    observed_at TEXT NOT NULL,
    score REAL NOT NULL DEFAULT 0,
    raw_data TEXT NOT NULL DEFAULT '{}'
);

CREATE TABLE IF NOT EXISTS trend_observations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    topic TEXT NOT NULL,
    title TEXT NOT NULL,
    source TEXT NOT NULL,
    source_item_id TEXT,
    url TEXT,
    observed_at TEXT NOT NULL,
    activity_value REAL NOT NULL,
    baseline_value REAL NOT NULL,
    raw_data TEXT NOT NULL DEFAULT '{}'
);

CREATE INDEX IF NOT EXISTS idx_trend_observations_topic_time
ON trend_observations(topic, observed_at);

CREATE TABLE IF NOT EXISTS topic_snapshots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    topic TEXT NOT NULL,
    observed_at TEXT NOT NULL,
    activity REAL NOT NULL,
    source_count INTEGER NOT NULL,
    mention_count INTEGER NOT NULL,
    sources TEXT NOT NULL DEFAULT '[]'
);

CREATE INDEX IF NOT EXISTS idx_topic_snapshots_topic_time
ON topic_snapshots(topic, observed_at);

CREATE TABLE IF NOT EXISTS source_health (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source TEXT NOT NULL,
    checked_at TEXT NOT NULL,
    success INTEGER NOT NULL,
    attempts INTEGER NOT NULL,
    error TEXT
);

CREATE TABLE IF NOT EXISTS trend_candidates (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    topic TEXT NOT NULL UNIQUE,
    score REAL NOT NULL,
    lifecycle_stage TEXT NOT NULL,
    score_breakdown TEXT NOT NULL DEFAULT '{}',
    supporting_sources TEXT NOT NULL DEFAULT '[]',
    first_seen_at TEXT,
    last_seen_at TEXT,
    status TEXT NOT NULL DEFAULT 'new',
    evaluated_at TEXT,
    cooldown_until TEXT,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS content_jobs (
    job_id INTEGER PRIMARY KEY AUTOINCREMENT,
    trend_id INTEGER NOT NULL REFERENCES trends(id),
    pipeline_id TEXT NOT NULL,
    topic TEXT NOT NULL,
    angle TEXT NOT NULL,
    audience TEXT NOT NULL,
    objective TEXT NOT NULL,
    key_points TEXT NOT NULL DEFAULT '[]',
    sources TEXT NOT NULL DEFAULT '[]',
    priority INTEGER NOT NULL DEFAULT 0,
    status TEXT NOT NULL DEFAULT 'pending',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS content_packages (
    content_id INTEGER PRIMARY KEY AUTOINCREMENT,
    job_id INTEGER NOT NULL REFERENCES content_jobs(job_id),
    pipeline_id TEXT NOT NULL,
    title TEXT NOT NULL,
    body TEXT NOT NULL,
    caption TEXT NOT NULL,
    visual_spec TEXT NOT NULL DEFAULT '{}',
    assets TEXT NOT NULL DEFAULT '[]',
    sources TEXT NOT NULL DEFAULT '[]',
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS posts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    content_id INTEGER NOT NULL REFERENCES content_packages(content_id),
    platform TEXT NOT NULL,
    account TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'queued',
    scheduled_at TEXT,
    published_at TEXT,
    external_post_id TEXT,
    error TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE(content_id, platform, account)
);
"""


class Database:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.connection = sqlite3.connect(self.path)
        self.connection.row_factory = sqlite3.Row
        self.connection.execute("PRAGMA foreign_keys = ON")

    def initialize(self) -> None:
        self.connection.executescript(SCHEMA)
        columns = {row["name"] for row in self.connection.execute("PRAGMA table_info(trend_candidates)").fetchall()}
        if "cooldown_until" not in columns:
            self.connection.execute("ALTER TABLE trend_candidates ADD COLUMN cooldown_until TEXT")
        self.connection.commit()

    def close(self) -> None:
        self.connection.close()

    def save_trend(self, trend: Trend) -> int:
        cursor = self.connection.execute(
            "INSERT INTO trends (topic, title, source, url, observed_at, score, raw_data) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (trend.topic, trend.title, trend.source, trend.url, trend.observed_at, trend.score, json.dumps(trend.raw_data)),
        )
        self.connection.commit()
        return int(cursor.lastrowid)

    def get_trend(self, trend_id: int) -> Trend:
        row = self.connection.execute("SELECT * FROM trends WHERE id = ?", (trend_id,)).fetchone()
        if row is None:
            raise KeyError(f"Trend {trend_id} was not found")
        return Trend(row["topic"], row["title"], row["source"], row["url"], row["observed_at"], row["score"], json.loads(row["raw_data"]), row["id"])

    def save_observation(self, observation: Observation, observed_at: str) -> int:
        cursor = self.connection.execute(
            "INSERT INTO trend_observations (topic, title, source, source_item_id, url, observed_at, activity_value, baseline_value, raw_data) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (observation.topic, observation.title, observation.source, observation.source_item_id, observation.url, observed_at, observation.current_volume, observation.baseline_volume, json.dumps(observation.raw_data or {})),
        )
        self.connection.commit()
        return int(cursor.lastrowid)

    def save_topic_snapshot(self, snapshot: TopicSnapshot) -> int:
        cursor = self.connection.execute(
            "INSERT INTO topic_snapshots (topic, observed_at, activity, source_count, mention_count, sources) VALUES (?, ?, ?, ?, ?, ?)",
            (snapshot.topic, snapshot.observed_at, snapshot.activity, snapshot.source_count, snapshot.mention_count, json.dumps(snapshot.sources)),
        )
        self.connection.commit()
        return int(cursor.lastrowid)

    def topic_history(self, topic: str, limit: int = 20) -> list[TopicSnapshot]:
        rows = self.connection.execute(
            "SELECT topic, observed_at, activity, source_count, mention_count, sources FROM topic_snapshots WHERE topic = ? ORDER BY observed_at DESC LIMIT ?",
            (topic, limit),
        ).fetchall()
        return [TopicSnapshot(row["topic"], row["observed_at"], row["activity"], row["source_count"], row["mention_count"], json.loads(row["sources"])) for row in reversed(rows)]

    def snapshot_topics(self) -> list[str]:
        rows = self.connection.execute("SELECT DISTINCT topic FROM topic_snapshots ORDER BY topic").fetchall()
        return [row["topic"] for row in rows]

    def save_source_health(self, source: str, checked_at: str, success: bool, attempts: int, error: str | None = None) -> int:
        cursor = self.connection.execute(
            "INSERT INTO source_health (source, checked_at, success, attempts, error) VALUES (?, ?, ?, ?, ?)",
            (source, checked_at, int(success), attempts, error),
        )
        self.connection.commit()
        return int(cursor.lastrowid)

    def upsert_candidate(self, candidate, updated_at: str) -> int:
        self.connection.execute(
            """INSERT INTO trend_candidates
            (topic, score, lifecycle_stage, score_breakdown, supporting_sources, first_seen_at, last_seen_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(topic) DO UPDATE SET score=excluded.score, lifecycle_stage=excluded.lifecycle_stage,
            score_breakdown=excluded.score_breakdown, supporting_sources=excluded.supporting_sources,
            first_seen_at=excluded.first_seen_at, last_seen_at=excluded.last_seen_at, updated_at=excluded.updated_at""",
            (candidate.topic, candidate.score, candidate.lifecycle_stage, json.dumps(candidate.score_breakdown), json.dumps(candidate.supporting_sources), candidate.first_seen_at, candidate.last_seen_at, updated_at),
        )
        self.connection.commit()
        row = self.connection.execute("SELECT id FROM trend_candidates WHERE topic = ?", (candidate.topic,)).fetchone()
        return int(row["id"])

    def eligible_candidates(self, now: str, limit: int = 20):
        rows = self.connection.execute(
            "SELECT * FROM trend_candidates WHERE status IN ('new', 'active', 'pending_determination') AND (cooldown_until IS NULL OR cooldown_until <= ?) ORDER BY score DESC LIMIT ?",
            (now, limit),
        ).fetchall()
        return rows

    def mark_candidates_for_determination(self, topics: list[str], updated_at: str) -> None:
        if not topics:
            return
        placeholders = ", ".join("?" for _ in topics)
        self.connection.execute(
            f"UPDATE trend_candidates SET status = 'pending_determination', updated_at = ? WHERE topic IN ({placeholders}) AND (cooldown_until IS NULL OR cooldown_until <= ?)",
            (updated_at, *topics, updated_at),
        )
        self.connection.commit()

    def set_candidate_cooldown(self, candidate_id: int, until: str, status: str = "active") -> None:
        self.connection.execute(
            "UPDATE trend_candidates SET status = ?, cooldown_until = ?, evaluated_at = ?, updated_at = ? WHERE id = ?",
            (status, until, until, until, candidate_id),
        )
        self.connection.commit()

    def claim_candidate(self, candidate_id: int, claimed_at: str, cooldown_until: str) -> bool:
        cursor = self.connection.execute(
            "UPDATE trend_candidates SET status = 'evaluating', evaluated_at = ?, cooldown_until = ?, updated_at = ? WHERE id = ? AND status IN ('new', 'active', 'pending_determination') AND (cooldown_until IS NULL OR cooldown_until <= ?)",
            (claimed_at, cooldown_until, claimed_at, candidate_id, claimed_at),
        )
        self.connection.commit()
        return cursor.rowcount == 1

    def cleanup_before(self, cutoff: str) -> dict[str, int]:
        counts = {}
        for table, column in (("trend_observations", "observed_at"), ("topic_snapshots", "observed_at"), ("source_health", "checked_at")):
            cursor = self.connection.execute(f"DELETE FROM {table} WHERE {column} < ?", (cutoff,))
            counts[table] = cursor.rowcount
        self.connection.commit()
        return counts

    def save_content_job(self, job: ContentJob) -> int:
        cursor = self.connection.execute(
            "INSERT INTO content_jobs (trend_id, pipeline_id, topic, angle, audience, objective, key_points, sources, priority, status, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (job.trend_id, job.pipeline_id, job.topic, job.angle, job.audience, job.objective, json.dumps(job.key_points), json.dumps(job.sources), job.priority, job.status, job.created_at, job.updated_at),
        )
        self.connection.commit()
        return int(cursor.lastrowid)

    def save_content_package(self, package: ContentPackage) -> int:
        cursor = self.connection.execute(
            "INSERT INTO content_packages (job_id, pipeline_id, title, body, caption, visual_spec, assets, sources, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (package.job_id, package.pipeline_id, package.title, package.body, package.caption, json.dumps(package.visual_spec), json.dumps(package.assets), json.dumps(package.sources), package.created_at),
        )
        self.connection.commit()
        return int(cursor.lastrowid)

    def queue_post(self, post: PostRecord) -> int:
        cursor = self.connection.execute(
            "INSERT INTO posts (content_id, platform, account, status, scheduled_at, published_at, external_post_id, error, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (post.content_id, post.platform, post.account, post.status, post.scheduled_at, post.published_at, post.external_post_id, post.error, post.created_at, post.updated_at),
        )
        self.connection.commit()
        return int(cursor.lastrowid)
