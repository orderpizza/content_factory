"""Explicit data contracts shared across POC components."""

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class Trend:
    topic: str
    title: str
    source: str
    url: str | None = None
    observed_at: str = field(default_factory=utc_now)
    score: float = 0.0
    raw_data: dict[str, Any] = field(default_factory=dict)
    id: int | None = None


@dataclass
class TrendCandidate:
    topic: str
    score: float
    lifecycle_stage: str
    score_breakdown: dict[str, float] = field(default_factory=dict)
    supporting_sources: list[str] = field(default_factory=list)
    first_seen_at: str | None = None
    last_seen_at: str | None = None


@dataclass
class ContentJob:
    trend_id: int
    pipeline_id: str
    topic: str
    angle: str
    audience: str
    objective: str
    key_points: list[str] = field(default_factory=list)
    sources: list[str] = field(default_factory=list)
    priority: int = 0
    status: str = "pending"
    job_id: int | None = None
    created_at: str = field(default_factory=utc_now)
    updated_at: str = field(default_factory=utc_now)


@dataclass
class ContentPackage:
    job_id: int
    pipeline_id: str
    title: str
    body: str
    caption: str
    visual_spec: dict[str, Any] = field(default_factory=dict)
    assets: list[str] = field(default_factory=list)
    sources: list[str] = field(default_factory=list)
    content_id: int | None = None
    created_at: str = field(default_factory=utc_now)


@dataclass
class PostRecord:
    content_id: int
    platform: str
    account: str
    status: str = "queued"
    scheduled_at: str | None = None
    published_at: str | None = None
    external_post_id: str | None = None
    error: str | None = None
    id: int | None = None
    created_at: str = field(default_factory=utc_now)
    updated_at: str = field(default_factory=utc_now)
