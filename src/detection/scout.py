"""Freeze source evidence, calculate attention_v1, and persist the shortlist."""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timedelta, timezone
from hashlib import sha256
from math import log2
from statistics import median
from typing import Any
import json
import socket
import sqlite3
from common.diagnostics import safe_diagnostic

from .configuration import canonical_json
from .store import DetectionStore, utc_now


def _parse_time(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc)


def _evaluation_slot(value: datetime) -> datetime:
    epoch = int(value.timestamp())
    return datetime.fromtimestamp(epoch - epoch % 900, timezone.utc)


def _clamp(value: float, lower: float = 0.0, upper: float = 1.0) -> float:
    return max(lower, min(upper, value))


class DetectionScout:
    WORKER_TYPE = "trend_scout_shortlist"

    def __init__(self, store: DetectionStore, *, instance_id: str | None = None):
        self.store = store
        self.instance_id = instance_id or f"scout-{socket.gethostname().casefold()}"

    def run(self, *, now: datetime | None = None) -> dict[str, Any]:
        frozen_at = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
        slot = _evaluation_slot(frozen_at)
        release = self.store.active_release()
        release_id = int(release["configuration_release_id"])
        manifest = json.loads(release["manifest_json"])
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
                f"slot already completed; {counts.get('candidate_count', 0)} candidate(s)",
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
            self.WORKER_TYPE, self.instance_id, "working", f"evaluating slot {slot.isoformat()}",
            claim_type="scout_evaluation_run", claim_id=run_id,
        )
        try:
            attempt_ids = self._freeze_inputs(run_id, release_id, frozen_at, claim_version)
            evaluation_time = _parse_time(self.store.connection.execute(
                "SELECT input_frozen_at FROM scout_evaluation_runs WHERE scout_evaluation_run_id=?",
                (run_id,),
            ).fetchone()["input_frozen_at"])
            result = self._evaluate(run_id, release_id, manifest, evaluation_time, attempt_ids)
            # Selection budgets use this execution's time, not the older input clock.
            self._finalize(run_id, claim_version, result, manifest, frozen_at)
            summary = f"{result['candidate_count']} candidate(s), {result['selected_count']} selected"
            self.store.finish_worker_run(worker_run_id, "completed", summary=summary)
            self.store.heartbeat(self.WORKER_TYPE, self.instance_id, "idle", summary)
            public_result = {
                key: value for key, value in result.items() if key != "candidates"
            }
            return {"run_id": run_id, "status": "completed", **public_result}
        except Exception as error:
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
            (release_id, now.isoformat(), now.isoformat()),
        ).fetchone()
        if recoverable is not None:
            return int(recoverable["scout_evaluation_run_id"])
        try:
            with self.store.connection:
                cursor = self.store.connection.execute(
                    "INSERT INTO scout_evaluation_runs "
                    "(evaluation_slot_start, configuration_release_id, aggregate_counts_json, "
                    "status, attempt_limit, created_at) VALUES (?, ?, '{}', 'pending', 3, ?)",
                    (slot.isoformat(), release_id, now.isoformat()),
                )
                return int(cursor.lastrowid)
        except sqlite3.IntegrityError:
            row = self.store.connection.execute(
                "SELECT scout_evaluation_run_id FROM scout_evaluation_runs "
                "WHERE evaluation_slot_start=? AND configuration_release_id=?",
                (slot.isoformat(), release_id),
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
                    self.instance_id, now.isoformat(), (now + timedelta(minutes=10)).isoformat(),
                    run_id, now.isoformat(), now.isoformat(),
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
                            "attempt limit exhausted after lease expiry", now.isoformat(),
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
        current_start = frozen_at - timedelta(hours=24)
        baseline_start = current_start - timedelta(days=14)
        frozen_description: list[dict[str, Any]] = []
        attempt_ids: list[int] = []
        with self.store.connection:
            # Acquire the write lock and validate ownership before reading/writing
            # the freeze boundary. A completed empty input still has an input_hash.
            claimed = self.store.connection.execute(
                "UPDATE scout_evaluation_runs "
                "SET input_frozen_at=COALESCE(input_frozen_at,?) "
                "WHERE scout_evaluation_run_id=? AND configuration_release_id=? "
                "AND status='running' AND claim_owner=? AND claim_version=?",
                (frozen_at.isoformat(), run_id, release_id, self.instance_id, claim_version),
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
            release_manifest = json.loads(self.store.connection.execute(
                "SELECT manifest_json FROM configuration_releases WHERE configuration_release_id=?", (release_id,)
            ).fetchone()[0])
            if release_manifest["components"]["detection"]["score_formula_version"] == "attention_v2":
                from .hybrid import freeze
                return freeze(self.store.connection, run_id, release_id, frozen_at)
            sources = self.store.connection.execute(
                "SELECT * FROM detection_source_instances "
                "WHERE configuration_release_id=? AND enabled=1 ORDER BY stable_id",
                (release_id,),
            ).fetchall()
            for source_ordinal, source in enumerate(sources, start=1):
                attempts = self.store.connection.execute(
                    "SELECT a.*, h.source_health_id, h.classification AS health_classification, "
                    "h.reason AS health_reason FROM source_collection_attempts a "
                    "LEFT JOIN source_health h ON h.source_collection_attempt_id=a.source_collection_attempt_id "
                    "WHERE a.source_instance_id=? AND a.status='completed' AND a.complete=1 "
                    "AND a.collected_at>=? AND a.collected_at<=? ORDER BY a.collected_at",
                    (
                        source["detection_source_instance_id"], baseline_start.isoformat(),
                        frozen_at.isoformat(),
                    ),
                ).fetchall()
                latest = attempts[-1] if attempts else None
                latest_any = self.store.connection.execute(
                    "SELECT * FROM source_collection_attempts WHERE source_instance_id=? "
                    "AND created_at<=? ORDER BY created_at DESC, source_collection_attempt_id DESC LIMIT 1",
                    (source["detection_source_instance_id"], frozen_at.isoformat()),
                ).fetchone()
                state, reason = self._input_state(source, latest, latest_any, frozen_at)
                self.store.connection.execute(
                    "INSERT INTO scout_evaluation_inputs "
                    "(scout_evaluation_run_id, source_instance_id, source_collection_attempt_id, "
                    "source_health_id, input_state, reason, ordinal, created_at) VALUES (?,?,?,?,?,?,?,?)",
                    (
                        run_id, source["detection_source_instance_id"],
                        latest["source_collection_attempt_id"] if latest else None,
                        latest["source_health_id"] if latest else None,
                        state, reason, source_ordinal, frozen_at.isoformat(),
                    ),
                )
                role_counts = {"current_window": 0, "baseline_window": 0}
                for attempt in attempts:
                    collected = _parse_time(attempt["collected_at"])
                    role = "current_window" if collected >= current_start else "baseline_window"
                    role_counts[role] += 1
                    attempt_id = int(attempt["source_collection_attempt_id"])
                    attempt_ids.append(attempt_id)
                    self.store.connection.execute(
                        "INSERT INTO scout_evaluation_attempts "
                        "(scout_evaluation_run_id, source_instance_id, source_collection_attempt_id, "
                        "measurement_role, ordinal, created_at) VALUES (?,?,?,?,?,?)",
                        (
                            run_id, source["detection_source_instance_id"], attempt_id, role,
                            role_counts[role], frozen_at.isoformat(),
                        ),
                    )
                frozen_description.append({
                    "source": source["stable_id"], "state": state,
                    "attempt_ids": [int(item["source_collection_attempt_id"]) for item in attempts],
                })
            input_json = canonical_json(frozen_description)
            input_hash = sha256(input_json.encode("utf-8")).hexdigest()
            self.store.connection.execute(
                "UPDATE scout_evaluation_runs SET input_frozen_at=?, input_hash=? "
                "WHERE scout_evaluation_run_id=? AND status='running' "
                "AND claim_owner=? AND claim_version=?",
                (frozen_at.isoformat(), input_hash, run_id, self.instance_id, claim_version),
            )
        return attempt_ids

    @staticmethod
    def _input_state(
        source: sqlite3.Row,
        latest: sqlite3.Row | None,
        latest_any: sqlite3.Row | None,
        frozen_at: datetime,
    ) -> tuple[str, str]:
        if latest is None:
            if latest_any is not None and latest_any["failure_category"] == "quota_limited":
                return "quota_limited", "local quota ceiling reached"
            if latest_any is not None and latest_any["status"] in {"failed", "retry_wait"}:
                return "failed", latest_any["failure_category"] or "latest collection failed"
            return "unavailable", "no complete collection is available"
        age = (frozen_at - _parse_time(latest["collected_at"])).total_seconds()
        availability = int(source["availability_seconds"])
        later_bad = latest_any is not None and int(latest_any["source_collection_attempt_id"]) != int(latest["source_collection_attempt_id"])
        if age <= 1.5 * availability and not later_bad:
            return "current", "latest complete collection is within the healthy window"
        if age <= 3 * availability:
            return "degraded" if later_bad else "reused", "using a prior complete collection within the degraded window"
        return "unavailable", "latest complete collection is outside the degraded window"

    def _evaluate(
        self,
        run_id: int,
        release_id: int,
        manifest: dict[str, Any],
        frozen_at: datetime,
        attempt_ids: list[int],
    ) -> dict[str, Any]:
        if manifest["components"]["detection"]["score_formula_version"] == "attention_v2":
            from .hybrid import evaluate
            return evaluate(self.store.connection, run_id, release_id, manifest)
        if not attempt_ids:
            return {"candidate_count": 0, "selected_count": 0, "candidates": []}
        placeholders = ",".join("?" for _ in attempt_ids)
        observations = self.store.connection.execute(
            f"SELECT o.*, t.canonical_key, s.source_kind, s.stable_id, "
            f"s.independence_group, s.trust_weight "
            f"FROM trend_observations o JOIN detection_source_instances s "
            f"ON s.detection_source_instance_id=o.source_instance_id "
            f"JOIN trends t ON t.trend_id=o.trend_id "
            f"WHERE o.source_collection_attempt_id IN ({placeholders}) "
            f"ORDER BY o.effective_observed_at, o.trend_observation_id",
            tuple(attempt_ids),
        ).fetchall()
        # Never trust a mutable/global collection-time contributor flag for
        # replay. Resolve the documented winner using only these frozen rows.
        observations = [dict(row) for row in observations]
        winners = {}
        for row in observations:
            item = (row["canonical_url"] or row["canonical_key"]) if row["source_kind"] == "publisher_feed_collector_v1" else row["source_item_key"]
            group = (row["independence_group"], row["window_start"], row["window_end"], item)
            pair = (row["source_instance_id"], row["source_item_key"])
            winners[group] = min(winners.get(group, pair), pair)
        for row in observations:
            item = (row["canonical_url"] or row["canonical_key"]) if row["source_kind"] == "publisher_feed_collector_v1" else row["source_item_key"]
            group = (row["independence_group"], row["window_start"], row["window_end"], item)
            row["activity_contributor"] = int((row["source_instance_id"], row["source_item_key"]) == winners[group])
        aliases = {
            row["alias_key"]: row["target_cluster_key"]
            for row in self.store.connection.execute(
                "SELECT alias_key, target_cluster_key FROM detection_cluster_aliases "
                "WHERE configuration_release_id=? AND active=1",
                (release_id,),
            )
        }
        health = {
            int(row["source_instance_id"]): row["input_state"]
            for row in self.store.connection.execute(
                "SELECT source_instance_id, input_state FROM scout_evaluation_inputs "
                "WHERE scout_evaluation_run_id=?",
                (run_id,),
            )
        }
        current_start = frozen_at - timedelta(hours=24)
        windowed: dict[tuple[str, str, int], list[sqlite3.Row]] = defaultdict(list)
        current_members: dict[str, list[sqlite3.Row]] = defaultdict(list)
        for observation in observations:
            measured = _parse_time(observation["effective_observed_at"])
            if measured < current_start - timedelta(days=14) or measured > frozen_at:
                continue
            cluster = observation["canonical_key"]
            while cluster in aliases:
                cluster = aliases[cluster]
            age_days = int((frozen_at - measured).total_seconds() // 86400)
            windowed[(cluster, observation["source_kind"], age_days)].append(observation)
            if measured >= current_start:
                current_members[cluster].append(observation)

        activity: dict[tuple[str, str], float] = {}
        historical_activity: dict[tuple[str, str, int], float] = {}
        valid_history_days: dict[str, set[int]] = defaultdict(set)
        for (cluster, kind, age_days), items in windowed.items():
            value = self._source_activity(kind, items)
            if age_days == 0:
                activity[(cluster, kind)] = value
            elif 1 <= age_days <= 14:
                historical_activity[(cluster, kind, age_days)] = value
                valid_history_days[kind].add(age_days)

        prominence: dict[tuple[str, str], float] = {}
        prominence_meta: dict[tuple[str, str], dict[str, Any]] = {}
        kinds = {kind for _, kind in activity}
        for kind in kinds:
            values = [(cluster, value) for (cluster, source_kind), value in activity.items() if source_kind == kind]
            values.sort(key=lambda item: (-item[1], item[0]))
            count = len(values)
            index = 0
            while index < count:
                end = index + 1
                while end < count and values[end][1] == values[index][1]:
                    end += 1
                midrank = ((index + 1) + end) / 2
                score = 0.5 if count == 1 else 1 - ((midrank - 1) / (count - 1))
                for tied in range(index, end):
                    cluster = values[tied][0]
                    prominence[(cluster, kind)] = score
                    prominence_meta[(cluster, kind)] = {
                        "population_size": count,
                        "midrank": round(midrank, 6),
                        "tie_size": end - index,
                    }
                index = end

        candidates: list[dict[str, Any]] = []
        for cluster, members in current_members.items():
            source_kinds = sorted({row["source_kind"] for row in members})
            source_components: list[dict[str, Any]] = []
            weighted_g = weighted_p = weighted_r = weight_sum = 0.0
            history_ready = False
            independence_groups = {row["independence_group"] for row in members if row["activity_contributor"]}
            for kind in source_kinds:
                kind_members = [row for row in members if row["source_kind"] == kind]
                a_value = activity[(cluster, kind)]
                history_days = sorted(valid_history_days.get(kind, set()))
                baselines = [
                    historical_activity.get((cluster, kind, age_days), 0.0)
                    for age_days in history_days
                ]
                ready = len(baselines) >= 7
                history_ready = history_ready or ready
                baseline = median(baselines) if baselines else 0.0
                p_value = prominence[(cluster, kind)]
                g_value = _clamp(log2((a_value + 1) / (baseline + 1)) / 2) if ready else 0.5 * p_value
                reliability_values = []
                for row in kind_members:
                    state = health.get(int(row["source_instance_id"]), "unavailable")
                    multiplier = 1.0 if state in {"current", "reused"} else 0.5 if state == "degraded" else 0.0
                    reliability_values.append(float(row["trust_weight"]) * multiplier)
                r_value = max(reliability_values, default=0.0)
                weight = max(r_value, 0.000001)
                weighted_g += g_value * weight
                weighted_p += p_value * weight
                weighted_r += r_value * weight
                weight_sum += weight
                source_components.append({
                    "source_kind": kind, "activity": round(a_value, 6),
                    "baseline": round(baseline, 6), "history_windows": len(baselines),
                    "history_day_offsets": history_days,
                    "history_ready": ready, "momentum": round(g_value, 6),
                    "prominence": round(p_value, 6), "reliability": round(r_value, 6),
                    "prominence_population": prominence_meta[(cluster, kind)],
                    "attempt_ids": sorted({
                        int(row["source_collection_attempt_id"]) for row in kind_members
                    }),
                    "observation_ids": sorted({
                        int(row["trend_observation_id"]) for row in kind_members
                    }),
                    "measurement_windows": sorted({
                        (row["window_start"], row["window_end"]) for row in kind_members
                    }),
                })
            momentum = weighted_g / weight_sum if weight_sum else 0.0
            prominent = weighted_p / weight_sum if weight_sum else 0.0
            reliability = weighted_r / weight_sum if weight_sum else 0.0
            breadth = min(1.0, len(independence_groups) / 3)
            persistence_windows = len({
                int((frozen_at - _parse_time(row["effective_observed_at"])).total_seconds() // 86400)
                for row in observations
                if row["trend_id"] in {item["trend_id"] for item in members}
                and _parse_time(row["effective_observed_at"]) >= frozen_at - timedelta(hours=72)
            })
            persistence = min(1.0, persistence_windows / 3)
            newest = max(_parse_time(row["effective_observed_at"]) for row in members)
            freshness = _clamp(1 - (frozen_at - newest).total_seconds() / 3600 / 48)
            final = round(
                momentum * 0.30 + prominent * 0.20 + breadth * 0.20
                + persistence * 0.10 + freshness * 0.10 + reliability * 0.10,
                4,
            )
            breakdown = {
                "formula_version": "attention_v1", "source_components": source_components,
                "momentum": round(momentum, 6), "prominence": round(prominent, 6),
                "breadth": round(breadth, 6), "persistence": round(persistence, 6),
                "freshness": round(freshness, 6), "reliability": round(reliability, 6),
                "history_ready": history_ready, "score": final,
            }
            evidence = [{
                "observation_id": int(row["trend_observation_id"]), "source": row["stable_id"],
                "title": row["title"], "activity": row["activity"], "rank": row["rank"],
            } for row in members]
            evidence_json = canonical_json(evidence)
            fingerprint = sha256(evidence_json.encode("utf-8")).hexdigest()
            policy = manifest["components"]["detection"]["shortlist"]
            eligible = (
                final >= policy["minimum_score"] and reliability >= policy["minimum_reliability"]
                and (history_ready or len(independence_groups) >= 2)
            )
            failed_gates = []
            if final < policy["minimum_score"]:
                failed_gates.append("score_below_threshold")
            if reliability < policy["minimum_reliability"]:
                failed_gates.append("reliability_below_threshold")
            if not history_ready and len(independence_groups) < 2:
                failed_gates.append("bootstrap_requires_two_independent_groups")
            candidates.append({
                "cluster_key": cluster,
                "opportunity_identity": f"trend:canonicalization_v1:{cluster}",
                "canonical_subject": members[0]["title"], "score": final,
                "breakdown": breakdown, "evidence": evidence,
                "evidence_json": evidence_json, "evidence_fingerprint": fingerprint,
                "members": members, "eligible": eligible,
                "eligibility_reason": "eligible" if eligible else ",".join(failed_gates),
                "breadth": breadth, "prominence": prominent, "freshness": freshness,
            })
        candidates.sort(key=lambda item: (-item["score"], -item["breadth"], -item["prominence"], -item["freshness"], item["opportunity_identity"]))
        return {"candidate_count": len(candidates), "selected_count": 0, "candidates": candidates}

    @staticmethod
    def _source_activity(kind: str, items: list[sqlite3.Row]) -> float:
        if kind == "publisher_feed_collector_v1":
            return float(len({row["independence_group"] for row in items if row["activity_contributor"]}))
        if kind == "wikimedia_enwiki_pageviews_v1":
            return float(sum(row["activity"] for row in items if row["activity_contributor"]))
        if kind == "youtube_most_popular_v1":
            return float(max(
                (
                    51 - int(row["rank"]) for row in items
                    if row["rank"] is not None and row["activity_contributor"]
                ),
                default=0,
            ))
        if kind == "hacker_news_top_stories_v1":
            return max(
                (
                    ((101 - int(row["rank"])) / 100) * log2(float(row["activity"]) + 1)
                    for row in items
                    if row["rank"] is not None and row["activity_contributor"]
                ),
                default=0.0,
            )
        raise ValueError(f"Unsupported source kind: {kind}")

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
        six_hours = (frozen_at - timedelta(hours=6)).isoformat()
        day = (frozen_at - timedelta(hours=24)).isoformat()
        deferred_stale_before = (
            frozen_at - timedelta(hours=policy["deferred_fresh_hours"])
        ).isoformat()
        with self.store.connection:
            for kind, population in result.get("prominence_populations", {}).items():
                encoded_population = canonical_json(population)
                self.store.connection.execute(
                    "INSERT INTO scout_prominence_populations(scout_evaluation_run_id,source_kind,population_json,population_hash,created_at) VALUES (?,?,?,?,?)",
                    (run_id, kind, encoded_population, sha256(encoded_population.encode()).hexdigest(), frozen_at.isoformat()),
                )
            self.store.connection.execute(
                "UPDATE trend_candidates SET eligibility_status='deferred_stale', "
                "eligibility_reason='deferred_evidence_older_than_policy_window', "
                "updated_at=? WHERE eligibility_status='deferred_by_budget' "
                "AND last_seen_at<=?",
                (frozen_at.isoformat(), deferred_stale_before),
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
                        frozen_at.isoformat(),
                    ),
                )
                snapshot_id = int(self.store.connection.execute("SELECT last_insert_rowid()").fetchone()[0])
                existing = self.store.connection.execute(
                    "SELECT * FROM trend_candidates WHERE opportunity_identity=?",
                    (candidate["opportunity_identity"],),
                ).fetchone()
                desired_status = "eligible" if candidate["eligible"] else "observed"
                reason = candidate["eligibility_reason"]
                if existing and existing["eligibility_status"] in {
                    "selected", "consumed", "rejected_cooldown", "reconsiderable",
                    "migration_hold",
                }:
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
                            candidate.get("last_seen_at", frozen_at.isoformat()), frozen_at.isoformat(), existing["trend_candidate_id"],
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
                            normalization_version, desired_status, reason, rank, frozen_at.isoformat(),
                            candidate.get("last_seen_at", frozen_at.isoformat()), frozen_at.isoformat(), frozen_at.isoformat(),
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
                            }), frozen_at.isoformat(),
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
                        (candidate_id, frozen_at.isoformat(), frozen_at.isoformat()),
                    )
                    thread_id = int(thread_cursor.lastrowid)
                    context = {
                        "candidate_id": candidate_id, "topic_snapshot_id": snapshot_id,
                        "opportunity_identity": candidate["opportunity_identity"],
                        "evidence_fingerprint": candidate["evidence_fingerprint"],
                    }
                    self.store.connection.execute(
                        "INSERT INTO intake_requests "
                        "(thread_id, source_candidate_id, context_json, context_version, status, "
                        "attempt_limit, created_at) VALUES (?, ?, ?, 'trend_intake_context_v1', 'pending', 3, ?)",
                        (thread_id, candidate_id, canonical_json(context), frozen_at.isoformat()),
                    )
                    self.store.connection.execute(
                        "UPDATE trend_candidates SET eligibility_status='selected', "
                        "eligibility_reason='selected_by_shortlist_v1', selected_at=?, "
                        "selected_thread_id=?, updated_at=? WHERE trend_candidate_id=?",
                        (frozen_at.isoformat(), thread_id, frozen_at.isoformat(), candidate_id),
                    )
                    selected_count += 1
                    selected_6h += 1
                    selected_24h += 1
                elif desired_status == "eligible":
                    self.store.connection.execute(
                        "UPDATE trend_candidates SET eligibility_status='deferred_by_budget', "
                        "eligibility_reason='selection_budget_exhausted', updated_at=? "
                        "WHERE trend_candidate_id=?",
                        (frozen_at.isoformat(), candidate_id),
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
            datetime.now(timezone.utc) + timedelta(seconds=delay)
        ).isoformat() if retry else None
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
