"""Typed source-adapter outputs; no provider object crosses this boundary."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any
from common.diagnostics import safe_diagnostic


@dataclass(frozen=True)
class CollectedItem:
    source_item_key: str
    title: str
    activity: float
    rank: int | None = None
    source_item_id: str | None = None
    canonical_url: str | None = None
    provider_time: str | None = None
    payload: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ItemEvent:
    disposition: str
    reason: str
    source_ordinal: int | None = None
    source_item_key: str | None = None
    payload_hash: str | None = None


@dataclass(frozen=True)
class CollectionResult:
    items: tuple[CollectedItem, ...]
    events: tuple[ItemEvent, ...]
    complete: bool
    response_hash: str
    latency_ms: int
    provider_time: str | None = None
    failure_category: str | None = None
    failure_detail: str | None = None


class SourceCollectionError(RuntimeError):
    def __init__(self, category: str, detail: str):
        detail = safe_diagnostic(detail)
        super().__init__(detail)
        self.category = category
        self.detail = detail[:2000]
