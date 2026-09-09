"""Small SQLite persistence layer for the POC state."""

import json
import sqlite3
import gzip
from collections import defaultdict
from datetime import datetime
from pathlib import Path

from common.models import ContentJob, ContentPackage, PostRecord, TopicSnapshot, Trend
from database.migrations import SchemaError
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

CREATE TABLE IF NOT EXISTS trend_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    period_start TEXT NOT NULL,
    topic TEXT NOT NULL,
    source TEXT NOT NULL,
    observation_count INTEGER NOT NULL,
    average_activity REAL NOT NULL,
    maximum_activity REAL NOT NULL,
    first_seen_at TEXT NOT NULL,
    last_seen_at TEXT NOT NULL,
    UNIQUE(period_start, topic, source)
);

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

CREATE TABLE IF NOT EXISTS detection_runs (
    run_id INTEGER PRIMARY KEY AUTOINCREMENT,
    started_at TEXT NOT NULL,
    completed_at TEXT,
    observations_collected INTEGER NOT NULL DEFAULT 0,
    candidates_scored INTEGER NOT NULL DEFAULT 0,
    candidates_selected INTEGER NOT NULL DEFAULT 0,
    status TEXT NOT NULL DEFAULT 'running',
    error TEXT
);

CREATE TABLE IF NOT EXISTS determination_handoffs (
    handoff_id INTEGER PRIMARY KEY AUTOINCREMENT,
    candidate_id INTEGER NOT NULL REFERENCES trend_candidates(id),
    detection_run_id INTEGER NOT NULL REFERENCES detection_runs(run_id),
    payload_json TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending',
    created_at TEXT NOT NULL,
    claimed_at TEXT,
    completed_at TEXT,
    failure_reason TEXT
);

CREATE INDEX IF NOT EXISTS idx_determination_handoffs_status
ON determination_handoffs(status, created_at);

CREATE TABLE IF NOT EXISTS content_threads (
    thread_id INTEGER PRIMARY KEY AUTOINCREMENT,
    origin TEXT NOT NULL CHECK(origin IN ('trend', 'human')),
    status TEXT NOT NULL DEFAULT 'open' CHECK(status IN ('open', 'closed')),
    seed_candidate_id INTEGER REFERENCES trend_candidates(id),
    opportunity_identity TEXT,
    coverage_identity TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE(seed_candidate_id),
    UNIQUE(opportunity_identity)
);

CREATE TABLE IF NOT EXISTS thread_messages (
    message_id INTEGER PRIMARY KEY AUTOINCREMENT,
    thread_id INTEGER NOT NULL REFERENCES content_threads(thread_id),
    sequence_number INTEGER NOT NULL,
    actor TEXT NOT NULL CHECK(actor IN ('human', 'intake_agent')),
    body TEXT NOT NULL,
    created_at TEXT NOT NULL,
    UNIQUE(thread_id, sequence_number)
);

CREATE TABLE IF NOT EXISTS intake_requests (
    intake_request_id INTEGER PRIMARY KEY AUTOINCREMENT,
    thread_id INTEGER NOT NULL REFERENCES content_threads(thread_id),
    input_snapshot_json TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending' CHECK(status IN ('pending', 'claimed', 'needs_clarification', 'completed', 'failed')),
    claimed_at TEXT,
    completed_at TEXT,
    failure_reason TEXT,
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_intake_requests_status
ON intake_requests(status, created_at);

CREATE TABLE IF NOT EXISTS brief_revisions (
    revision_id INTEGER PRIMARY KEY AUTOINCREMENT,
    thread_id INTEGER NOT NULL REFERENCES content_threads(thread_id),
    revision_number INTEGER NOT NULL,
    brief_json TEXT NOT NULL,
    source_snapshot_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    UNIQUE(thread_id, revision_number)
);

CREATE TABLE IF NOT EXISTS determination_requests (
    determination_request_id INTEGER PRIMARY KEY AUTOINCREMENT,
    revision_id INTEGER NOT NULL UNIQUE REFERENCES brief_revisions(revision_id),
    input_snapshot_json TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending' CHECK(status IN ('pending', 'claimed', 'completed', 'failed')),
    claimed_at TEXT,
    completed_at TEXT,
    failure_reason TEXT,
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_determination_requests_status
ON determination_requests(status, created_at);

CREATE TABLE IF NOT EXISTS content_jobs (
    job_id INTEGER PRIMARY KEY AUTOINCREMENT,
    trend_id INTEGER REFERENCES trends(id),
    determination_handoff_id INTEGER REFERENCES determination_handoffs(handoff_id),
    candidate_id INTEGER REFERENCES trend_candidates(id),
    pipeline_id TEXT NOT NULL,
    target_platform TEXT NOT NULL DEFAULT 'bluesky',
    target_account TEXT NOT NULL DEFAULT 'default',
    content_format TEXT NOT NULL DEFAULT 'text_card',
    visual_profile_id TEXT NOT NULL DEFAULT 'default',
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

CREATE TABLE IF NOT EXISTS determination_decisions (
    decision_id INTEGER PRIMARY KEY AUTOINCREMENT,
    handoff_id INTEGER UNIQUE REFERENCES determination_handoffs(handoff_id),
    determination_request_id INTEGER UNIQUE REFERENCES determination_requests(determination_request_id),
    status TEXT NOT NULL,
    recipe_json TEXT NOT NULL DEFAULT '{}',
    reasoning TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS determination_routes (
    route_id INTEGER PRIMARY KEY AUTOINCREMENT,
    decision_id INTEGER NOT NULL REFERENCES determination_decisions(decision_id),
    pipeline_id TEXT NOT NULL,
    disposition TEXT NOT NULL CHECK(disposition IN ('selected', 'skipped', 'blocked', 'reused')),
    fit TEXT NOT NULL,
    reason TEXT NOT NULL,
    angle_json TEXT,
    output_assessment_json TEXT NOT NULL DEFAULT '{}',
    UNIQUE(decision_id, pipeline_id)
);

CREATE TABLE IF NOT EXISTS content_packages (
    content_id INTEGER PRIMARY KEY AUTOINCREMENT,
    job_id INTEGER NOT NULL REFERENCES content_jobs(job_id),
    pipeline_id TEXT NOT NULL,
    platform TEXT NOT NULL DEFAULT 'bluesky',
    account TEXT NOT NULL DEFAULT 'default',
    content_format TEXT NOT NULL DEFAULT 'text_card',
    title TEXT NOT NULL,
    body TEXT NOT NULL,
    caption TEXT NOT NULL,
    visual_spec TEXT NOT NULL DEFAULT '{}',
    assets TEXT NOT NULL DEFAULT '[]',
    sources TEXT NOT NULL DEFAULT '[]',
    tags TEXT NOT NULL DEFAULT '[]',
    hashtags TEXT NOT NULL DEFAULT '[]',
    status TEXT NOT NULL DEFAULT 'awaiting_render',
    metadata_status TEXT NOT NULL DEFAULT 'pending',
    metadata_model TEXT,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS posts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    content_id INTEGER NOT NULL REFERENCES content_packages(content_id),
    pipeline_id TEXT NOT NULL DEFAULT 'poc_pipeline',
    platform TEXT NOT NULL,
    account TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'queued',
    scheduled_at TEXT,
    published_at TEXT,
    external_post_id TEXT,
    error TEXT,
    attempt_count INTEGER NOT NULL DEFAULT 0,
    last_attempt_at TEXT,
    next_attempt_at TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE(content_id, platform, account)
);

CREATE TABLE IF NOT EXISTS post_attempts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    post_id INTEGER NOT NULL REFERENCES posts(id),
    attempt_number INTEGER NOT NULL,
    started_at TEXT NOT NULL,
    completed_at TEXT,
    status TEXT NOT NULL,
    error TEXT,
    UNIQUE(post_id, attempt_number)
);

CREATE TABLE IF NOT EXISTS instagram_containers (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    post_id INTEGER NOT NULL REFERENCES posts(id),
    asset_index INTEGER,
    container_id TEXT NOT NULL,
    container_type TEXT NOT NULL,
    status TEXT NOT NULL,
    created_at TEXT NOT NULL,
    last_checked_at TEXT,
    UNIQUE(post_id, container_id)
);

CREATE TABLE IF NOT EXISTS posting_policies (
    pipeline_id TEXT NOT NULL,
    platform TEXT NOT NULL,
    account TEXT NOT NULL,
    max_posts_per_day INTEGER NOT NULL,
    min_post_interval_minutes INTEGER NOT NULL,
    PRIMARY KEY (pipeline_id, platform, account)
);

CREATE TABLE IF NOT EXISTS api_usage (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    phase TEXT NOT NULL,
    entity_id INTEGER,
    model TEXT NOT NULL,
    input_tokens INTEGER NOT NULL,
    output_tokens INTEGER NOT NULL,
    total_tokens INTEGER NOT NULL,
    estimated_cost_usd REAL,
    created_at TEXT NOT NULL
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
        version = int(self.connection.execute("PRAGMA user_version").fetchone()[0])
        if version != 0:
            raise SchemaError(
                f"Legacy initialization refuses versioned database schema {version}. "
                "Use the versioned detection/workflow entrypoints; no legacy DDL was run."
            )
        self.connection.executescript(SCHEMA)
        self._migrate_determination_decisions()
        self._ensure_columns("trend_candidates", {"cooldown_until": "TEXT"})
        self._ensure_columns("content_jobs", {
            "determination_handoff_id": "INTEGER",
            "determination_request_id": "INTEGER",
            "candidate_id": "INTEGER",
            "target_platform": "TEXT NOT NULL DEFAULT 'bluesky'",
            "target_account": "TEXT NOT NULL DEFAULT 'default'",
            "content_format": "TEXT NOT NULL DEFAULT 'text_card'",
            "visual_profile_id": "TEXT NOT NULL DEFAULT 'default'",
        })
        self._ensure_columns("content_packages", {
            "platform": "TEXT NOT NULL DEFAULT 'bluesky'",
            "account": "TEXT NOT NULL DEFAULT 'default'",
            "content_format": "TEXT NOT NULL DEFAULT 'text_card'",
            "tags": "TEXT NOT NULL DEFAULT '[]'",
            "hashtags": "TEXT NOT NULL DEFAULT '[]'",
            "status": "TEXT NOT NULL DEFAULT 'awaiting_render'",
            "metadata_status": "TEXT NOT NULL DEFAULT 'pending'",
            "metadata_model": "TEXT",
        })
        self._ensure_columns("posts", {
            "pipeline_id": "TEXT NOT NULL DEFAULT 'poc_pipeline'",
            "attempt_count": "INTEGER NOT NULL DEFAULT 0",
            "last_attempt_at": "TEXT",
            "next_attempt_at": "TEXT",
        })
        self.connection.commit()

    def _migrate_determination_decisions(self) -> None:
        """Allow target determination decisions without a legacy handoff.

        The initial POC table required ``handoff_id``. Rebuild only that small
        audit table when opening an older database so historic rows are retained
        and new Intake → Determination records can use their own request FK.
        """
        columns = self.connection.execute("PRAGMA table_info(determination_decisions)").fetchall()
        handoff = next((row for row in columns if row["name"] == "handoff_id"), None)
        request = next((row for row in columns if row["name"] == "determination_request_id"), None)
        if handoff is None or not handoff["notnull"] and request is not None:
            return
        self.connection.executescript("""
            DROP TABLE IF EXISTS determination_routes;
            ALTER TABLE determination_decisions RENAME TO determination_decisions_legacy;
            CREATE TABLE determination_decisions (
                decision_id INTEGER PRIMARY KEY AUTOINCREMENT,
                handoff_id INTEGER UNIQUE REFERENCES determination_handoffs(handoff_id),
                determination_request_id INTEGER UNIQUE REFERENCES determination_requests(determination_request_id),
                status TEXT NOT NULL,
                recipe_json TEXT NOT NULL DEFAULT '{}',
                reasoning TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL
            );
            INSERT INTO determination_decisions
                (decision_id, handoff_id, status, recipe_json, reasoning, created_at)
            SELECT decision_id, handoff_id, status, recipe_json, reasoning, created_at
            FROM determination_decisions_legacy;
            DROP TABLE determination_decisions_legacy;
            CREATE TABLE determination_routes (
                route_id INTEGER PRIMARY KEY AUTOINCREMENT,
                decision_id INTEGER NOT NULL REFERENCES determination_decisions(decision_id),
                pipeline_id TEXT NOT NULL,
                disposition TEXT NOT NULL CHECK(disposition IN ('selected', 'skipped', 'blocked', 'reused')),
                fit TEXT NOT NULL,
                reason TEXT NOT NULL,
                angle_json TEXT,
                output_assessment_json TEXT NOT NULL DEFAULT '{}',
                UNIQUE(decision_id, pipeline_id)
            );
        """)

    def _ensure_columns(self, table: str, columns: dict[str, str]) -> None:
        existing = {row["name"] for row in self.connection.execute(f"PRAGMA table_info({table})").fetchall()}
        for name, definition in columns.items():
            if name not in existing:
                self.connection.execute(f"ALTER TABLE {table} ADD COLUMN {name} {definition}")

    def close(self) -> None:
        self.connection.close()

    def record_api_usage(self, phase: str, entity_id: int | None, model: str,
                         input_tokens: int, output_tokens: int, total_tokens: int,
                         estimated_cost_usd: float | None, created_at: str) -> int:
        cursor = self.connection.execute(
            "INSERT INTO api_usage (phase, entity_id, model, input_tokens, output_tokens, total_tokens, estimated_cost_usd, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (phase, entity_id, model, input_tokens, output_tokens, total_tokens, estimated_cost_usd, created_at),
        )
        self.connection.commit()
        return int(cursor.lastrowid)

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

    def start_detection_run(self, started_at: str) -> int:
        cursor = self.connection.execute("INSERT INTO detection_runs (started_at) VALUES (?)", (started_at,))
        self.connection.commit()
        return int(cursor.lastrowid)

    def finish_detection_run(self, run_id: int, completed_at: str, observations_collected: int, candidates_scored: int, candidates_selected: int, status: str = "completed", error: str | None = None) -> None:
        self.connection.execute(
            "UPDATE detection_runs SET completed_at = ?, observations_collected = ?, candidates_scored = ?, candidates_selected = ?, status = ?, error = ? WHERE run_id = ?",
            (completed_at, observations_collected, candidates_scored, candidates_selected, status, error, run_id),
        )
        self.connection.commit()

    def create_handoff_if_absent(self, candidate_id: int, detection_run_id: int, payload: dict, created_at: str) -> int | None:
        active = self.connection.execute(
            "SELECT handoff_id FROM determination_handoffs WHERE candidate_id = ? AND status IN ('pending', 'claimed') ORDER BY handoff_id DESC LIMIT 1",
            (candidate_id,),
        ).fetchone()
        if active:
            return None
        cursor = self.connection.execute(
            "INSERT INTO determination_handoffs (candidate_id, detection_run_id, payload_json, created_at) VALUES (?, ?, ?, ?)",
            (candidate_id, detection_run_id, json.dumps(payload), created_at),
        )
        self.connection.commit()
        return int(cursor.lastrowid)

    def pending_handoffs(self, limit: int = 20):
        return self.connection.execute(
            "SELECT * FROM determination_handoffs WHERE status = 'pending' ORDER BY created_at, handoff_id LIMIT ?",
            (limit,),
        ).fetchall()

    def claim_handoff(self, handoff_id: int, claimed_at: str) -> bool:
        cursor = self.connection.execute(
            "UPDATE determination_handoffs SET status = 'claimed', claimed_at = ? WHERE handoff_id = ? AND status = 'pending'",
            (claimed_at, handoff_id),
        )
        self.connection.commit()
        return cursor.rowcount == 1

    def complete_handoff(self, handoff_id: int, completed_at: str, status: str = "completed", failure_reason: str | None = None) -> None:
        self.connection.execute(
            "UPDATE determination_handoffs SET status = ?, completed_at = ?, failure_reason = ? WHERE handoff_id = ? AND status = 'claimed'",
            (status, completed_at, failure_reason, handoff_id),
        )
        self.connection.commit()

    def save_determination_decision(self, handoff_id: int, status: str, recipe: dict, reasoning: str, created_at: str) -> int:
        cursor = self.connection.execute(
            "INSERT INTO determination_decisions (handoff_id, status, recipe_json, reasoning, created_at) VALUES (?, ?, ?, ?, ?)",
            (handoff_id, status, json.dumps(recipe), reasoning, created_at),
        )
        self.connection.commit()
        return int(cursor.lastrowid)

    def create_trend_intake_if_absent(self, candidate_id: int, detection_run_id: int,
                                      snapshot: dict, created_at: str) -> int | None:
        """Atomically hand a selected deterministic candidate to Idea Intake."""
        candidate = self.connection.execute(
            "SELECT topic FROM trend_candidates WHERE id = ?", (candidate_id,)
        ).fetchone()
        if candidate is None:
            raise KeyError(f"Trend candidate {candidate_id} was not found")
        existing = self.connection.execute(
            "SELECT intake_request_id FROM intake_requests WHERE thread_id = "
            "(SELECT thread_id FROM content_threads WHERE seed_candidate_id = ?)",
            (candidate_id,),
        ).fetchone()
        if existing is not None:
            return None
        opportunity_identity = f"trend:canonicalization_v1:{candidate['topic']}"
        try:
            with self.connection:
                cursor = self.connection.execute(
                    """INSERT INTO content_threads
                    (origin, status, seed_candidate_id, opportunity_identity, created_at, updated_at)
                    VALUES ('trend', 'open', ?, ?, ?, ?)""",
                    (candidate_id, opportunity_identity, created_at, created_at),
                )
                thread_id = int(cursor.lastrowid)
                frozen_snapshot = dict(snapshot)
                frozen_snapshot["detection_run_id"] = detection_run_id
                frozen_snapshot["candidate_id"] = candidate_id
                request = self.connection.execute(
                    "INSERT INTO intake_requests (thread_id, input_snapshot_json, created_at) VALUES (?, ?, ?)",
                    (thread_id, json.dumps(frozen_snapshot), created_at),
                )
                self.connection.execute(
                    "UPDATE trend_candidates SET status = 'pending_intake', updated_at = ? WHERE id = ?",
                    (created_at, candidate_id),
                )
                return int(request.lastrowid)
        except sqlite3.IntegrityError:
            return None

    def pending_intake_requests(self, limit: int = 20):
        return self.connection.execute(
            "SELECT * FROM intake_requests WHERE status = 'pending' ORDER BY created_at, intake_request_id LIMIT ?",
            (limit,),
        ).fetchall()

    def claim_intake_request(self, intake_request_id: int, claimed_at: str) -> bool:
        cursor = self.connection.execute(
            "UPDATE intake_requests SET status = 'claimed', claimed_at = ? "
            "WHERE intake_request_id = ? AND status = 'pending'",
            (claimed_at, intake_request_id),
        )
        self.connection.commit()
        return cursor.rowcount == 1

    def fail_intake_request(self, intake_request_id: int, failure_reason: str, completed_at: str) -> None:
        self.connection.execute(
            "UPDATE intake_requests SET status = 'failed', failure_reason = ?, completed_at = ? "
            "WHERE intake_request_id = ? AND status = 'claimed'",
            (failure_reason, completed_at, intake_request_id),
        )
        self.connection.commit()

    def complete_intake_with_revision(self, intake_request_id: int, brief: dict,
                                      source_snapshot: dict, coverage_identity: str,
                                      completed_at: str) -> int:
        """Freeze one brief and its pending Determination request in one transaction."""
        row = self.connection.execute(
            "SELECT thread_id FROM intake_requests WHERE intake_request_id = ? AND status = 'claimed'",
            (intake_request_id,),
        ).fetchone()
        if row is None:
            raise ValueError(f"Intake request {intake_request_id} is not claimed")
        with self.connection:
            revision_number = int(self.connection.execute(
                "SELECT COUNT(*) AS count FROM brief_revisions WHERE thread_id = ?", (row["thread_id"],)
            ).fetchone()["count"]) + 1
            revision = self.connection.execute(
                """INSERT INTO brief_revisions
                (thread_id, revision_number, brief_json, source_snapshot_json, created_at)
                VALUES (?, ?, ?, ?, ?)""",
                (row["thread_id"], revision_number, json.dumps(brief), json.dumps(source_snapshot), completed_at),
            )
            revision_id = int(revision.lastrowid)
            request_snapshot = {"brief": brief, "source_snapshot": source_snapshot, "catalog_version": "poc_v1"}
            determination = self.connection.execute(
                "INSERT INTO determination_requests (revision_id, input_snapshot_json, created_at) VALUES (?, ?, ?)",
                (revision_id, json.dumps(request_snapshot), completed_at),
            )
            self.connection.execute(
                "UPDATE content_threads SET coverage_identity = ?, updated_at = ? WHERE thread_id = ?",
                (coverage_identity, completed_at, row["thread_id"]),
            )
            self.connection.execute(
                "UPDATE intake_requests SET status = 'completed', completed_at = ? WHERE intake_request_id = ?",
                (completed_at, intake_request_id),
            )
            return int(determination.lastrowid)

    def pending_determination_requests(self, limit: int = 20):
        return self.connection.execute(
            """SELECT r.*, b.brief_json, b.source_snapshot_json, b.thread_id
            FROM determination_requests r JOIN brief_revisions b ON b.revision_id = r.revision_id
            WHERE r.status = 'pending' ORDER BY r.created_at, r.determination_request_id LIMIT ?""",
            (limit,),
        ).fetchall()

    def claim_determination_request(self, determination_request_id: int, claimed_at: str) -> bool:
        cursor = self.connection.execute(
            "UPDATE determination_requests SET status = 'claimed', claimed_at = ? "
            "WHERE determination_request_id = ? AND status = 'pending'",
            (claimed_at, determination_request_id),
        )
        self.connection.commit()
        return cursor.rowcount == 1

    def fail_determination_request(self, determination_request_id: int, failure_reason: str, completed_at: str) -> None:
        self.connection.execute(
            "UPDATE determination_requests SET status = 'failed', failure_reason = ?, completed_at = ? "
            "WHERE determination_request_id = ? AND status = 'claimed'",
            (failure_reason, completed_at, determination_request_id),
        )
        self.connection.commit()

    def complete_determination_request(self, determination_request_id: int, outcome: str,
                                       recipe: dict, reasoning: str, routes: list[dict],
                                       completed_at: str) -> int:
        """Persist one decision, route summary, optional job, and completion atomically."""
        request = self.connection.execute(
            """SELECT r.revision_id, b.thread_id FROM determination_requests r
            JOIN brief_revisions b ON b.revision_id = r.revision_id
            WHERE r.determination_request_id = ? AND r.status = 'claimed'""",
            (determination_request_id,),
        ).fetchone()
        if request is None:
            raise ValueError(f"Determination request {determination_request_id} is not claimed")
        with self.connection:
            existing = self.connection.execute(
                "SELECT decision_id FROM determination_decisions WHERE determination_request_id = ?",
                (determination_request_id,),
            ).fetchone()
            if existing is not None:
                return int(existing["decision_id"])
            decision = self.connection.execute(
                """INSERT INTO determination_decisions
                (determination_request_id, status, recipe_json, reasoning, created_at)
                VALUES (?, ?, ?, ?, ?)""",
                (determination_request_id, outcome, json.dumps(recipe), reasoning, completed_at),
            )
            decision_id = int(decision.lastrowid)
            for route in routes:
                self.connection.execute(
                    """INSERT INTO determination_routes
                    (decision_id, pipeline_id, disposition, fit, reason, angle_json, output_assessment_json)
                    VALUES (?, ?, ?, ?, ?, ?, ?)""",
                    (decision_id, route["pipeline_id"], route["disposition"], route["fit"], route["reason"],
                     json.dumps(route.get("angle")) if route.get("angle") else None,
                     json.dumps(route.get("output_assessment", {}))),
                )
            if outcome == "accepted":
                candidate = self.connection.execute(
                    "SELECT seed_candidate_id FROM content_threads WHERE thread_id = ?", (request["thread_id"],)
                ).fetchone()
                job = self.connection.execute(
                    """INSERT INTO content_jobs
                    (determination_request_id, candidate_id, pipeline_id, target_platform, target_account,
                     content_format, visual_profile_id, topic, angle, audience, objective, key_points, sources,
                     priority, status, created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'pending', ?, ?)""",
                    (determination_request_id, candidate["seed_candidate_id"] if candidate else None,
                     recipe["pipeline_id"], recipe["target_platform"], recipe["target_account"],
                     recipe["content_format"], recipe["visual_profile_id"], recipe["topic"], recipe["angle"],
                     recipe["audience"], recipe["objective"], json.dumps(recipe["key_points"]),
                     json.dumps(recipe["sources"]), recipe["priority"], completed_at, completed_at),
                )
                _ = int(job.lastrowid)
            self.connection.execute(
                "UPDATE determination_requests SET status = 'completed', completed_at = ? WHERE determination_request_id = ?",
                (completed_at, determination_request_id),
            )
            return decision_id

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

    def archive_and_cleanup(self, cutoff: str, archive_directory: str | Path) -> dict[str, int]:
        """Archive detailed detector records, summarize them, then remove hot data."""
        archive_directory = Path(archive_directory)
        archive_directory.mkdir(parents=True, exist_ok=True)
        counts = {"trend_observations": 0, "topic_snapshots": 0, "source_health": 0}
        tables = (
            ("trend_observations", "observed_at"),
            ("topic_snapshots", "observed_at"),
            ("source_health", "checked_at"),
        )
        for table, time_column in tables:
            rows = self.connection.execute(f"SELECT * FROM {table} WHERE {time_column} < ?", (cutoff,)).fetchall()
            if not rows:
                continue
            rows_by_month = defaultdict(list)
            for row in rows:
                month = datetime.fromisoformat(row[time_column].replace("Z", "+00:00")).strftime("%Y-%m")
                rows_by_month[month].append(row)
            for month, month_rows in rows_by_month.items():
                target = archive_directory / f"{table}-{month}.jsonl.gz"
                with gzip.open(target, "at", encoding="utf-8") as handle:
                    for row in month_rows:
                        handle.write(json.dumps(dict(row), sort_keys=True) + "\n")
            for row in rows:
                if table == "trend_observations":
                    period = row[time_column][:7]
                    self.connection.execute(
                        """INSERT INTO trend_history
                        (period_start, topic, source, observation_count, average_activity, maximum_activity, first_seen_at, last_seen_at)
                        VALUES (?, ?, ?, 1, ?, ?, ?, ?)
                        ON CONFLICT(period_start, topic, source) DO UPDATE SET
                        observation_count = observation_count + 1,
                        average_activity = ((average_activity * observation_count) + excluded.average_activity) / (observation_count + 1),
                        maximum_activity = MAX(maximum_activity, excluded.maximum_activity),
                        first_seen_at = MIN(first_seen_at, excluded.first_seen_at),
                        last_seen_at = MAX(last_seen_at, excluded.last_seen_at)""",
                        (period, row["topic"], row["source"], row["activity_value"], row["activity_value"], row[time_column], row[time_column]),
                    )
            self.connection.execute(f"DELETE FROM {table} WHERE {time_column} < ?", (cutoff,))
            counts[table] = len(rows)
        self.connection.commit()
        return counts

    def save_content_job(self, job: ContentJob) -> int:
        cursor = self.connection.execute(
            "INSERT INTO content_jobs (trend_id, determination_handoff_id, determination_request_id, candidate_id, pipeline_id, target_platform, target_account, content_format, visual_profile_id, topic, angle, audience, objective, key_points, sources, priority, status, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (job.trend_id, job.determination_handoff_id, job.determination_request_id, job.candidate_id, job.pipeline_id, job.target_platform, job.target_account, job.content_format, job.visual_profile_id, job.topic, job.angle, job.audience, job.objective, json.dumps(job.key_points), json.dumps(job.sources), job.priority, job.status, job.created_at, job.updated_at),
        )
        self.connection.commit()
        return int(cursor.lastrowid)

    def pending_content_jobs(self, limit: int = 20):
        return self.connection.execute(
            "SELECT * FROM content_jobs WHERE status = 'pending' ORDER BY priority DESC, created_at, job_id LIMIT ?",
            (limit,),
        ).fetchall()

    def packages_awaiting_render(self, limit: int = 20):
        return self.connection.execute(
            "SELECT * FROM content_packages WHERE status = 'awaiting_render' ORDER BY content_id LIMIT ?",
            (limit,),
        ).fetchall()

    def ready_packages_without_post(self, limit: int = 20):
        return self.connection.execute(
            """SELECT c.* FROM content_packages c
            LEFT JOIN posts p ON p.content_id = c.content_id
            WHERE c.status = 'ready_for_posting' AND p.id IS NULL
            ORDER BY c.content_id LIMIT ?""",
            (limit,),
        ).fetchall()

    def claim_content_job(self, job_id: int, claimed_at: str) -> bool:
        cursor = self.connection.execute(
            "UPDATE content_jobs SET status = 'running', updated_at = ? WHERE job_id = ? AND status = 'pending'",
            (claimed_at, job_id),
        )
        self.connection.commit()
        return cursor.rowcount == 1

    def finish_content_job(self, job_id: int, status: str, updated_at: str) -> None:
        self.connection.execute(
            "UPDATE content_jobs SET status = ?, updated_at = ? WHERE job_id = ? AND status = 'running'",
            (status, updated_at, job_id),
        )
        self.connection.commit()

    def save_content_package(self, package: ContentPackage) -> int:
        cursor = self.connection.execute(
            "INSERT INTO content_packages (job_id, pipeline_id, platform, account, content_format, title, body, caption, visual_spec, assets, sources, tags, hashtags, status, metadata_status, metadata_model, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (package.job_id, package.pipeline_id, package.platform, package.account, package.content_format, package.title, package.body, package.caption, json.dumps(package.visual_spec), json.dumps(package.assets), json.dumps(package.sources), json.dumps(package.tags), json.dumps(package.hashtags), package.status, package.metadata_status, package.metadata_model, package.created_at),
        )
        self.connection.commit()
        return int(cursor.lastrowid)

    def mark_package_rendered(self, content_id: int, asset_path: str) -> None:
        self.mark_package_rendered_assets(content_id, [asset_path], required_asset_count=1)

    def mark_package_rendered_assets(self, content_id: int, asset_paths: list[str], required_asset_count: int) -> None:
        """Record rendered assets and make the package postable only when complete."""
        if required_asset_count < 1:
            raise ValueError("A renderable package must require at least one asset")
        row = self.connection.execute("SELECT assets FROM content_packages WHERE content_id = ?", (content_id,)).fetchone()
        if row is None:
            raise KeyError(f"Content package {content_id} was not found")
        assets = json.loads(row["assets"])
        for asset_path in asset_paths:
            if asset_path not in assets:
                assets.append(asset_path)
        status = "ready_for_posting" if len(assets) >= required_asset_count else "awaiting_render"
        self.connection.execute(
            "UPDATE content_packages SET assets = ?, status = ? WHERE content_id = ?",
            (json.dumps(assets), status, content_id),
        )
        self.connection.commit()

    def set_posting_policy(self, pipeline_id: str, platform: str, account: str, max_posts_per_day: int, min_post_interval_minutes: int) -> None:
        self.connection.execute(
            "INSERT INTO posting_policies (pipeline_id, platform, account, max_posts_per_day, min_post_interval_minutes) VALUES (?, ?, ?, ?, ?) "
            "ON CONFLICT(pipeline_id, platform, account) DO UPDATE SET max_posts_per_day = excluded.max_posts_per_day, min_post_interval_minutes = excluded.min_post_interval_minutes",
            (pipeline_id, platform, account, max_posts_per_day, min_post_interval_minutes),
        )
        self.connection.commit()

    def posting_policy(self, pipeline_id: str, platform: str, account: str):
        return self.connection.execute(
            "SELECT * FROM posting_policies WHERE pipeline_id = ? AND platform = ? AND account = ?",
            (pipeline_id, platform, account),
        ).fetchone()

    def due_posts(self, now: str):
        return self.connection.execute(
            """SELECT p.*, c.pipeline_id AS package_pipeline_id, c.platform AS package_platform,
            c.account AS package_account, c.content_format, c.caption, c.hashtags, c.assets,
            c.status AS package_status
            FROM posts p JOIN content_packages c ON c.content_id = p.content_id
            WHERE (
                p.status = 'scheduled' AND p.scheduled_at <= ?
            ) OR (
                p.status = 'retryable_failure' AND p.next_attempt_at <= ?
            )
            ORDER BY p.scheduled_at, p.id""",
            (now, now),
        ).fetchall()

    def start_post_attempt(self, post_id: int, started_at: str) -> int:
        """Claim a due post and persist its next delivery attempt."""
        row = self.connection.execute(
            "SELECT attempt_count FROM posts WHERE id = ? AND status IN ('scheduled', 'retryable_failure')",
            (post_id,),
        ).fetchone()
        if row is None:
            raise ValueError(f"Post {post_id} is not available for publishing")
        attempt_number = int(row["attempt_count"]) + 1
        self.connection.execute(
            "UPDATE posts SET status = 'publishing', attempt_count = ?, last_attempt_at = ?, updated_at = ? WHERE id = ?",
            (attempt_number, started_at, started_at, post_id),
        )
        cursor = self.connection.execute(
            "INSERT INTO post_attempts (post_id, attempt_number, started_at, status) VALUES (?, ?, ?, 'running')",
            (post_id, attempt_number, started_at),
        )
        self.connection.commit()
        return int(cursor.lastrowid)

    def finish_post_attempt(self, attempt_id: int, status: str, completed_at: str, error: str | None = None) -> None:
        self.connection.execute(
            "UPDATE post_attempts SET status = ?, completed_at = ?, error = ? WHERE id = ?",
            (status, completed_at, error, attempt_id),
        )
        self.connection.commit()

    def record_instagram_container(self, post_id: int, container_id: str, container_type: str,
                                   status: str, created_at: str, asset_index: int | None = None) -> None:
        self.connection.execute(
            """INSERT INTO instagram_containers
            (post_id, asset_index, container_id, container_type, status, created_at, last_checked_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(post_id, container_id) DO UPDATE SET
            status = excluded.status,
            last_checked_at = excluded.last_checked_at""",
            (post_id, asset_index, container_id, container_type, status, created_at,
             created_at if status != "created" else None),
        )
        self.connection.commit()

    def queue_post(self, post: PostRecord) -> int:
        package = self.connection.execute("SELECT pipeline_id FROM content_packages WHERE content_id = ?", (post.content_id,)).fetchone()
        if package is None:
            raise KeyError(f"Content package {post.content_id} was not found")
        cursor = self.connection.execute(
            "INSERT INTO posts (content_id, pipeline_id, platform, account, status, scheduled_at, published_at, external_post_id, error, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (post.content_id, package["pipeline_id"], post.platform, post.account, post.status, post.scheduled_at, post.published_at, post.external_post_id, post.error, post.created_at, post.updated_at),
        )
        self.connection.commit()
        return int(cursor.lastrowid)
