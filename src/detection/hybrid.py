"""Versioned hybrid attention evaluation for frozen live/daily evidence."""

from collections import defaultdict
from datetime import datetime, timedelta, timezone
from hashlib import sha256
from math import log2
from statistics import median
import json
from common.timestamps import parse_timestamp, serialize_timestamp

from .configuration import canonical_json
from .semantic import load_resolution, observation_rows

WIKI = "wikimedia_enwiki_pageviews_v1"
FEED = "publisher_feed_collector_v1"
HN = "hacker_news_top_stories_v1"


def moment(value):
    return parse_timestamp(value)


def midnight(value):
    return value.replace(hour=0, minute=0, second=0, microsecond=0)


def health(source, complete, failures, at):
    prior = [a for a in complete if moment(a["collected_at"]) <= at]
    latest = max(prior, key=lambda a: (a["collected_at"], a["source_collection_attempt_id"]), default=None)
    errors = [e for e in failures if moment(e["time"]) <= at]
    latest_error = max(errors, key=lambda e: e["time"], default=None)
    if latest_error and (latest is None or latest_error["time"] >= latest["collected_at"]):
        if latest_error["category"] == "quota_limited":
            return "quota_limited", latest
        later_bad = True
    else:
        later_bad = False
    if latest is None:
        return "unavailable", None
    age = (at - moment(latest["collected_at"])).total_seconds()
    if age <= 1.5 * source["availability_seconds"] and not later_bad:
        return "current", latest
    return ("degraded" if age <= 3 * source["availability_seconds"] else "unavailable"), latest


def freeze(connection, run_id, release_id, at):
    """Caller owns the fenced SQLite write transaction; persist once."""
    source_rows = connection.execute(
        "SELECT * FROM detection_source_instances WHERE configuration_release_id=? AND enabled=1 ORDER BY stable_id", (release_id,)
    ).fetchall()
    frozen = {"version": "scout_input_v2", "at": serialize_timestamp(at), "sources": []}
    ids = []
    cutoff = serialize_timestamp(midnight(at) - timedelta(days=21))
    for ordinal, row in enumerate(source_rows, 1):
        source = dict(row)
        complete = [dict(a) for a in connection.execute(
            "SELECT a.* FROM source_collection_attempts a JOIN detection_source_instances s ON s.detection_source_instance_id=a.source_instance_id "
            "WHERE s.stable_id=? AND s.config_fingerprint=? AND a.status='completed' AND a.complete=1 "
            "AND a.collected_at>=? AND a.collected_at<=? ORDER BY a.collected_at,a.source_collection_attempt_id",
            (source["stable_id"], source["config_fingerprint"], cutoff, serialize_timestamp(at)),
        )]
        failures = [{"time": a["completed_at"], "category": a["error_category"]} for a in connection.execute(
            "SELECT e.completed_at,e.error_category FROM source_request_executions e JOIN detection_source_instances s ON s.detection_source_instance_id=e.source_instance_id "
            "WHERE s.stable_id=? AND s.config_fingerprint=? AND e.status='failed' AND e.completed_at>=? AND e.completed_at<=?",
            (source["stable_id"], source["config_fingerprint"], cutoff, serialize_timestamp(at)),
        )]
        # Quota refusal has no outbound execution; pending retry failures must
        # also affect current health before their final terminal health row.
        for failure in connection.execute(
            "SELECT a.failure_category,a.completed_at time FROM source_collection_attempts a "
            "JOIN detection_source_instances s ON s.detection_source_instance_id=a.source_instance_id "
            "WHERE s.stable_id=? AND s.config_fingerprint=? AND a.status IN ('failed','retry_wait') "
            "AND a.created_at>=? AND a.created_at<=?",
            (source["stable_id"], source["config_fingerprint"], cutoff, serialize_timestamp(at)),
        ):
            failures.append({"time": failure["time"] or serialize_timestamp(at), "category": failure["failure_category"]})
        state, latest = health(source, complete, failures, at)
        source["state"] = state
        source["latest_attempt_id"] = latest["source_collection_attempt_id"] if latest else None
        source["report_days"] = sorted({
            json.loads(a["request_json"]).get("report_date") or (moment(a["scheduled_for"]).date() - timedelta(days=1)).isoformat()
            for a in complete
        }) if source["source_kind"] == WIKI else []
        source["history_health"] = {}
        for offset in range(1, 22):
            day = midnight(at) - timedelta(days=offset)
            # The half-open day's health is sampled immediately before its end.
            status, _ = health(source, complete, failures, day + timedelta(days=1, microseconds=-1))
            source["history_health"][day.date().isoformat()] = status
        connection.execute(
            "INSERT INTO scout_evaluation_inputs(scout_evaluation_run_id,source_instance_id,source_collection_attempt_id,input_state,reason,ordinal,created_at) VALUES (?,?,?,?,?,?,?)",
            (run_id, source["detection_source_instance_id"], source["latest_attempt_id"], state, "hybrid attention inputs frozen", ordinal, serialize_timestamp(at)),
        )
        for attempt_ordinal, attempt in enumerate(complete, 1):
            attempt_id = attempt["source_collection_attempt_id"]
            ids.append(attempt_id)
            connection.execute(
                "INSERT INTO scout_evaluation_attempts(scout_evaluation_run_id,source_instance_id,source_collection_attempt_id,measurement_role,ordinal,created_at) VALUES (?,?,?,'baseline_window',?,?)",
                (run_id, source["detection_source_instance_id"], attempt_id, attempt_ordinal, serialize_timestamp(at)),
            )
        source["attempt_ids"] = [a["source_collection_attempt_id"] for a in complete]
        frozen["sources"].append(source)
    payload = canonical_json(frozen)
    fingerprint = sha256(payload.encode()).hexdigest()
    connection.execute(
        "INSERT INTO scout_frozen_evidence(scout_evaluation_run_id,snapshot_version,snapshot_json,snapshot_hash,created_at) VALUES (?,'scout_input_v2',?,?,?)",
        (run_id, payload, fingerprint, serialize_timestamp(at)),
    )
    connection.execute("UPDATE scout_evaluation_runs SET input_hash=? WHERE scout_evaluation_run_id=?", (fingerprint, run_id))
    return ids


def activity(kind, rows):
    rows = [r for r in rows if r["activity_contributor"]]
    if kind == FEED:
        return float(len({r["independence_group"] for r in rows}))
    if kind == WIKI:
        articles = {}
        for row in sorted(rows, key=lambda r: r["trend_observation_id"]):
            articles.setdefault((row["source_item_key"], row["window_start"]), row["activity"])
        return float(sum(articles.values()))
    if kind == HN:
        return round(max((((101 - r["rank"]) / 100) * log2(r["activity"] + 1) for r in rows if r["rank"]), default=0), 6)
    return float(max((51 - r["rank"] for r in rows if r["rank"]), default=0))


def evaluate(connection, run_id, release_id, manifest):
    release = connection.execute(
        "SELECT r.configuration_release_id,c.manifest_json FROM scout_evaluation_runs r "
        "JOIN configuration_releases c USING(configuration_release_id) WHERE scout_evaluation_run_id=?", (run_id,)
    ).fetchone()
    if release is None or release["configuration_release_id"] != release_id or canonical_json(manifest) != canonical_json(json.loads(release["manifest_json"])):
        raise ValueError("scoring requires the evaluation's frozen configuration release")
    normalization_version = manifest["components"]["detection"]["canonicalization_version"]
    record = connection.execute("SELECT * FROM scout_frozen_evidence WHERE scout_evaluation_run_id=?", (run_id,)).fetchone()
    if record is None or sha256(record["snapshot_json"].encode()).hexdigest() != record["snapshot_hash"]:
        raise ValueError("missing or corrupted frozen hybrid evidence")
    frozen = json.loads(record["snapshot_json"])
    at = moment(frozen["at"])
    sources = {s["stable_id"]: s for s in frozen["sources"]}
    resolution = load_resolution(connection, run_id)
    rows = observation_rows(connection, run_id)
    report_days = {name: set(source["report_days"]) for name, source in sources.items()}
    latest_report = {name: max(days) for name, days in report_days.items() if days}
    winners = {}
    for row in rows:
        cluster = row["canonical_key"]
        row["cluster"] = cluster
        row["day"] = row["window_start"][:10]
        identity = (row["canonical_url"] or row["canonical_key"]) if row["source_kind"] == FEED else row["source_item_key"]
        group = (row["independence_group"], row["day"], identity)
        pair = (row["stable_id"], row["source_item_key"])
        row["dedup_group"] = group
        winners[group] = min(winners.get(group, pair), pair)
    current = defaultdict(list)
    history = defaultdict(list)
    for row in rows:
        source = sources[row["stable_id"]]
        row["activity_contributor"] = int((row["stable_id"], row["source_item_key"]) == winners[row["dedup_group"]])
        row["evidence_time"] = row["window_end"] if row["source_kind"] == WIKI else row["effective_observed_at"]
        in_current = row["day"] == latest_report.get(row["stable_id"]) if row["source_kind"] == WIKI else at - timedelta(hours=24) < moment(row["effective_observed_at"]) <= at
        if in_current:
            current[row["cluster"]].append(row)
        valid_day = (row["source_kind"] == WIKI or source["history_health"].get(row["day"]) == "current") and source["trust_weight"] > 0
        if valid_day:
            history[(row["cluster"], row["source_kind"], row["day"])].append(row)
    usable = {cluster: [r for r in members if sources[r["stable_id"]]["state"] in {"current", "degraded"}
                        and r["trust_weight"] > 0 and r["activity_contributor"]] for cluster, members in current.items()}
    activities = {}
    for cluster, members in usable.items():
        for kind in {r["source_kind"] for r in members}:
            activities[(cluster, kind)] = activity(kind, [r for r in members if r["source_kind"] == kind])
    populations = {}
    population_refs = {}
    prominence = {}
    for kind in {key[1] for key in activities}:
        population = sorted([{"cluster_key": c, "activity": a} for (c, k), a in activities.items() if k == kind], key=lambda p: (-p["activity"], p["cluster_key"]))
        n = len(population)
        index = 0
        while index < n:
            end = index + 1
            while end < n and population[end]["activity"] == population[index]["activity"]:
                end += 1
            midrank = ((index + 1) + end) / 2
            for entry in population[index:end]:
                entry.update(midrank=midrank, tie_size=end - index, prominence=0.5 if n == 1 else 1 - (midrank - 1) / (n - 1))
                prominence[(entry["cluster_key"], kind)] = entry["prominence"]
            index = end
        populations[kind] = population
        population_refs[kind] = {"scout_evaluation_run_id": run_id, "source_kind": kind,
                                 "population_size": n, "population_hash": sha256(canonical_json(population).encode()).hexdigest()}
    persistence_by_cluster = defaultdict(set)
    for (cluster, kind, day), evidence in history.items():
        if any(r["activity_contributor"] for r in evidence) and at - timedelta(hours=72) < moment(day + "T00:00:00+00:00") + timedelta(days=1) <= at:
            persistence_by_cluster[cluster].add(day)
    candidates = []
    policy = manifest["components"]["detection"]["shortlist"]
    for cluster, all_members in current.items():
        members = usable[cluster]
        components = []
        total_weight = weighted_g = weighted_p = weighted_r = 0.0
        ready = False
        for kind in sorted({r["source_kind"] for r in members}):
            selected = [r for r in members if r["source_kind"] == kind]
            current_day = min(r["day"] for r in selected) if kind == WIKI else midnight(at - timedelta(hours=24)).date().isoformat()
            baseline_end = moment(current_day + "T00:00:00+00:00")
            days = [(baseline_end - timedelta(days=i)).date().isoformat() for i in range(1, 15)]
            kind_sources = [s for s in sources.values() if s["source_kind"] == kind and s["trust_weight"] > 0]
            valid_days = [d for d in days if any(
                d in report_days[s["stable_id"]] if kind == WIKI else s["history_health"].get(d) == "current"
                for s in kind_sources)]
            values = [activity(kind, history.get((cluster, kind, d), [])) for d in valid_days]
            baseline = median(values) if values else 0
            history_ready = len(values) >= 7
            ready = ready or history_ready
            a = activities[(cluster, kind)]
            p = prominence[(cluster, kind)]
            g = min(1, max(0, log2((a + 1) / (baseline + 1)) / 2)) if history_ready else 0.5 * p
            reliability = max(r["trust_weight"] * (1 if sources[r["stable_id"]]["state"] == "current" else 0.5) for r in selected)
            weighted_g += g * reliability
            weighted_p += p * reliability
            weighted_r += reliability * reliability
            total_weight += reliability
            components.append({"source_kind": kind, "activity": a, "baseline": baseline,
                               "history_ready": history_ready, "history_windows": len(values), "history_days": valid_days,
                               "baseline_values": values, "momentum": g, "prominence": p, "reliability": reliability,
                               "prominence_population": population_refs[kind],
                               "observation_ids": [r["trend_observation_id"] for r in selected]})
        groups = {r["independence_group"] for r in members}
        persistence_days = persistence_by_cluster[cluster]
        newest = max((moment(r["evidence_time"]) for r in members), default=None)
        evidence_recency = min(1, max(0, 1 - (at - newest).total_seconds() / 172800)) if newest else 0
        parts = {"momentum": weighted_g / total_weight if total_weight else 0,
                 "prominence": weighted_p / total_weight if total_weight else 0,
                 "reliability": weighted_r / total_weight if total_weight else 0,
                 "breadth": min(1, len(groups) / 3), "persistence": min(1, len(persistence_days) / 3),
                 "evidence_recency": evidence_recency}
        formula_version = manifest["components"]["detection"]["score_formula_version"]
        weights = {"momentum": 1 / 3, "prominence": 2 / 9, "breadth": 2 / 9,
                   "persistence": 1 / 9, "reliability": 1 / 9}
        ranking_recency = parts["evidence_recency"]
        score = round(sum(parts[name] * weight for name, weight in weights.items()), 4)
        breakdown = {**parts, "formula_version": formula_version, "source_components": components, "score": score,
                     "history_ready": ready, "persistence_days": sorted(persistence_days),
                     "excluded_observation_ids": [r["trend_observation_id"] for r in all_members if r not in members]}
        evidence = [{"observation_id": r["trend_observation_id"], "source": r["stable_id"], "title": r["title"],
                     "activity": r["activity"], "rank": r["rank"], "contributing": r in members} for r in all_members]
        encoded = canonical_json(evidence)
        reasons = []
        if score < policy["minimum_score"]: reasons.append("score_below_threshold")
        if parts["reliability"] < policy["minimum_reliability"]: reasons.append("reliability_below_threshold")
        if not ready and len(groups) < 2: reasons.append("bootstrap_requires_two_independent_groups")
        last_seen = newest or max(moment(r["evidence_time"]) for r in all_members)
        candidates.append({"cluster_key": cluster, "opportunity_identity": f"trend:{normalization_version}:{cluster}",
                           "canonical_subject": all_members[0]["title"], "score": score, "breakdown": breakdown,
                           "evidence": evidence, "evidence_json": encoded, "evidence_fingerprint": sha256(encoded.encode()).hexdigest(),
                           "members": all_members, "eligible": not reasons, "eligibility_reason": ",".join(reasons) or "eligible",
                           "breadth": parts["breadth"], "prominence": parts["prominence"],
                           "evidence_recency": ranking_recency,
                           "last_seen_at": serialize_timestamp(last_seen)})
    candidates.sort(key=lambda c: (-c["score"], -c["breadth"], -c["prominence"], -c["evidence_recency"], c["opportunity_identity"]))
    # Score credit belongs to the strongest lexical constituent. Inferred
    # membership cannot manufacture source breadth, momentum or eligibility.
    mapping = {n["lexical_key"]: n["resolved_key"] for n in resolution["clusters"]}
    frozen_members = sorted((n["lexical_key"], oid) for n in resolution["clusters"] for oid in n["observation_ids"])
    actual_members = sorted((r["canonical_key"], r["trend_observation_id"]) for r in rows)
    if set(mapping) != {r["canonical_key"] for r in rows} or frozen_members != actual_members:
        raise ValueError("frozen event partition does not cover the source input")
    events = defaultdict(list)
    for candidate in candidates:
        events[mapping[candidate["cluster_key"]]].append(candidate)
    resolved = []
    for event, constituents in events.items():
        anchor = min(constituents, key=lambda c: (not c["eligible"], -c["score"], -c["breadth"], -c["prominence"], c["cluster_key"]))
        result = dict(anchor)
        keys = sorted(c["cluster_key"] for c in constituents)
        all_members = sorted([m for c in constituents for m in c["members"]], key=lambda m: m["trend_observation_id"])
        scoring_ids = {e["observation_id"] for e in anchor["evidence"] if e["contributing"]}
        evidence = [{**e, "lexical_key": c["cluster_key"], "contributing": e["observation_id"] in scoring_ids}
                    for c in sorted(constituents, key=lambda c: c["cluster_key"]) for e in c["evidence"]]
        encoded = canonical_json(evidence)
        result.update(cluster_key=event, opportunity_identity=f"trend:{normalization_version}:{event}",
                      members=all_members, lexical_keys=keys, evidence=evidence, evidence_json=encoded,
                      evidence_fingerprint=sha256(encoded.encode()).hexdigest())
        result["breakdown"] = {**anchor["breakdown"],
            "semantic_resolution": {"scout_evaluation_run_id": run_id, "resolved_key": event,
                                    "lexical_keys": keys, "scoring_lexical_key": anchor["cluster_key"],
                                    "credit_policy": "strongest_lexical_constituent"},
            "excluded_observation_ids": [m["trend_observation_id"] for m in all_members if m["trend_observation_id"] not in scoring_ids]}
        resolved.append(result)
    resolved.sort(key=lambda c: (-c["score"], -c["breadth"], -c["prominence"], -c["evidence_recency"], c["opportunity_identity"]))
    return {"candidate_count": len(resolved), "selected_count": 0, "candidates": resolved,
            "prominence_populations": populations}
