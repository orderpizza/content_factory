"""Persist one bounded provider collection per due source instance."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from dataclasses import asdict
from hashlib import sha256
from typing import Any
import json
import os
import socket
import sqlite3
from time import monotonic
from common.operation_log import emit
from common.diagnostics import safe_diagnostic

from .adapters import collect_source
from .configuration import canonical_json
from .models import CollectionResult, SourceCollectionError
from .normalization import canonical_title, parse_provider_time, utc_day_window
from .store import DetectionStore, utc_now


def _parse_time(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc)


def _slot(value: datetime, cadence_seconds: int) -> datetime:
    epoch = int(value.timestamp())
    return datetime.fromtimestamp(epoch - epoch % cadence_seconds, timezone.utc)


class DetectionCollector:
    WORKER_TYPE = "trend_source_collector"

    def __init__(self, store: DetectionStore, *, instance_id: str | None = None):
        self.store = store
        self.instance_id = instance_id or f"collector-{socket.gethostname().casefold()}"

    def run_due(
        self,
        *,
        now: datetime | None = None,
        source_ids: set[str] | None = None,
        force: bool = False,
    ) -> list[dict[str, Any]]:
        current = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
        outcomes: list[dict[str, Any]] = []
        sources = self.store.enabled_sources()
        for source in sources:
            if source_ids and source["stable_id"] not in source_ids:
                continue
            scheduled = _slot(current, int(source["cadence_seconds"]))
            if not force and not self._is_due(source, scheduled, current):
                continue
            started = monotonic()
            outcome = self._run_source(source, scheduled, current)
            outcomes.append(outcome)
            attempt = self.store.connection.execute('SELECT * FROM source_collection_attempts WHERE source_collection_attempt_id=?', (outcome['attempt_id'],)).fetchone()
            emit('detection', 'collection', worker=self.WORKER_TYPE, source_id=source['stable_id'],
                 scheduled_slot=attempt['scheduled_for'], attempt_id=outcome['attempt_id'],
                 status=outcome['status'], complete=bool(attempt['complete']),
                 item_count=outcome.get('items', outcome.get('items_received', 0)),
                 event_count=outcome.get('events', outcome.get('events_received', 0)),
                 claim_version=attempt['claim_version'], attempt_count=attempt['attempt_count'],
                 error_code=attempt['failure_category'], duration_ms=round((monotonic()-started)*1000))
        failed = [
            outcome for outcome in outcomes
            if outcome["status"] in {"failed", "retry_wait"}
        ]
        summary = f"processed {len(outcomes)} source attempt(s); failures={len(failed)}"
        self.store.heartbeat(
            self.WORKER_TYPE,
            self.instance_id,
            "failed" if failed else "idle",
            summary,
        )
        return outcomes

    def _is_due(
        self, source: sqlite3.Row, scheduled: datetime, current: datetime
    ) -> bool:
        row = self.store.connection.execute(
            "SELECT scheduled_for, status, next_attempt_at, lease_expires_at "
            "FROM source_collection_attempts "
            "WHERE source_instance_id=? ORDER BY scheduled_for DESC, "
            "source_collection_attempt_id DESC LIMIT 1",
            (source["detection_source_instance_id"],),
        ).fetchone()
        if row is None:
            return True
        if row["status"] == "pending":
            return True
        if row["status"] == "retry_wait" and row["next_attempt_at"]:
            return _parse_time(row["next_attempt_at"]) <= current
        if row["status"] in {"claimed", "running"} and row["lease_expires_at"]:
            return _parse_time(row["lease_expires_at"]) <= current
        return _parse_time(row["scheduled_for"]) < scheduled

    def _run_source(
        self, source: sqlite3.Row, scheduled: datetime, current: datetime
    ) -> dict[str, Any]:
        attempt_id = self._materialize_attempt(source, scheduled, current)
        row = self.store.connection.execute(
            "SELECT status FROM source_collection_attempts WHERE source_collection_attempt_id=?",
            (attempt_id,),
        ).fetchone()
        if row["status"] == "completed":
            return {"source": source["stable_id"], "attempt_id": attempt_id, "status": "already_completed"}
        reserve_quota = not (
            source["source_kind"] == "youtube_most_popular_v1"
            and not os.getenv(source["secret_ref"] or "")
        )
        claim_version, execution_id, claim_status = self._claim(
            source, attempt_id, current, reserve_quota=reserve_quota
        )
        if claim_status == "quota_limited":
            return {
                "source": source["stable_id"],
                "attempt_id": attempt_id,
                "status": "failed",
                "error": "local UTC-day quota ceiling reached",
            }
        if claim_version is None:
            if claim_status == "attempts_exhausted":
                return {
                    "source": source["stable_id"], "attempt_id": attempt_id,
                    "status": "failed", "error": "attempt limit exhausted after lease expiry",
                }
            return {"source": source["stable_id"], "attempt_id": attempt_id, "status": "not_claimed"}

        worker_run_id = self.store.start_worker_run(
            self.WORKER_TYPE, self.instance_id, "source_collection_attempt", attempt_id
        )
        self.store.heartbeat(
            self.WORKER_TYPE, self.instance_id, "working", f"collecting {source['stable_id']}",
            claim_type="source_collection_attempt", claim_id=attempt_id,
        )
        try:
            # The scheduled request, not today's wall clock, owns a report date.
            request = json.loads(self.store.connection.execute(
                "SELECT request_json FROM source_collection_attempts WHERE source_collection_attempt_id=?", (attempt_id,)
            ).fetchone()[0])
            frozen_source = dict(source)
            frozen_source["canonicalization_version"] = self.store.normalization_version(source["configuration_release_id"])
            frozen_source["collection_day"] = _parse_time(request["scheduled_for"]).date().isoformat()
            frozen_source["report_date"] = request.get("report_date") or (
                _parse_time(request["scheduled_for"]).date() - timedelta(days=1)
            ).isoformat()
            result = collect_source(frozen_source)
            if execution_id is not None:
                # Incomplete responses never enter scoring, but their bounded
                # parsed evidence survives independently for each execution.
                evidence = {"items": [asdict(item) for item in result.items],
                            "events": [{**asdict(event), "reason": safe_diagnostic(event.reason)} for event in result.events],
                            "failure_category": result.failure_category,
                            "failure_detail": safe_diagnostic(result.failure_detail) if result.failure_detail else None}
                with self.store.connection:
                    self.store.connection.execute(
                        "INSERT INTO source_execution_evidence(source_request_execution_id,complete,response_hash,evidence_json,created_at) VALUES (?,?,?,?,?)",
                        (execution_id, int(result.complete), result.response_hash, canonical_json(evidence), utc_now()),
                    )
            if not result.complete:
                category = result.failure_category or "incomplete_response"
                detail = safe_diagnostic(result.failure_detail or "provider response was incomplete")
                status = self._finalize_failure(
                    source, attempt_id, claim_version, category, detail
                )
                self._finish_request_execution(
                    execution_id, "failed", category=category, detail=detail
                )
                self.store.finish_worker_run(worker_run_id, status, error=detail)
                return {
                    "source": source["stable_id"], "attempt_id": attempt_id,
                    "status": status, "items_received": len(result.items),
                    "events_received": len(result.events), "error": detail,
                }
            self._finalize_success(source, attempt_id, claim_version, current, result)
            self._finish_request_execution(execution_id, "succeeded")
            status = "completed"
            summary = f"{source['stable_id']}: {len(result.items)} item(s), complete=true"
            self.store.finish_worker_run(worker_run_id, status, summary=summary)
            return {
                "source": source["stable_id"], "attempt_id": attempt_id,
                "status": status, "items": len(result.items), "events": len(result.events),
            }
        except SourceCollectionError as error:
            status = self._finalize_failure(
                source, attempt_id, claim_version, error.category, error.detail
            )
            self._finish_request_execution(
                execution_id, "failed", category=error.category, detail=error.detail
            )
            self.store.finish_worker_run(worker_run_id, status, error=error.detail)
            return {"source": source["stable_id"], "attempt_id": attempt_id, "status": status, "error": error.detail}
        except Exception as error:  # converted to bounded safe state at this boundary
            detail = f"unexpected collector error ({type(error).__name__})"
            status = self._finalize_failure(
                source, attempt_id, claim_version, "unexpected_error", detail
            )
            self._finish_request_execution(
                execution_id, "failed", category="unexpected_error", detail=detail
            )
            self.store.finish_worker_run(worker_run_id, status, error=detail)
            return {"source": source["stable_id"], "attempt_id": attempt_id, "status": status, "error": detail}

    def _materialize_attempt(
        self, source: sqlite3.Row, scheduled: datetime, current: datetime
    ) -> int:
        release_id = int(source["configuration_release_id"])
        recoverable = self.store.connection.execute(
            "SELECT source_collection_attempt_id FROM source_collection_attempts "
            "WHERE source_instance_id=? AND configuration_release_id=? AND ("
            "status='pending' OR (status='retry_wait' AND next_attempt_at<=?) OR "
            "(status IN ('claimed','running') AND lease_expires_at<=?)) "
            "ORDER BY scheduled_for, source_collection_attempt_id LIMIT 1",
            (
                source["detection_source_instance_id"], release_id,
                current.isoformat(), current.isoformat(),
            ),
        ).fetchone()
        if recoverable is not None:
            return int(recoverable["source_collection_attempt_id"])
        request = {
            "source_stable_id": source["stable_id"],
            "source_kind": source["source_kind"],
            "scheduled_for": scheduled.isoformat(),
            "endpoint_url": source["endpoint_url"],
            "configuration_fingerprint": source["config_fingerprint"],
            "options": json.loads(source["config_json"])["options"],
        }
        if source["source_kind"] == "wikimedia_enwiki_pageviews_v1":
            request["report_date"] = (scheduled.date() - timedelta(days=1)).isoformat()
        request_json = canonical_json(request)
        request_hash = sha256(request_json.encode("utf-8")).hexdigest()
        try:
            with self.store.connection:
                cursor = self.store.connection.execute(
                    "INSERT INTO source_collection_attempts "
                    "(source_instance_id, configuration_release_id, scheduled_for, request_json, "
                    "request_hash, quota_units_reserved, status, attempt_limit, created_at) "
                    "VALUES (?, ?, ?, ?, ?, 0, 'pending', 3, ?)",
                    (
                        source["detection_source_instance_id"], release_id, scheduled.isoformat(),
                        request_json, request_hash, current.isoformat(),
                    ),
                )
                return int(cursor.lastrowid)
        except sqlite3.IntegrityError:
            row = self.store.connection.execute(
                "SELECT source_collection_attempt_id FROM source_collection_attempts "
                "WHERE source_instance_id=? AND scheduled_for=? AND configuration_release_id=?",
                (source["detection_source_instance_id"], scheduled.isoformat(), release_id),
            ).fetchone()
            if row is None:
                raise
            return int(row["source_collection_attempt_id"])

    def _claim(
        self,
        source: sqlite3.Row,
        attempt_id: int,
        current: datetime,
        *,
        reserve_quota: bool,
    ) -> tuple[int | None, int | None, str]:
        lease = (current + timedelta(minutes=10)).isoformat()
        self.store.connection.execute("BEGIN IMMEDIATE")
        with self.store.connection:
            quota_units = 0
            if source["source_kind"] == "youtube_most_popular_v1" and reserve_quota:
                quota_day = current.date().isoformat()
                used = int(self.store.connection.execute(
                    "SELECT COALESCE(SUM(e.quota_units), 0) FROM source_request_executions e "
                    "JOIN detection_source_instances s ON s.detection_source_instance_id=e.source_instance_id "
                    "WHERE s.stable_id=? AND e.quota_day=?",
                    (source["stable_id"], quota_day),
                ).fetchone()[0])
                quota_limit = int(source["quota_limit"])
                if used >= quota_limit:
                    cursor = self.store.connection.execute(
                        "UPDATE source_collection_attempts SET status='failed', "
                        "failure_category='quota_limited', failure_detail=?, completed_at=? "
                        "WHERE source_collection_attempt_id=? AND (status='pending' OR "
                        "(status='retry_wait' AND next_attempt_at<=?) OR "
                        "(status IN ('claimed','running') AND lease_expires_at<=?))",
                        (
                            "local UTC-day quota ceiling reached", current.isoformat(), attempt_id,
                            current.isoformat(), current.isoformat(),
                        ),
                    )
                    if cursor.rowcount == 1:
                        self._insert_terminal_health(
                            source, attempt_id, "quota_limited",
                            "local UTC-day quota ceiling reached", current,
                        )
                        return None, None, "quota_limited"
                    return None, None, "not_claimed"
                quota_units = 1
            cursor = self.store.connection.execute(
                "UPDATE source_collection_attempts SET status='claimed', claim_owner=?, "
                "claimed_at=?, lease_expires_at=?, claim_version=claim_version+1, "
                "attempt_count=attempt_count+1, "
                "quota_units_reserved=quota_units_reserved+? "
                "WHERE source_collection_attempt_id=? "
                "AND (status='pending' OR (status='retry_wait' AND next_attempt_at<=?) OR "
                "(status IN ('claimed','running') AND lease_expires_at<=?)) "
                "AND attempt_count < attempt_limit",
                (
                    self.instance_id, current.isoformat(), lease, quota_units, attempt_id,
                    current.isoformat(), current.isoformat(),
                ),
            )
            if cursor.rowcount != 1:
                exhausted = self.store.connection.execute(
                    "SELECT status, attempt_count, attempt_limit, lease_expires_at "
                    "FROM source_collection_attempts WHERE source_collection_attempt_id=?",
                    (attempt_id,),
                ).fetchone()
                lease_expired = (
                    exhausted["status"] in {"claimed", "running"}
                    and exhausted["lease_expires_at"] is not None
                    and _parse_time(exhausted["lease_expires_at"]) <= current
                )
                retry_due = (
                    exhausted["status"] in {"pending", "retry_wait"}
                )
                if (
                    int(exhausted["attempt_count"]) >= int(exhausted["attempt_limit"])
                    and (lease_expired or retry_due)
                ):
                    terminal = self.store.connection.execute(
                        "UPDATE source_collection_attempts SET status='failed', "
                        "failure_category='attempts_exhausted', failure_detail=?, completed_at=? "
                        "WHERE source_collection_attempt_id=? AND status=?",
                        (
                            "attempt limit exhausted after lease expiry", current.isoformat(),
                            attempt_id, exhausted["status"],
                        ),
                    )
                    if terminal.rowcount == 1:
                        self._insert_terminal_health(
                            source, attempt_id, "attempts_exhausted",
                            "attempt limit exhausted after lease expiry", current,
                        )
                        return None, None, "attempts_exhausted"
                return None, None, "not_claimed"
            row = self.store.connection.execute(
                "SELECT claim_version, attempt_count FROM source_collection_attempts "
                "WHERE source_collection_attempt_id=?",
                (attempt_id,),
            ).fetchone()
            version = int(row["claim_version"])
            execution_id = None
            if reserve_quota:
                execution_cursor = self.store.connection.execute(
                    "INSERT INTO source_request_executions "
                    "(source_collection_attempt_id, source_instance_id, request_ordinal, "
                    "quota_day, quota_units, status, reserved_at) "
                    "VALUES (?,?,?,?,?,'reserved',?)",
                    (
                        attempt_id, source["detection_source_instance_id"], row["attempt_count"],
                        current.date().isoformat(), quota_units, current.isoformat(),
                    ),
                )
                execution_id = int(execution_cursor.lastrowid)
            self.store.connection.execute(
                "UPDATE source_collection_attempts SET status='running' "
                "WHERE source_collection_attempt_id=? AND status='claimed' "
                "AND claim_owner=? AND claim_version=?",
                (attempt_id, self.instance_id, version),
            )
            return version, execution_id, "claimed"

    def _finish_request_execution(
        self,
        execution_id: int | None,
        status: str,
        *,
        category: str | None = None,
        detail: str | None = None,
    ) -> None:
        if execution_id is None:
            return
        with self.store.connection:
            self.store.connection.execute(
                "UPDATE source_request_executions SET status=?, completed_at=?, "
                "error_category=?, error_detail=? WHERE source_request_execution_id=? "
                "AND status='reserved'",
                (status, utc_now(), category, detail[:2000] if detail else None, execution_id),
            )

    def _finalize_success(
        self,
        source: sqlite3.Row,
        attempt_id: int,
        claim_version: int,
        collected_at: datetime,
        result: CollectionResult,
    ) -> None:
        window_start, window_end = utc_day_window(collected_at)
        normalization_version = self.store.normalization_version(source["configuration_release_id"])
        with self.store.connection:
            for event in result.events:
                self.store.connection.execute(
                    "INSERT INTO source_item_events "
                    "(source_collection_attempt_id, source_instance_id, source_ordinal, "
                    "source_item_key, disposition, reason, payload_hash, created_at) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        attempt_id, source["detection_source_instance_id"], event.source_ordinal,
                        event.source_item_key, event.disposition, safe_diagnostic(event.reason),
                        event.payload_hash, collected_at.isoformat(),
                    ),
                )
            for item in result.items:
                key = canonical_title(item.title, normalization_version)
                if not key:
                    continue
                if source["source_kind"] in {
                    "youtube_most_popular_v1", "hacker_news_top_stories_v1"
                }:
                    effective_text, time_status = collected_at.isoformat(), "collection_time_measurement"
                else:
                    effective_text, time_status = parse_provider_time(item.provider_time, collected_at)
                    if time_status == "provider_time_fallback":
                        first = self.store.connection.execute(
                            "SELECT MIN(o.collected_at) FROM trend_observations o JOIN detection_source_instances s "
                            "ON s.detection_source_instance_id=o.source_instance_id WHERE s.stable_id=? "
                            "AND s.source_kind=? AND o.source_item_key=?",
                            (source["stable_id"], source["source_kind"], item.source_item_key),
                        ).fetchone()[0]
                        effective_text = first or effective_text
                effective = _parse_time(effective_text)
                item_window_start, item_window_end = utc_day_window(effective)
                trend_id = self._upsert_trend(key, item.title, effective_text, item.payload, collected_at.isoformat(), normalization_version)
                payload = dict(item.payload)
                payload["provider_time_status"] = time_status
                activity_contributor = self._resolve_activity_contributor(
                    source, attempt_id, item.source_item_key, item.canonical_url,
                    key, item_window_start, item_window_end, collected_at,
                )
                self.store.connection.execute(
                    "INSERT INTO trend_observations "
                    "(source_collection_attempt_id, source_instance_id, trend_id, source_item_id, "
                    "source_item_key, canonical_url, provider_time, effective_observed_at, "
                    "collected_at, window_start, window_end, activity, rank, title, payload_json, "
                    "activity_contributor, created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (
                        attempt_id, source["detection_source_instance_id"], trend_id,
                        item.source_item_id, item.source_item_key, item.canonical_url,
                        item.provider_time, effective_text, collected_at.isoformat(),
                        item_window_start, item_window_end, item.activity, item.rank, item.title,
                        canonical_json(payload), activity_contributor, collected_at.isoformat(),
                    ),
                )
            status_reason = "complete collection" if result.complete else (result.failure_detail or "incomplete collection")
            health = "healthy" if result.complete else "degraded"
            self.store.connection.execute(
                "INSERT INTO source_health "
                "(source_instance_id, source_collection_attempt_id, window_start, window_end, "
                "item_count, complete, classification, reason, fallback_mode, latency_ms, "
                "error_category, created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    source["detection_source_instance_id"], attempt_id, window_start, window_end,
                    len(result.items), int(result.complete), health, status_reason[:2000],
                    None, result.latency_ms, result.failure_category, collected_at.isoformat(),
                ),
            )
            cursor = self.store.connection.execute(
                "UPDATE source_collection_attempts SET status='completed', provider_time=?, "
                "collected_at=?, response_hash=?, item_count=?, complete=?, completed_at=?, "
                "next_attempt_at=NULL, failure_category=?, failure_detail=? "
                "WHERE source_collection_attempt_id=? AND status='running' "
                "AND claim_owner=? AND claim_version=?",
                (
                    result.provider_time, collected_at.isoformat(), result.response_hash,
                    len(result.items), int(result.complete), utc_now(), result.failure_category,
                    result.failure_detail, attempt_id, self.instance_id, claim_version,
                ),
            )
            if cursor.rowcount != 1:
                raise RuntimeError("Collection claim was lost before finalization")

    def _resolve_activity_contributor(
        self,
        source: sqlite3.Row,
        attempt_id: int,
        source_item_key: str,
        canonical_url: str | None,
        canonical_key: str,
        window_start: str,
        window_end: str,
        now: datetime,
    ) -> int:
        if source["source_kind"] == "publisher_feed_collector_v1":
            identity_clause = (
                "((? IS NOT NULL AND o.canonical_url=?) OR "
                "(? IS NULL AND o.canonical_url IS NULL AND t.canonical_key=?))"
            )
            identity_values: tuple[Any, ...] = (
                canonical_url, canonical_url, canonical_url, canonical_key,
            )
        else:
            identity_clause = "o.source_item_key=?"
            identity_values = (source_item_key,)
        existing = self.store.connection.execute(
            "SELECT o.trend_observation_id, o.source_collection_attempt_id, "
            "o.source_instance_id, o.source_item_key FROM trend_observations o "
            "JOIN detection_source_instances s "
            "ON s.detection_source_instance_id=o.source_instance_id "
            "JOIN trends t ON t.trend_id=o.trend_id "
            "WHERE s.configuration_release_id=? AND s.independence_group=? "
            "AND o.source_instance_id<>? AND o.window_start=? AND o.window_end=? "
            "AND o.activity_contributor=1 AND " + identity_clause,
            (
                source["configuration_release_id"], source["independence_group"],
                source["detection_source_instance_id"], window_start, window_end,
                *identity_values,
            ),
        ).fetchall()
        if not existing:
            return 1
        current_pair = (int(source["detection_source_instance_id"]), source_item_key)
        winning_pair = min(
            [current_pair]
            + [
                (int(row["source_instance_id"]), str(row["source_item_key"]))
                for row in existing
            ]
        )
        if current_pair != winning_pair:
            self.store.connection.execute(
                "INSERT INTO source_item_events "
                "(source_collection_attempt_id, source_instance_id, source_item_key, "
                "disposition, reason, created_at) "
                "VALUES (?,?,?,'duplicate_suppressed',?,?)",
                (
                    attempt_id, source["detection_source_instance_id"], source_item_key,
                    "same independence-group item already has the deterministic contributor",
                    now.isoformat(),
                ),
            )
            return 0
        # Completed observations/events are immutable. Scout resolves the winner
        # from its own frozen attempt set and records that decision in membership.
        return 1

    def _upsert_trend(
        self,
        key: str,
        title: str,
        observed_at: str,
        payload: dict[str, Any],
        updated_at: str,
        normalization_version: str = "canonicalization_v2",
    ) -> int:
        self.store.connection.execute(
            "INSERT INTO trends "
            "(canonical_key, canonicalization_version, canonical_subject, first_observed_at, "
            "last_observed_at, current_metadata_json, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?) "
            "ON CONFLICT(canonical_key, canonicalization_version) DO UPDATE SET "
            "canonical_subject=excluded.canonical_subject, "
            "last_observed_at=MAX(trends.last_observed_at, excluded.last_observed_at), "
            "current_metadata_json=excluded.current_metadata_json, updated_at=excluded.updated_at",
            (key, normalization_version, title, observed_at, observed_at, canonical_json(payload), updated_at, updated_at),
        )
        row = self.store.connection.execute(
            "SELECT trend_id FROM trends WHERE canonical_key=? AND canonicalization_version=?",
            (key, normalization_version),
        ).fetchone()
        return int(row["trend_id"])

    def _finalize_failure(
        self,
        source: sqlite3.Row,
        attempt_id: int,
        claim_version: int,
        category: str,
        detail: str,
    ) -> str:
        detail = safe_diagnostic(detail)
        now = datetime.now(timezone.utc)
        row = self.store.connection.execute(
            "SELECT attempt_count, attempt_limit FROM source_collection_attempts "
            "WHERE source_collection_attempt_id=?",
            (attempt_id,),
        ).fetchone()
        retry = (
            category
            not in {
                "configuration_missing",
                "unsafe_endpoint",
                "adapter_missing",
                "quota_limited",
            }
            and int(row["attempt_count"]) < int(row["attempt_limit"])
        )
        status = "retry_wait" if retry else "failed"
        next_attempt = (now + timedelta(seconds=30 if int(row["attempt_count"]) == 1 else 300)).isoformat() if retry else None
        with self.store.connection:
            cursor = self.store.connection.execute(
                "UPDATE source_collection_attempts SET status=?, next_attempt_at=?, "
                "failure_category=?, failure_detail=?, completed_at=? "
                "WHERE source_collection_attempt_id=? AND status='running' "
                "AND claim_owner=? AND claim_version=?",
                (
                    status, next_attempt, category, detail[:2000], utc_now() if not retry else None,
                    attempt_id, self.instance_id, claim_version,
                ),
            )
            if cursor.rowcount != 1:
                raise RuntimeError("Collection claim was lost before failure finalization")
            if not retry:
                self._insert_terminal_health(source, attempt_id, category, detail, now)
        return status

    def _insert_terminal_health(
        self,
        source: sqlite3.Row,
        attempt_id: int,
        category: str,
        detail: str,
        now: datetime,
    ) -> None:
        classification = "quota_limited" if category == "quota_limited" else "failed"
        self.store.connection.execute(
            "INSERT OR IGNORE INTO source_health "
            "(source_instance_id, source_collection_attempt_id, item_count, complete, "
            "classification, reason, error_category, created_at) "
            "VALUES (?,?,0,0,?,?,?,?)",
            (
                source["detection_source_instance_id"], attempt_id, classification,
                detail[:2000], category, now.isoformat(),
            ),
        )
