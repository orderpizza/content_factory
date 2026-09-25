"""Freeze source evidence, calculate versioned attention, and persist the shortlist."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from hashlib import sha256
from typing import Any
import json
import socket
import sqlite3
from time import monotonic
from common.operation_log import emit
from common.diagnostics import safe_diagnostic
from common.timestamps import parse_timestamp, serialize_timestamp, utc_datetime_now

from .configuration import canonical_json
from .store import DetectionStore, utc_now
from .semantic import LocalEmbeddingEncoder, freeze_resolution


def _parse_time(value: str) -> datetime:
    return parse_timestamp(value)


def _evaluation_slot(value: datetime) -> datetime:
    epoch = int(value.timestamp())
    return datetime.fromtimestamp(epoch - epoch % 900, timezone.utc)


class DetectionScout:
    WORKER_TYPE = "trend_scout_shortlist"

    def __init__(self, store: DetectionStore, *, instance_id: str | None = None, encoder=None):
        self.store = store
        self.instance_id = instance_id or f"scout-{socket.gethostname().casefold()}"
        self.encoder = encoder if encoder is not None else LocalEmbeddingEncoder()

    def run(self, *, now: datetime | None = None) -> dict[str, Any]:
        started = monotonic()
        frozen_at = (now or utc_datetime_now()).astimezone(timezone.utc).replace(microsecond=0)
        slot = _evaluation_slot(frozen_at)
        release = self.store.active_release()
        release_id = int(release["configuration_release_id"])
        manifest = json.loads(release["manifest_json"])
        from .configuration import validate_manifest
        validate_manifest(manifest)
        run_id = self._materialize_run(slot, release_id, frozen_at)
        row = self.store.connection.execute(
            "SELECT status, aggregate_counts_json FROM scout_evaluation_runs "
            "WHERE scout_evaluation_run_id=?",
            (run_id,),
        ).fetchone()
        if row["status"] == "completed":
            counts = json.loads(row["aggregate_counts_json"])
            self.store.heartbeat(
                self.WORKER_TYPE, self.instance_id, "idle",
                f"slot already completed; {counts.get('candidate_count', 0)} cluster(s)",
            )
            return {
                "run_id": run_id,
                "status": "already_completed",
                **counts,
            }
        claim_version = self._claim(run_id, frozen_at)
        if claim_version is None:
            current_status = self.store.connection.execute(
                "SELECT status FROM scout_evaluation_runs WHERE scout_evaluation_run_id=?",
                (run_id,),
            ).fetchone()["status"]
            self.store.heartbeat(
                self.WORKER_TYPE, self.instance_id,
                "failed" if current_status == "failed" else "idle",
                "evaluation attempt limit exhausted"
                if current_status == "failed"
                else "evaluation exists but is not currently claimable",
            )
            return {
                "run_id": run_id,
                "status": "failed" if current_status == "failed" else "not_claimed",
            }

        worker_run_id = self.store.start_worker_run(
            self.WORKER_TYPE, self.instance_id, "scout_evaluation_run", run_id
        )
        self.store.heartbeat(
            self.WORKER_TYPE, self.instance_id, "working", f"evaluating slot {serialize_timestamp(slot)}",
            claim_type="scout_evaluation_run", claim_id=run_id,
        )
        try:
            attempt_ids = self._freeze_inputs(run_id, release_id, frozen_at, claim_version)
            evaluation_time = _parse_time(self.store.connection.execute(
                "SELECT input_frozen_at FROM scout_evaluation_runs WHERE scout_evaluation_run_id=?",
                (run_id,),
            ).fetchone()["input_frozen_at"])
            freeze_resolution(self.store.connection, run_id,
                              manifest["components"]["detection"]["semantic_resolution"], self.encoder,
                              owner=self.instance_id, claim_version=claim_version, execution_time=frozen_at)
            result = self._evaluate(run_id, release_id, manifest, evaluation_time, attempt_ids)
            # Selection budgets use this execution's time, not the older input clock.
            self._finalize(run_id, claim_version, result, manifest, frozen_at)
            summary = f"{result['candidate_count']} cluster(s), {result['selected_count']} selected"
            self.store.finish_worker_run(worker_run_id, "completed", summary=summary)
            self.store.heartbeat(self.WORKER_TYPE, self.instance_id, "idle", summary)
            public_result = {
                key: value for key, value in result.items() if key != "candidates"
            }
            emit('detection', 'scout', worker=self.WORKER_TYPE, evaluation_id=run_id,
                 claim_version=claim_version, scheduled_slot=serialize_timestamp(slot), status='completed',
                 candidate_count=result['candidate_count'], selected_count=result['selected_count'],
                 duration_ms=round((monotonic()-started)*1000))
            return {"run_id": run_id, "status": "completed", **public_result}
        except Exception as error:
            emit('detection', 'scout', evaluation_id=run_id, status='failed', error_type=type(error).__name__,
                 duration_ms=round((monotonic()-started)*1000))
            detail = f"unexpected Scout error ({type(error).__name__})"
            self._fail(run_id, claim_version, detail)
            self.store.finish_worker_run(worker_run_id, "failed", error=detail)
            self.store.heartbeat(self.WORKER_TYPE, self.instance_id, "failed", detail)
            raise

    def _materialize_run(self, slot: datetime, release_id: int, now: datetime) -> int:
        recoverable = self.store.connection.execute(
            "SELECT scout_evaluation_run_id FROM scout_evaluation_runs "
            "WHERE configuration_release_id=? AND (status='pending' OR "
            "(status='retry_wait' AND next_attempt_at<=?) OR "
            "(status IN ('claimed','running') AND lease_expires_at<=?)) "
            "ORDER BY evaluation_slot_start, scout_evaluation_run_id LIMIT 1",
            (release_id, serialize_timestamp(now), serialize_timestamp(now)),
        ).fetchone()
        if recoverable is not None:
            return int(recoverable["scout_evaluation_run_id"])
        try:
            with self.store.connection:
                cursor = self.store.connection.execute(
                    "INSERT INTO scout_evaluation_runs "
                    "(evaluation_slot_start, configuration_release_id, aggregate_counts_json, "
                    "status, attempt_limit, created_at) VALUES (?, ?, '{}', 'pending', 3, ?)",
                    (serialize_timestamp(slot), release_id, serialize_timestamp(now)),
                )
                return int(cursor.lastrowid)
        except sqlite3.IntegrityError:
            row = self.store.connection.execute(
                "SELECT scout_evaluation_run_id FROM scout_evaluation_runs "
                "WHERE evaluation_slot_start=? AND configuration_release_id=?",
                (serialize_timestamp(slot), release_id),
            ).fetchone()
            if row is None:
                raise
            return int(row["scout_evaluation_run_id"])

    def _claim(self, run_id: int, now: datetime) -> int | None:
        with self.store.connection:
            cursor = self.store.connection.execute(
                "UPDATE scout_evaluation_runs SET status='claimed', claim_owner=?, claimed_at=?, "
                "lease_expires_at=?, claim_version=claim_version+1, attempt_count=attempt_count+1 "
                "WHERE scout_evaluation_run_id=? AND (status='pending' OR "
                "(status='retry_wait' AND next_attempt_at<=?) OR "
                "(status IN ('claimed','running') AND lease_expires_at<=?)) "
                "AND attempt_count<attempt_limit",
                (
                    self.instance_id, serialize_timestamp(now), serialize_timestamp(now + timedelta(minutes=10)),
                    run_id, serialize_timestamp(now), serialize_timestamp(now),
                ),
            )
            if cursor.rowcount != 1:
                exhausted = self.store.connection.execute(
                    "SELECT status, attempt_count, attempt_limit, lease_expires_at "
                    "FROM scout_evaluation_runs WHERE scout_evaluation_run_id=?",
                    (run_id,),
                ).fetchone()
                lease_expired = (
                    exhausted["status"] in {"claimed", "running"}
                    and exhausted["lease_expires_at"] is not None
                    and _parse_time(exhausted["lease_expires_at"]) <= now
                )
                retry_due = exhausted["status"] in {"pending", "retry_wait"}
                if (
                    int(exhausted["attempt_count"]) >= int(exhausted["attempt_limit"])
                    and (lease_expired or retry_due)
                ):
                    self.store.connection.execute(
                        "UPDATE scout_evaluation_runs SET status='failed', "
                        "failure_category='attempts_exhausted', failure_detail=?, completed_at=? "
                        "WHERE scout_evaluation_run_id=? AND status=?",
                        (
                            "attempt limit exhausted after lease expiry", serialize_timestamp(now),
                            run_id, exhausted["status"],
                        ),
                    )
                return None
            version = int(self.store.connection.execute(
                "SELECT claim_version FROM scout_evaluation_runs WHERE scout_evaluation_run_id=?",
                (run_id,),
            ).fetchone()["claim_version"])
            self.store.connection.execute(
                "UPDATE scout_evaluation_runs SET status='running' "
                "WHERE scout_evaluation_run_id=? AND claim_owner=? AND claim_version=?",
                (run_id, self.instance_id, version),
            )
            return version

    def _freeze_inputs(
        self, run_id: int, release_id: int, frozen_at: datetime, claim_version: int
    ) -> list[int]:
        with self.store.connection:
            # Acquire the write lock and validate ownership before reading/writing
            # the freeze boundary. A completed empty input still has an input_hash.
            claimed = self.store.connection.execute(
                "UPDATE scout_evaluation_runs "
                "SET input_frozen_at=COALESCE(input_frozen_at,?) "
                "WHERE scout_evaluation_run_id=? AND configuration_release_id=? "
                "AND status='running' AND claim_owner=? AND claim_version=?",
                (serialize_timestamp(frozen_at), run_id, release_id, self.instance_id, claim_version),
            )
            if claimed.rowcount != 1:
                raise RuntimeError("Scout claim was lost before freezing inputs")
            frozen = self.store.connection.execute(
                "SELECT input_hash FROM scout_evaluation_runs WHERE scout_evaluation_run_id=?",
                (run_id,),
            ).fetchone()
            if frozen["input_hash"] is not None:
                return [int(row["source_collection_attempt_id"]) for row in self.store.connection.execute(
                    "SELECT source_collection_attempt_id FROM scout_evaluation_attempts "
                    "WHERE scout_evaluation_run_id=? ORDER BY scout_evaluation_attempt_id",
                    (run_id,),
                )]
            from .hybrid import freeze
            return freeze(self.store.connection, run_id, release_id, frozen_at)

    def _evaluate(
        self,
        run_id: int,
        release_id: int,
        manifest: dict[str, Any],
        frozen_at: datetime,
        attempt_ids: list[int],
    ) -> dict[str, Any]:
        from .hybrid import evaluate
        return evaluate(self.store.connection, run_id, release_id, manifest)

    def _workflow_catalog(self) -> list[dict[str, Any]]:
        from workflow.catalog import read_catalog
        production = self.store.connection.execute("SELECT 1 FROM production_configurations LIMIT 1").fetchone()
        return read_catalog(self.store.connection, "production" if production else "fixture")

    def _create_trend_determination_handoff(
        self,
        *,
        candidate: dict[str, Any],
        candidate_id: int,
        run_id: int,
        snapshot_id: int,
        thread_id: int,
        frozen_at: datetime,
    ) -> None:
        """Create the source-backed brief and direct Determination handoff."""
        subject = str(candidate["canonical_subject"]).strip()
        normalized = " ".join(subject.casefold().split())
        coverage_identity = (
            f"coverage:coverage_normalization_v2:trend_topic:{normalized}"
        )
        collision = self.store.connection.execute(
            "SELECT thread_id FROM content_threads "
            "WHERE coverage_identity=? AND thread_id<>?",
            (coverage_identity, thread_id),
        ).fetchone()
        if collision is not None:
            raise RuntimeError(
                "selected trend conflicts with an existing editorial coverage thread"
            )
        self.store.connection.execute(
            "UPDATE content_threads SET coverage_identity=?, updated_at=?, "
            "row_version=row_version+1 WHERE thread_id=?",
            (coverage_identity, serialize_timestamp(frozen_at), thread_id),
        )

        member_index = {member['trend_observation_id']: member for member in candidate['members']}
        source_snapshot = {
            "kind": "selected_trend",
            "detection_run_id": run_id,
            "topic_snapshot_id": snapshot_id,
            "candidate": {
                "candidate_id": candidate_id,
                "opportunity_identity": candidate["opportunity_identity"],
                "topic": subject,
                "score": candidate["score"],
                "evidence_fingerprint": candidate["evidence_fingerprint"],
            },
            "evidence": [
                {**entry,
                 "canonical_url": member_index[entry['observation_id']].get('canonical_url'),
                 "evidence_time": member_index[entry['observation_id']].get('evidence_time')}
                for entry in candidate["evidence"]
            ],
        }
        brief = {
            "editorial_goal": f"Assess whether {subject} merits useful content.",
            "topic": subject,
            "coverage_kind": "trend_topic",
            "canonical_target": subject,
            "revision_scope": "whole_brief",
            "audience": "general audience",
            "desired_outcome": "inform",
            "constraints": {"origin": "detected_trend"},
            "source_context": (
                "This source-backed brief was created from an Opportunity after "
                "complete Detection Selection; the frozen Cluster evidence is attached separately."
            ),
            "open_questions": [],
        }
        revision = self.store.connection.execute(
            "INSERT INTO brief_revisions "
            "(thread_id, revision_number, brief_json, source_snapshot_json, "
            "revision_reason, created_by, created_at) "
            "VALUES (?, 1, ?, ?, 'initial', 'system', ?) ",
            (
                thread_id,
                canonical_json(brief),
                canonical_json(source_snapshot),
                serialize_timestamp(frozen_at),
            ),
        )
        revision_id = int(revision.lastrowid)
        request_snapshot = {
            "brief": brief,
            "source_context": source_snapshot,
            "catalog": self._workflow_catalog(),
            "catalog_version": "domain_pipeline_catalog_v1",
            "routing_policy_version": "determination_policy_v3",
        }
        self.store.connection.execute(
            "INSERT INTO determination_requests "
            "(revision_id, input_snapshot_json, input_fingerprint, status, "
            "attempt_limit, created_at) VALUES (?, ?, ?, 'pending', 3, ?)",
            (
                revision_id,
                canonical_json(request_snapshot),
                sha256(canonical_json(request_snapshot).encode("utf-8")).hexdigest(),
                serialize_timestamp(frozen_at),
            ),
        )

    def _finalize(
        self,
        run_id: int,
        claim_version: int,
        result: dict[str, Any],
        manifest: dict[str, Any],
        frozen_at: datetime,
    ) -> None:
        policy = manifest["components"]["detection"]["shortlist"]
        formula_version = manifest["components"]["detection"]["score_formula_version"]
        normalization_version = manifest["components"]["detection"]["canonicalization_version"]
        six_hours = serialize_timestamp(frozen_at - timedelta(hours=6))
        day = serialize_timestamp(frozen_at - timedelta(hours=24))
        with self.store.connection:
            for kind, population in result.get("prominence_populations", {}).items():
                encoded_population = canonical_json(population)
                self.store.connection.execute(
                    "INSERT INTO scout_prominence_populations(scout_evaluation_run_id,source_kind,population_json,population_hash,created_at) VALUES (?,?,?,?,?)",
                    (run_id, kind, encoded_population, sha256(encoded_population.encode()).hexdigest(), serialize_timestamp(frozen_at)),
                )
            selected_6h = int(self.store.connection.execute(
                "SELECT COUNT(*) FROM trend_candidates WHERE selected_at>=?", (six_hours,)
            ).fetchone()[0])
            selected_24h = int(self.store.connection.execute(
                "SELECT COUNT(*) FROM trend_candidates WHERE selected_at>=?", (day,)
            ).fetchone()[0])
            selected_count = 0
            for rank, candidate in enumerate(result["candidates"], start=1):
                self.store.connection.execute(
                    "INSERT INTO topic_snapshots "
                    "(scout_evaluation_run_id, cluster_key, opportunity_identity, canonical_subject, "
                    "score, score_breakdown_json, evidence_snapshot_json, evidence_fingerprint, "
                    "score_formula_version, canonicalization_version, created_at) "
                    "VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                    (
                        run_id, candidate["cluster_key"], candidate["opportunity_identity"],
                        candidate["canonical_subject"], candidate["score"],
                        canonical_json(candidate["breakdown"]), candidate["evidence_json"],
                        candidate["evidence_fingerprint"], formula_version, normalization_version,
                        serialize_timestamp(frozen_at),
                    ),
                )
                snapshot_id = int(self.store.connection.execute("SELECT last_insert_rowid()").fetchone()[0])
                existing = self.store.connection.execute(
                    "SELECT * FROM trend_candidates WHERE opportunity_identity=?",
                    (candidate["opportunity_identity"],),
                ).fetchone()
                desired_status = "eligible" if candidate["eligible"] else "observed"
                reason = candidate["eligibility_reason"]
                for key in candidate.get("lexical_keys", []):
                    owner = self.store.connection.execute(
                        "SELECT DISTINCT c.selected_thread_id FROM trend_candidates c "
                        "JOIN candidate_observation_memberships m ON m.trend_candidate_id=c.trend_candidate_id "
                        "JOIN trend_observations o ON o.trend_observation_id=m.trend_observation_id "
                        "JOIN trends t ON t.trend_id=o.trend_id "
                        "WHERE t.canonical_key=? AND c.selected_thread_id IS NOT NULL ORDER BY c.selected_thread_id LIMIT 1",
                        (key,),
                    ).fetchone()
                    if owner and (not existing or existing["selected_thread_id"] != owner[0]):
                        desired_status, reason = "observed", "resolved_event_already_owned"
                if existing and existing["selected_thread_id"] is not None:
                    desired_status = existing["eligibility_status"]
                    reason = existing["eligibility_reason"]
                if existing:
                    self.store.connection.execute(
                        "UPDATE trend_candidates SET cluster_key=?, canonical_subject=?, "
                        "latest_topic_snapshot_id=?, latest_evidence_fingerprint=?, score=?, "
                        "score_breakdown_json=?, score_formula_version=?, "
                        "canonicalization_version=?, eligibility_status=?, "
                        "eligibility_reason=?, rank=?, last_seen_at=?, updated_at=? "
                        "WHERE trend_candidate_id=?",
                        (
                            candidate["cluster_key"], candidate["canonical_subject"], snapshot_id,
                            candidate["evidence_fingerprint"], candidate["score"],
                            canonical_json(candidate["breakdown"]), formula_version, normalization_version, desired_status, reason, rank,
                            candidate.get("last_seen_at", serialize_timestamp(frozen_at)), serialize_timestamp(frozen_at), existing["trend_candidate_id"],
                        ),
                    )
                    candidate_id = int(existing["trend_candidate_id"])
                else:
                    cursor = self.store.connection.execute(
                        "INSERT INTO trend_candidates "
                        "(opportunity_identity, cluster_key, canonical_subject, latest_topic_snapshot_id, "
                        "latest_evidence_fingerprint, score, score_breakdown_json, score_formula_version, "
                        "canonicalization_version, eligibility_status, eligibility_reason, rank, "
                        "first_seen_at, last_seen_at, created_at, updated_at) "
                        "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                        (
                            candidate["opportunity_identity"], candidate["cluster_key"],
                            candidate["canonical_subject"], snapshot_id, candidate["evidence_fingerprint"],
                            candidate["score"], canonical_json(candidate["breakdown"]), formula_version,
                            normalization_version, desired_status, reason, rank, serialize_timestamp(frozen_at),
                            candidate.get("last_seen_at", serialize_timestamp(frozen_at)), serialize_timestamp(frozen_at), serialize_timestamp(frozen_at),
                        ),
                    )
                    candidate_id = int(cursor.lastrowid)
                for ordinal, member in enumerate(candidate["members"], start=1):
                    self.store.connection.execute(
                        "INSERT INTO candidate_observation_memberships "
                        "(trend_candidate_id, topic_snapshot_id, trend_observation_id, ordinal, "
                        "contribution, snapshot_json, created_at) VALUES (?,?,?,?,?,?,?)",
                        (
                            candidate_id, snapshot_id, member["trend_observation_id"], ordinal,
                            float(member["activity"]) if member["activity_contributor"] and member["trend_observation_id"] not in candidate["breakdown"].get("excluded_observation_ids", []) else 0.0, canonical_json({
                                "source": member["stable_id"], "activity": member["activity"],
                                "rank": member["rank"], "title": member["title"],
                                "source_item_key": member["source_item_key"], "canonical_url": member["canonical_url"],
                                "effective_observed_at": member["effective_observed_at"], "collected_at": member["collected_at"],
                                "window_start": member["window_start"], "window_end": member["window_end"],
                            }), serialize_timestamp(frozen_at),
                        ),
                    )
                can_select = (
                    desired_status == "eligible"
                    and selected_6h < policy["max_selected_6h"]
                    and selected_24h < policy["max_selected_24h"]
                )
                if can_select:
                    thread_cursor = self.store.connection.execute(
                        "INSERT INTO content_threads "
                        "(origin, seed_candidate_id, status, created_at, updated_at) "
                        "VALUES ('trend', ?, 'open', ?, ?)",
                        (candidate_id, serialize_timestamp(frozen_at), serialize_timestamp(frozen_at)),
                    )
                    thread_id = int(thread_cursor.lastrowid)
                    self._create_trend_determination_handoff(
                        candidate=candidate,
                        candidate_id=candidate_id,
                        run_id=run_id,
                        snapshot_id=snapshot_id,
                        thread_id=thread_id,
                        frozen_at=frozen_at,
                    )
                    self.store.connection.execute(
                        "UPDATE trend_candidates SET eligibility_status='selected', "
                        "eligibility_reason=?, selected_at=?, "
                        "selected_thread_id=?, updated_at=? WHERE trend_candidate_id=?",
                        (f"selected_by_{policy['policy_version']}", serialize_timestamp(frozen_at), thread_id, serialize_timestamp(frozen_at), candidate_id),
                    )
                    selected_count += 1
                    selected_6h += 1
                    selected_24h += 1
                elif desired_status == "eligible":
                    self.store.connection.execute(
                        "UPDATE trend_candidates SET eligibility_status='deferred_by_budget', "
                        "eligibility_reason='selection_budget_exhausted', updated_at=? "
                        "WHERE trend_candidate_id=?",
                        (serialize_timestamp(frozen_at), candidate_id),
                    )
            result["selected_count"] = selected_count
            counts = canonical_json({
                "candidate_count": result["candidate_count"], "selected_count": selected_count,
            })
            cursor = self.store.connection.execute(
                "UPDATE scout_evaluation_runs SET status='completed', aggregate_counts_json=?, "
                "next_attempt_at=NULL, failure_category=NULL, failure_detail=NULL, completed_at=? "
                "WHERE scout_evaluation_run_id=? AND status='running' "
                "AND claim_owner=? AND claim_version=?",
                (counts, utc_now(), run_id, self.instance_id, claim_version),
            )
            if cursor.rowcount != 1:
                raise RuntimeError("Scout claim was lost before finalization")

    def _fail(self, run_id: int, claim_version: int, detail: str) -> None:
        detail = safe_diagnostic(detail)
        row = self.store.connection.execute(
            "SELECT attempt_count, attempt_limit FROM scout_evaluation_runs "
            "WHERE scout_evaluation_run_id=?",
            (run_id,),
        ).fetchone()
        retry = int(row["attempt_count"]) < int(row["attempt_limit"])
        delay = 30 if int(row["attempt_count"]) == 1 else 300
        next_attempt = (
            utc_datetime_now() + timedelta(seconds=delay)
        ) if retry else None
        next_attempt = serialize_timestamp(next_attempt) if next_attempt else None
        with self.store.connection:
            self.store.connection.execute(
                "UPDATE scout_evaluation_runs SET status=?, next_attempt_at=?, "
                "failure_category='evaluation_failed', failure_detail=?, completed_at=? "
                "WHERE scout_evaluation_run_id=? AND status='running' "
                "AND claim_owner=? AND claim_version=?",
                (
                    "retry_wait" if retry else "failed", next_attempt, detail,
                    None if retry else utc_now(), run_id, self.instance_id, claim_version,
                ),
            )
