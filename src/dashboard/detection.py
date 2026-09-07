"""Read-only compact detection dashboard for detection_dashboard_schema_v1."""

from __future__ import annotations

from datetime import datetime
from html import escape
from typing import Any
from urllib.parse import urlencode
import json
import sqlite3


def _cell(value: Any) -> str:
    return escape("" if value is None else str(value))


def _json(value: Any) -> str:
    try:
        parsed = json.loads(value) if isinstance(value, str) else value
        return _cell(json.dumps(parsed, ensure_ascii=False, separators=(",", ":"), sort_keys=True))
    except (TypeError, json.JSONDecodeError):
        return _cell(value)


def _timestamp(value: Any) -> str:
    """Display persisted UTC timestamps without fractional seconds or an offset."""

    if value is None or value == "":
        return "—"
    text = str(value)
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return _cell(text)
    return parsed.strftime("%Y-%m-%dT%H:%M:%S")


def _rows(items: list[sqlite3.Row], renderers, empty: str, columns: int) -> str:
    if not items:
        return f"<tr><td colspan='{columns}' class='empty'>{_cell(empty)}</td></tr>"
    return "".join(
        "<tr>" + "".join(f"<td>{renderer(item)}</td>" for renderer in renderers) + "</tr>"
        for item in items
    )


def _literal_like(value: str) -> str:
    return "%" + value.casefold().replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"


def render_detection_dashboard(
    connection: sqlite3.Connection,
    *,
    query: str = "",
    source: str = "",
    status: str = "",
    page: int = 1,
) -> str:
    """Render one consistent SQLite snapshot without mutating it."""

    query = query.strip()[:200]
    source = source.strip()[:100]
    # The compact landing view intentionally shows only shortlisted candidates:
    # they are the records handed to the next intake/determination boundary.
    # Keep the argument for URL compatibility with earlier dashboard links.
    del status
    page = max(1, min(int(page), 10_000))
    page_size = 50
    search_pattern = _literal_like(query)

    connection.execute("BEGIN")
    try:
        release = connection.execute(
            "SELECT r.configuration_release_id "
            "FROM configuration_activations a JOIN configuration_releases r "
            "ON r.configuration_release_id=a.configuration_release_id "
            "WHERE a.scope_key='global' AND a.status='active'"
        ).fetchone()
        active_release_id = int(release["configuration_release_id"]) if release else -1
        counts = {
            "detection_source_instances": int(connection.execute(
                "SELECT COUNT(*) FROM detection_source_instances "
                "WHERE configuration_release_id=? AND enabled=1",
                (active_release_id,),
            ).fetchone()[0]),
            "source_collection_attempts": int(connection.execute(
                "SELECT COUNT(*) FROM source_collection_attempts WHERE configuration_release_id=?",
                (active_release_id,),
            ).fetchone()[0]),
            "trend_observations": int(connection.execute(
                "SELECT COUNT(*) FROM trend_observations o "
                "JOIN detection_source_instances s "
                "ON s.detection_source_instance_id=o.source_instance_id "
                "WHERE s.configuration_release_id=?",
                (active_release_id,),
            ).fetchone()[0]),
            "trend_candidates": int(connection.execute(
                "SELECT COUNT(*) FROM trend_candidates c JOIN topic_snapshots s "
                "ON s.topic_snapshot_id=c.latest_topic_snapshot_id "
                "JOIN scout_evaluation_runs r "
                "ON r.scout_evaluation_run_id=s.scout_evaluation_run_id "
                "WHERE r.configuration_release_id=?",
                (active_release_id,),
            ).fetchone()[0]),
        }
        candidate_from = (
            " FROM trend_candidates c "
            "JOIN topic_snapshots s ON s.topic_snapshot_id=c.latest_topic_snapshot_id "
            "JOIN scout_evaluation_runs er "
            "ON er.scout_evaluation_run_id=s.scout_evaluation_run_id "
            "LEFT JOIN content_threads t ON t.thread_id=c.selected_thread_id "
            "LEFT JOIN intake_requests i ON i.thread_id=t.thread_id "
        )
        candidate_where = (
            "WHERE er.configuration_release_id=? "
            "AND c.eligibility_status='selected' "
            "AND (?='' OR lower(c.canonical_subject) LIKE ? ESCAPE '\\' "
            "OR lower(c.opportunity_identity) LIKE ? ESCAPE '\\') "
            "AND (?='' OR EXISTS (SELECT 1 FROM candidate_observation_memberships m "
            "JOIN trend_observations fo ON fo.trend_observation_id=m.trend_observation_id "
            "JOIN detection_source_instances fs "
            "ON fs.detection_source_instance_id=fo.source_instance_id "
            "WHERE m.topic_snapshot_id=c.latest_topic_snapshot_id AND fs.stable_id=?)) "
        )
        candidate_parameters = (
            active_release_id, query, search_pattern, search_pattern,
            source, source,
        )
        filtered_candidate_count = int(connection.execute(
            "SELECT COUNT(*)" + candidate_from + candidate_where,
            candidate_parameters,
        ).fetchone()[0])

        observation_from = (
            " FROM trend_observations o "
            "JOIN detection_source_instances s "
            "ON s.detection_source_instance_id=o.source_instance_id "
            "JOIN trends t ON t.trend_id=o.trend_id "
        )
        observation_where = (
            "WHERE s.configuration_release_id=? AND (?='' OR s.stable_id=?) "
            "AND (?='' OR lower(o.title) LIKE ? ESCAPE '\\' "
            "OR lower(t.canonical_key) LIKE ? ESCAPE '\\') "
        )
        observation_parameters = (
            active_release_id, source, source, query, search_pattern, search_pattern,
        )
        filtered_observation_count = int(connection.execute(
            "SELECT COUNT(*)" + observation_from + observation_where,
            observation_parameters,
        ).fetchone()[0])
        max_page = max(
            1,
            (max(filtered_candidate_count, filtered_observation_count) + page_size - 1)
            // page_size,
        )
        page = min(page, max_page)
        offset = (page - 1) * page_size

        candidates = connection.execute(
            "SELECT c.*, s.evidence_snapshot_json, s.created_at AS snapshot_at, "
            "t.thread_id, i.intake_request_id, i.status AS intake_status "
            + candidate_from
            + candidate_where
            + "ORDER BY CASE c.eligibility_status "
            "WHEN 'selected' THEN 0 WHEN 'eligible' THEN 1 WHEN 'deferred_by_budget' THEN 2 ELSE 3 END, "
            "c.score DESC, c.updated_at DESC, c.trend_candidate_id DESC LIMIT ? OFFSET ?",
            (*candidate_parameters, page_size, offset),
        ).fetchall()
        sources = connection.execute(
            "SELECT s.*, a.status AS attempt_status, a.scheduled_for, a.collected_at, "
            "a.item_count, a.complete, a.failure_category, a.failure_detail, "
            "h.classification AS health_classification, h.reason AS health_reason, "
            "h.latency_ms FROM detection_source_instances s "
            "LEFT JOIN source_collection_attempts a ON a.source_collection_attempt_id=("
            "SELECT a2.source_collection_attempt_id FROM source_collection_attempts a2 "
            "WHERE a2.source_instance_id=s.detection_source_instance_id "
            "ORDER BY a2.created_at DESC, a2.source_collection_attempt_id DESC LIMIT 1) "
            "LEFT JOIN source_health h ON h.source_collection_attempt_id=a.source_collection_attempt_id "
            "WHERE s.configuration_release_id=(SELECT configuration_release_id "
            "FROM configuration_activations WHERE scope_key='global' AND status='active') "
            "ORDER BY s.stable_id"
        ).fetchall()
        observations = connection.execute(
            "SELECT o.trend_observation_id, o.title, o.canonical_url, o.activity, o.rank, "
            "o.provider_time, o.effective_observed_at, o.collected_at, o.payload_json, "
            "s.stable_id, s.provider_name, s.source_kind, t.canonical_key "
            + observation_from
            + observation_where
            + "ORDER BY o.collected_at DESC, o.trend_observation_id DESC LIMIT ? OFFSET ?",
            (*observation_parameters, page_size, offset),
        ).fetchall()
        evaluations = connection.execute(
            "SELECT * FROM scout_evaluation_runs "
            "ORDER BY evaluation_slot_start DESC, scout_evaluation_run_id DESC LIMIT 20"
        ).fetchall()
        workers = connection.execute(
            "SELECT * FROM worker_heartbeats ORDER BY worker_type, instance_id"
        ).fetchall()
        worker_runs = connection.execute(
            "SELECT * FROM worker_runs "
            "ORDER BY started_at DESC, worker_run_id DESC LIMIT 50"
        ).fetchall()
    finally:
        connection.rollback()

    source_options = "".join(
        f"<option value='{_cell(row['stable_id'])}'"
        f"{' selected' if row['stable_id'] == source else ''}>"
        f"{_cell(row['provider_name'])} · {_cell(row['stable_id'])}</option>"
        for row in sources
    )
    filters = (
        "<form class='filters' method='get' action='/'>"
        f"<label>Search<input name='q' maxlength='200' value='{_cell(query)}' "
        "placeholder='title, canonical key, or identity'></label>"
        f"<label>Source<select name='source'><option value=''>All sources</option>"
        f"{source_options}</select></label>"
        "<button type='submit'>Apply filters</button><a class='reset' href='/'>Reset</a>"
        "</form>"
    )
    link_parameters = {
        key: value for key, value in {"q": query, "source": source}.items()
        if value
    }

    def page_link(target: int, label: str) -> str:
        parameters = {**link_parameters, "page": target}
        return f"<a href='/?{_cell(urlencode(parameters))}'>{_cell(label)}</a>"

    pagination_parts = []
    if page > 1:
        pagination_parts.append(page_link(page - 1, "← Previous"))
    pagination_parts.append(f"<span>Page {page} of {max_page}</span>")
    if page < max_page:
        pagination_parts.append(page_link(page + 1, "Next →"))
    pagination = "<nav class='pagination'>" + "".join(pagination_parts) + "</nav>"

    candidate_rows = _rows(candidates, [
        lambda row: _cell(row["canonical_subject"]),
        lambda row: f"{float(row['score']):.4f}",
        lambda row: _cell(row["eligibility_reason"]),
        lambda row: _timestamp(row["snapshot_at"]),
        lambda row: _cell(row["thread_id"] or "—"),
    ], "No shortlisted opportunities yet.", 5)
    source_rows = _rows(sources, [
        lambda row: _cell(row["stable_id"]),
        lambda row: _cell(row["provider_name"]),
        lambda row: _cell(row["source_kind"]),
        lambda row: _cell(row["health_classification"] or row["attempt_status"] or "not_collected"),
        lambda row: _timestamp(row["collected_at"] or row["scheduled_for"]),
        lambda row: _cell(row["item_count"] if row["item_count"] is not None else "—"),
        lambda row: _cell(row["health_reason"] or row["failure_category"] or "—"),
    ], "No active source configuration.", 7)
    observation_rows = _rows(observations, [
        lambda row: _cell(row["provider_name"]),
        lambda row: (
            f"<a href='{_cell(row['canonical_url'])}' rel='noreferrer' target='_blank'>{_cell(row['title'])}</a>"
            if row["canonical_url"] else _cell(row["title"])
        ),
        lambda row: _cell(row["rank"] or "—"),
        lambda row: f"{float(row['activity']):.3f}",
        lambda row: _timestamp(row["collected_at"]),
    ], "Run source collection to populate the ingestion feed.", 5)
    evaluation_rows = _rows(evaluations, [
        lambda row: str(row["scout_evaluation_run_id"]),
        lambda row: _timestamp(row["evaluation_slot_start"]),
        lambda row: _cell(row["status"]),
        lambda row: _timestamp(row["input_frozen_at"]),
        lambda row: _json(row["aggregate_counts_json"]),
        lambda row: _cell(row["failure_category"] or "—"),
    ], "No Scout evaluation has run yet.", 6)
    worker_rows = _rows(workers, [
        lambda row: _cell(row["worker_type"]), lambda row: _cell(row["state"]),
        lambda row: _timestamp(row["last_seen_at"]), lambda row: _cell(row["safe_summary"]),
    ], "No worker heartbeat has been recorded yet.", 4)
    worker_run_rows = _rows(worker_runs, [
        lambda row: str(row["worker_run_id"]),
        lambda row: _cell(row["worker_type"]),
        lambda row: _cell(row["claim_type"] or "—"),
        lambda row: _cell(row["claim_id"] or "—"),
        lambda row: _cell(row["status"]),
        lambda row: _timestamp(row["started_at"]),
        lambda row: _timestamp(row["completed_at"]),
        lambda row: _cell(row["safe_summary"] or row["safe_error"] or "—"),
    ], "No substantive worker run has been recorded yet.", 8)
    return f"""<!doctype html>
<html lang='en'><head><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'>
<meta http-equiv='refresh' content='10'><title>Content Factory</title>
<style>
:root{{--ink:#17202a;--muted:#65717c;--line:#dce3e8;--paper:#fff;--wash:#f4f6f8;--accent:#136f63}}
*{{box-sizing:border-box}} body{{margin:0;background:var(--wash);color:var(--ink);font:12px/1.25 system-ui,-apple-system,sans-serif}}
main{{width:100%;padding:6px 8px}} h2{{font-size:13px;line-height:1.15;margin:0;font-weight:700}} h3{{font-size:12px;margin:0}}
.filters{{display:flex;gap:5px;align-items:end;flex-wrap:wrap;background:var(--paper);border:1px solid var(--line);padding:5px;margin:0 0 5px}}
.filters label{{display:grid;gap:2px;color:var(--muted);font-size:11px}} .filters input{{width:min(300px,46vw)}} input,select,button{{font:inherit;padding:3px 5px;border:1px solid #b9c4cb;border-radius:3px;background:#fff}}
button{{background:var(--accent);color:#fff;border-color:var(--accent);cursor:pointer}} .reset{{padding:4px 2px}}
.metrics{{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:4px;margin-bottom:5px}} .metric{{background:var(--paper);border:1px solid var(--line);padding:4px 6px;color:var(--muted)}}
.metric b{{display:inline;color:var(--ink);font-size:14px;margin-left:5px}} .panel{{overflow:auto;background:var(--paper);border:1px solid var(--line)}}
.split{{display:grid;grid-template-columns:minmax(0,1fr) minmax(0,1fr);gap:5px;margin-bottom:5px}} .section-head{{display:flex;justify-content:space-between;align-items:baseline;padding:4px 5px;background:#eaf0f3;border:1px solid var(--line);border-bottom:0}}
.count{{color:var(--muted);font-size:11px}} .operations{{display:grid;grid-template-columns:1fr 1fr;gap:5px;margin-top:5px}}
table{{width:100%;border-collapse:collapse;white-space:nowrap}} th,td{{padding:3px 5px;text-align:left;vertical-align:top;border-bottom:1px solid var(--line)}} th{{background:#f0f4f6;font-size:11px;color:#43505a}}
.ingestion-table td:nth-child(2),.opportunity-table td:first-child{{white-space:normal;min-width:180px}} tr:last-child td{{border-bottom:0}} .empty{{padding:12px;text-align:center;color:var(--muted)}}
details{{min-width:120px}} summary{{cursor:pointer;color:var(--accent)}} pre{{white-space:pre-wrap;max-width:420px;max-height:180px;overflow:auto;background:#f7f8f9;padding:5px;margin:3px 0}}
a{{color:#0969a2}} .pagination{{display:flex;gap:10px;align-items:center;margin:5px 0;color:var(--muted)}}
@media(max-width:900px){{.split,.operations{{grid-template-columns:1fr}}}} @media(max-width:560px){{main{{padding:4px}}.metrics{{grid-template-columns:repeat(2,1fr)}}.filters input{{width:260px}}}}
</style></head><body>
<main>{filters}
<div class='metrics'>
<div class='metric'>Enabled sources<b>{counts['detection_source_instances']}</b></div>
<div class='metric'>Collection attempts<b>{counts['source_collection_attempts']}</b></div>
<div class='metric'>Ingested observations<b>{counts['trend_observations']}</b></div>
<div class='metric'>Trend candidates<b>{counts['trend_candidates']}</b></div>
</div>
<div class='split'>
<section><div class='section-head'><h2>Ingestion feed</h2><span class='count'>{filtered_observation_count} item(s)</span></div><div class='panel'><table class='ingestion-table'><tr><th>Source</th><th>Title</th><th>Rank</th><th>Activity</th><th>Ingested</th></tr>{observation_rows}</table></div></section>
<section><div class='section-head'><h2>Opportunities</h2><span class='count'>{filtered_candidate_count} selected</span></div><div class='panel'><table class='opportunity-table'><tr><th>Subject</th><th>Score</th><th>Selection reason</th><th>Evaluated</th><th>Thread</th></tr>{candidate_rows}</table></div></section>
</div>
{pagination}
<div class='operations'>
<section><div class='section-head'><h2>Source health</h2></div><div class='panel'><table><tr><th>Source</th><th>Provider</th><th>Kind</th><th>Health</th><th>Latest</th><th>Items</th><th>Reason</th></tr>{source_rows}</table></div></section>
<section><div class='section-head'><h2>Scout evaluations</h2></div><div class='panel'><table><tr><th>Run</th><th>Slot</th><th>Status</th><th>Frozen</th><th>Counts</th><th>Error</th></tr>{evaluation_rows}</table></div></section>
<section><div class='section-head'><h2>Workers</h2></div><div class='panel'><table><tr><th>Worker</th><th>State</th><th>Last seen</th><th>Summary</th></tr>{worker_rows}</table></div></section>
<section><div class='section-head'><h2>Recent worker runs</h2></div><div class='panel'><table><tr><th>Run</th><th>Worker</th><th>Claim type</th><th>Claim</th><th>Status</th><th>Started</th><th>Completed</th><th>Result</th></tr>{worker_run_rows}</table></div></section>
</div>
</main></body></html>"""
