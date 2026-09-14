"""Concise operator-facing summaries for persisted detection runs."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any
import json


def summarize_scout(store: Any, result: Mapping[str, Any], *, limit: int = 10) -> dict[str, Any]:
    """Return useful Scout results without exposing internal audit payloads."""

    if limit < 0:
        raise ValueError("candidate summary limit must not be negative")
    summary = {
        key: value for key, value in result.items()
        if key != "prominence_populations"
    }
    run_id = result.get("run_id")
    if not isinstance(run_id, int) or limit == 0:
        summary["top_candidates"] = []
        return summary

    rows = store.connection.execute(
        "SELECT c.trend_candidate_id, c.rank, c.canonical_subject, c.score, "
        "c.eligibility_status, c.eligibility_reason, c.score_breakdown_json "
        "FROM trend_candidates c "
        "JOIN topic_snapshots s ON s.topic_snapshot_id=c.latest_topic_snapshot_id "
        "WHERE s.scout_evaluation_run_id=? "
        "ORDER BY c.rank ASC, c.trend_candidate_id ASC LIMIT ?",
        (run_id, limit),
    ).fetchall()
    candidates: list[dict[str, Any]] = []
    for row in rows:
        breakdown = json.loads(row["score_breakdown_json"])
        candidates.append({
            "trend_candidate_id": int(row["trend_candidate_id"]),
            "rank": row["rank"],
            "subject": row["canonical_subject"],
            "score": row["score"],
            "status": row["eligibility_status"],
            "reason": row["eligibility_reason"],
            "breadth": breakdown.get("breadth"),
            "source_count": len(breakdown.get("source_components", [])),
        })
    summary["top_candidates"] = candidates
    return summary
