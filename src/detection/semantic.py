"""Conservative local event resolution over lexical clusters, never observations."""

from collections import defaultdict
from datetime import datetime, timedelta, timezone
from hashlib import sha256
from math import isfinite, sqrt
import json
import re
from time import monotonic
from common.operation_log import emit

from .configuration import canonical_json


def moment(value):
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc)


class LocalEmbeddingEncoder:
    """Lazy CPU-only inference. Model provisioning is an explicit setup operation."""

    def __init__(self):
        self.model = None
        self.identity = None

    def encode(self, texts, policy):
        identity = (policy["model_id"], policy["model_revision"], policy["cpu_threads"])
        if self.identity != identity:
            started = monotonic()
            import os
            # No telemetry, metadata checks or automatic downloads in Scout.
            os.environ["HF_HUB_OFFLINE"] = "1"
            os.environ["HF_HUB_DISABLE_TELEMETRY"] = "1"
            from sentence_transformers import SentenceTransformer
            import torch
            torch.set_num_threads(policy["cpu_threads"])
            self.model = SentenceTransformer(
                policy["model_id"], revision=policy["model_revision"], device="cpu",
                local_files_only=True, trust_remote_code=False,
                model_kwargs={"use_safetensors": True},
            )
            self.identity = identity
            emit('detection', 'embedding_load', model_id=policy['model_id'], duration_ms=round((monotonic()-started)*1000), status='completed')
        started = monotonic()
        result = self.model.encode(
            texts, batch_size=policy["batch_size"], normalize_embeddings=True,
            show_progress_bar=False, convert_to_numpy=True,
        ).tolist()
        emit('detection', 'embedding_batch', model_id=policy['model_id'], cluster_count=len(texts),
             duration_ms=round((monotonic()-started)*1000), status='completed')
        return result


def observation_rows(connection, run_id):
    return [dict(row) for row in connection.execute(
        "SELECT o.*,t.canonical_key,s.stable_id,s.source_kind,s.independence_group,s.trust_weight "
        "FROM scout_evaluation_attempts f JOIN trend_observations o "
        "ON o.source_collection_attempt_id=f.source_collection_attempt_id "
        "JOIN trends t ON t.trend_id=o.trend_id "
        "JOIN detection_source_instances s ON s.detection_source_instance_id=o.source_instance_id "
        "WHERE f.scout_evaluation_run_id=? ORDER BY o.trend_observation_id", (run_id,)
    )]


def signals(title, policy):
    words = re.findall(r"[^\W_]+(?:[.'’][^\W_]+)*", title, re.UNICODE)
    ignored = set(policy["entity_stopwords"])
    actions = {word: kind for kind, terms in policy["event_terms"].items() for word in terms}
    entities = {
        policy["entity_aliases"].get(word.casefold(), word.casefold())
        for word in words
        if any(c.isupper() for c in word) and word.casefold() not in ignored
        and word.casefold() not in actions and not word.isdigit()
    }
    lowered = title.casefold()
    action_index = next((i for i, word in enumerate(words) if word.casefold() in actions), len(words))
    def role_tokens(part):
        return sorted({policy["entity_aliases"].get(w.casefold(), w.casefold()) for w in part
                       if any(c.isupper() for c in w)
                       and policy["entity_aliases"].get(w.casefold(), w.casefold()) in entities})
    numbers = set(re.findall(r"\d+(?:[.,]\d+)*(?:\s*(?:(?:billion|million|trillion|percent|bn|[mbk])\b|%))?", lowered))
    return {
        "entities": sorted(entities),
        "entity_roles": [role_tokens(words[:action_index]), role_tokens(words[action_index + 1:])],
        "numbers": sorted(re.sub(r"\s+", "", n) for n in numbers),
        "events": sorted({actions[w.casefold()] for w in words if w.casefold() in actions}),
        "negations": sorted({w.casefold() for w in words} & set(policy["negation_terms"])),
    }


def resolve(rows, at, policy, encoder):
    """Return a bounded explainable partition; unexamined nodes stay singletons."""
    by_key = defaultdict(list)
    for row in rows:
        by_key[row["canonical_key"]].append(row)
    nodes = []
    for key, members in sorted(by_key.items()):
        # Repeated polls cannot change the representative or multiply embeddings.
        first = min(members, key=lambda r: r["trend_observation_id"])
        title = first["title"]
        times = [moment(r["window_end"] if r["source_kind"] == "wikimedia_enwiki_pageviews_v1"
                        else r["effective_observed_at"]) for r in members]
        node = {"lexical_key": key, "title": title, "trend_id": min(r["trend_id"] for r in members),
                "observation_ids": sorted(r["trend_observation_id"] for r in members),
                "latest_evidence_at": max(times).isoformat(),
                "urls": sorted({r["canonical_url"] for r in members if r["canonical_url"]}),
                "signals": signals(title, policy), "resolution_status": "unresolved",
                "reason": "outside_recent_window", "resolved_key": key}
        if at - timedelta(hours=policy["recent_hours"]) <= max(times) <= at:
            node["reason"] = "candidate_limit"
        if len({canonical_json(signals(t, policy)) for t in {m["title"] for m in members}}) > 1:
            node["reason"] = "inconsistent_lexical_evidence"
        nodes.append(node)
    recent = sorted((n for n in nodes if n["reason"] == "candidate_limit"),
                    key=lambda n: (-moment(n["latest_evidence_at"]).timestamp(), n["lexical_key"]))[:policy["max_clusters"]]
    pairs = []
    degree = defaultdict(int)
    for i, left in enumerate(recent):
        left["reason"] = "no_plausible_peer"
        peers = sorted(recent[i + 1:], key=lambda n: (
            abs((moment(left["latest_evidence_at"]) - moment(n["latest_evidence_at"])).total_seconds()), n["lexical_key"]))
        for right in peers:
            a, b = left["signals"], right["signals"]
            shared_url = bool(set(left["urls"]) & set(right["urls"]))
            if not (set(a["entities"]) & set(b["entities"]) or shared_url):
                continue
            if len(pairs) >= policy["max_pairs"] or any(degree[n["lexical_key"]] >= policy["max_neighbors"] for n in (left, right)):
                continue
            gap = abs((moment(left["latest_evidence_at"]) - moment(right["latest_evidence_at"])).total_seconds()) / 3600
            pair = {"left": left["lexical_key"], "right": right["lexical_key"],
                    "similarity": None, "time_gap_hours": round(gap, 6), "shared_url": shared_url,
                    "entity_compatible": bool(a["entities"]) and a["entities"] == b["entities"],
                    "numbers_equal": a["numbers"] == b["numbers"],
                    "event_compatible": bool(a["events"]) and a["events"] == b["events"],
                    "outcome": "unresolved", "reason": "insufficient_event_signals"}
            if gap > policy["max_pair_hours"]:
                pair.update(outcome="separate", reason="temporal_conflict")
            elif a["numbers"] and b["numbers"] and a["numbers"] != b["numbers"]:
                pair.update(outcome="separate", reason="numeric_conflict")
            elif a["negations"] != b["negations"]:
                pair.update(outcome="separate", reason="negation_conflict")
            elif a["entities"] and b["entities"] and a["entities"] != b["entities"]:
                pair.update(outcome="separate", reason="entity_conflict")
            elif a["events"] and b["events"] and a["events"] != b["events"]:
                pair.update(outcome="separate", reason="event_conflict")
            elif a["entity_roles"] != b["entity_roles"]:
                pair.update(reason="entity_roles_differ")
            elif pair["entity_compatible"] and pair["event_compatible"] and pair["numbers_equal"]:
                pair["reason"] = "awaiting_similarity"
            pairs.append(pair)
            for node in (left, right):
                degree[node["lexical_key"]] += 1
    needed = {key for p in pairs if p["reason"] == "awaiting_similarity" for key in (p["left"], p["right"])}
    inputs = sorted((n for n in recent if n["lexical_key"] in needed), key=lambda n: n["lexical_key"])
    vectors = {}
    if inputs:
        encoded = encoder.encode([n["title"] for n in inputs], policy)
        if len(encoded) != len(inputs):
            raise ValueError("semantic encoder returned a mismatched batch")
        for node, vector in zip(inputs, encoded):
            if len(vector) != policy["dimensions"] or not all(isfinite(v) for v in vector):
                raise ValueError("semantic encoder returned an invalid vector")
            norm = sqrt(sum(v * v for v in vector))
            if norm == 0:
                raise ValueError("semantic encoder returned a zero vector")
            vectors[node["lexical_key"]] = [v / norm for v in vector]
            node["embedding_hash"] = sha256(canonical_json(vector).encode()).hexdigest()
    for pair in pairs:
        if pair["reason"] != "awaiting_similarity":
            continue
        sim = round(max(-1, min(1, sum(a * b for a, b in zip(vectors[pair["left"]], vectors[pair["right"]])))), policy["similarity_decimals"])
        pair["similarity"] = sim
        if sim >= policy["link_threshold"]:
            pair.update(outcome="linked", reason="compatible_event_and_embedding")
        elif sim <= policy["separate_threshold"]:
            pair.update(outcome="separate", reason="low_similarity")
        else:
            pair.update(outcome="unresolved", reason="similarity_ambiguous")
    # Complete-link, not connected components: A-B and B-C cannot imply A-C.
    groups = {n["lexical_key"]: {n["lexical_key"]} for n in nodes}
    links = {frozenset((p["left"], p["right"])) for p in pairs if p["outcome"] == "linked"}
    for pair in sorted(pairs, key=lambda p: (-(p["similarity"] or -1), p["left"], p["right"])):
        if pair["outcome"] != "linked":
            continue
        a, b = groups[pair["left"]], groups[pair["right"]]
        if a is b:
            continue
        if len(a | b) > policy["max_group_size"] or not all(frozenset((x, y)) in links for x in a for y in b):
            pair.update(outcome="unresolved", reason="complete_link_or_group_limit")
            continue
        merged = a | b
        for key in merged:
            groups[key] = merged
    node_map = {n["lexical_key"]: n for n in nodes}
    for node in nodes:
        group = groups[node["lexical_key"]]
        node["resolved_key"] = min(group, key=lambda k: (node_map[k]["trend_id"], k))
        if len(group) > 1:
            node.update(resolution_status="linked", reason="complete_link_group")
        elif degree[node["lexical_key"]]:
            related = [p for p in pairs if node["lexical_key"] in (p["left"], p["right"])]
            node.update(resolution_status="separate" if all(p["outcome"] == "separate" for p in related) else "unresolved",
                        reason="pair_decisions")
    return {"model_id": policy["model_id"], "model_revision": policy["model_revision"],
            "policy": policy, "clusters": nodes, "pairs": pairs,
            "embedded_clusters": len(inputs), "compared_pairs": len(pairs)}


def freeze_resolution(connection, run_id, policy, encoder, *, owner, claim_version, execution_time=None):
    started = monotonic()
    existing = connection.execute("SELECT * FROM scout_event_resolutions WHERE scout_evaluation_run_id=?", (run_id,)).fetchone()
    if existing is not None:
        return load_resolution(connection, run_id)
    source = connection.execute("SELECT * FROM scout_frozen_evidence WHERE scout_evaluation_run_id=?", (run_id,)).fetchone()
    if source is None or sha256(source["snapshot_json"].encode()).hexdigest() != source["snapshot_hash"]:
        raise ValueError("invalid frozen source input")
    at = moment(json.loads(source["snapshot_json"])["at"])
    result = resolve(observation_rows(connection, run_id), at, policy, encoder)
    payload = canonical_json(result)
    # Inference is finished before acquiring the write lock. A stale owner cannot freeze.
    connection.execute("BEGIN IMMEDIATE")
    with connection:
        row = connection.execute("SELECT status,claim_owner,claim_version,claimed_at,lease_expires_at FROM scout_evaluation_runs WHERE scout_evaluation_run_id=?", (run_id,)).fetchone()
        checked_at = (execution_time or moment(row["claimed_at"])) + timedelta(seconds=monotonic() - started)
        if row["status"] != "running" or row["claim_owner"] != owner or row["claim_version"] != claim_version or moment(row["lease_expires_at"]) <= checked_at:
            raise RuntimeError("Scout claim lost before semantic freeze")
        connection.execute(
            "INSERT INTO scout_event_resolutions(scout_evaluation_run_id,source_snapshot_hash,resolution_json,resolution_hash,created_at) VALUES (?,?,?,?,?)",
            (run_id, source["snapshot_hash"], payload, sha256(payload.encode()).hexdigest(), datetime.now(timezone.utc).isoformat()),
        )
    return result


def load_resolution(connection, run_id):
    row = connection.execute(
        "SELECT r.*,s.snapshot_hash FROM scout_event_resolutions r JOIN scout_frozen_evidence s USING(scout_evaluation_run_id) WHERE r.scout_evaluation_run_id=?", (run_id,)
    ).fetchone()
    if row is None or row["source_snapshot_hash"] != row["snapshot_hash"] or sha256(row["resolution_json"].encode()).hexdigest() != row["resolution_hash"]:
        raise ValueError("missing or corrupted frozen event resolution")
    return json.loads(row["resolution_json"])
