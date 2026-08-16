"""Build ranked, explainable reports from persisted topic snapshots."""

from intelligence.scoring import TrendScorer


def ranked_candidates(database, minimum_score: float = 0.0, limit: int = 20):
    scorer = TrendScorer()
    candidates = []
    for topic in database.snapshot_topics():
        history = database.topic_history(topic)
        if not history:
            continue
        candidate = scorer.score(topic, history)
        if candidate.score >= minimum_score:
            candidates.append(candidate)
    return sorted(candidates, key=lambda candidate: candidate.score, reverse=True)[:limit]


def select_candidates(database, minimum_score: float = 0.0, top_n: int = 5):
    """Return the small, score-qualified shortlist for determination."""
    return ranked_candidates(database, minimum_score=minimum_score, limit=top_n)


def format_report(candidates) -> str:
    if not candidates:
        return "No trend candidates available."
    lines = []
    for index, candidate in enumerate(candidates, start=1):
        breakdown = ", ".join(f"{key}={value:.2f}" for key, value in candidate.score_breakdown.items())
        sources = ", ".join(candidate.supporting_sources) or "unknown"
        lines.append(f"{index}. {candidate.lifecycle_stage} {candidate.topic} score={candidate.score:.2f}")
        lines.append(f"   sources: {sources}")
        lines.append(f"   evidence: {breakdown}")
    return "\n".join(lines)
