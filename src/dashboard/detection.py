"""Read-only Detection overview for the current application schema."""

from __future__ import annotations

from datetime import datetime, timezone
from html import escape
from typing import Any
from urllib.parse import urlencode
import json
import sqlite3
from .evidence import link, public_link
from .flow import render_progression, CLUSTER_STATES


from .refresh import AUTO_REFRESH_SCRIPT, AUTO_REFRESH_CSP
from common.timestamps import parse_timestamp, serialize_timestamp, utc_datetime_now


def _worker_freshness(row, at: datetime) -> str:
    """Heartbeat age is separate from the last reported state or claim health."""
    thresholds = {
        "trend_source_collector": (1200, 2700),
        "trend_scout_shortlist": (1200, 2700),
        "idea_intake": (60, 180),
        "determination": (60, 180),
        "pipeline_runner": (60, 180),
        "adaptation": (60, 180),
        "visual_renderer": (60, 180),
        "posting_agent": (30, 90),
        "cleanup": (600, 1200),
        "publication_reconciliation": (600, 1200),
        "storage_monitor": (600, 1200),
        "capability_readiness": (600, 1200),
        "maintenance": (26 * 3600, 50 * 3600),
    }
    limits = thresholds.get(row["worker_type"])
    if limits is None:
        return "unknown cadence"
    try:
        seen = parse_timestamp(row["last_seen_at"])
        age = (at - seen).total_seconds()
    except (TypeError, ValueError):
        return "invalid heartbeat time"
    if age < 0:
        return "clock skew"
    warn_after, stale_after = limits
    return (
        "stale heartbeat" if age > stale_after
        else "late heartbeat" if age > warn_after
        else "fresh heartbeat"
    )


def _cell(value: Any) -> str:
    return escape("" if value is None else str(value))


def _worker_summary(row):
    summary = row['safe_summary'] or '—'
    if row['worker_type'] == 'trend_scout_shortlist':
        # Translate existing operational summaries for display, never rewrite evidence.
        summary = summary.replace('candidate(s)', 'cluster(s)')
    return _cell(summary)


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
        parsed = parse_timestamp(text)
    except ValueError:
        return _cell(text)
    return serialize_timestamp(parsed)


def _rows(items: list[sqlite3.Row], renderers, empty: str, columns: int) -> str:
    if not items:
        return f"<tr><td colspan='{columns}' class='empty'>{_cell(empty)}</td></tr>"
    result = []
    for item in items:
        identity = next((key for key in ('trend_candidate_id','trend_observation_id','scout_evaluation_run_id',
                         'detection_source_instance_id','worker_run_id','worker_heartbeat_id') if key in item.keys()), None)
        key = f" id='{identity}-{int(item[identity])}'" if identity else ''
        result.append('<tr' + key + '>' + ''.join(f'<td>{renderer(item)}</td>' for renderer in renderers) + '</tr>')
    return ''.join(result)


def _literal_like(value: str) -> str:
    return "%" + value.casefold().replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"


def render_detection_dashboard(connection, **filters):
    owns_snapshot = not connection.in_transaction
    if owns_snapshot:
        connection.execute('BEGIN')
    try:
        return _render_detection_dashboard(connection, **filters)
    finally:
        if owns_snapshot:
            connection.rollback()


def _render_detection_dashboard(
    connection: sqlite3.Connection,
    *,
    query: str = "",
    source: str = "",
    status: str = "",
    stage: str = "clusters",
    raw_page: int = 1,
    cluster_page: int = 1,
    opportunity_page: int = 1,
    job_page: int = 1,
    cluster_sort: str = "score_desc",
) -> str:
    """Render one consistent SQLite snapshot without mutating it."""

    query = query.strip()[:200]
    source = source.strip()[:100]
    status = status.strip()[:40]
    stage = stage if stage in {"raw", "clusters", "opportunities", "jobs"} else "clusters"
    raw_page = max(1, min(int(raw_page), 10_000))
    cluster_page = max(1, min(int(cluster_page), 10_000))
    opportunity_page = max(1, min(int(opportunity_page), 10_000))
    job_page = max(1, min(int(job_page), 10_000))
    cluster_sort = cluster_sort if cluster_sort in {"score_desc", "recent"} else "score_desc"
    page_size = 50
    search_pattern = _literal_like(query)

    owns_snapshot = not connection.in_transaction
    if owns_snapshot:
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
        )
        candidate_where = (
            "WHERE er.configuration_release_id=? "
            "AND (?='' OR c.eligibility_status=?) "
            "AND (?='' OR lower(c.canonical_subject) LIKE ? ESCAPE '\\' "
            "OR lower(c.opportunity_identity) LIKE ? ESCAPE '\\') "
            "AND (?='' OR EXISTS (SELECT 1 FROM candidate_observation_memberships m "
            "JOIN trend_observations fo ON fo.trend_observation_id=m.trend_observation_id "
            "JOIN detection_source_instances fs "
            "ON fs.detection_source_instance_id=fo.source_instance_id "
            "WHERE m.topic_snapshot_id=c.latest_topic_snapshot_id AND fs.stable_id=?)) "
        )
        candidate_parameters = (
            active_release_id, status, status, query, search_pattern, search_pattern,
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
        raw_page = min(raw_page, max(1, (filtered_observation_count + page_size - 1) // page_size))
        cluster_page = min(cluster_page, max(1, (filtered_candidate_count + page_size - 1) // page_size))
        cluster_order = (
            "c.score DESC, c.updated_at DESC, c.trend_candidate_id DESC"
            if cluster_sort == "score_desc" else
            "c.updated_at DESC, c.trend_candidate_id DESC"
        )

        candidates = connection.execute(
            "SELECT c.*, s.evidence_snapshot_json, s.created_at AS snapshot_at, "
            "t.thread_id "
            + candidate_from
            + candidate_where
            + "ORDER BY " + cluster_order + " LIMIT ? OFFSET ?",
            (*candidate_parameters, page_size, (cluster_page - 1) * page_size),
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
            (*observation_parameters, page_size, (raw_page - 1) * page_size),
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
        if owns_snapshot:
            connection.rollback()

    source_options = "".join(
        f"<option value='{_cell(row['stable_id'])}'"
        f"{' selected' if row['stable_id'] == source else ''}>"
        f"{_cell(row['provider_name'])} · {_cell(row['stable_id'])}</option>"
        for row in sources
    )
    filters = (
        "<form class='filters' method='get' action='/'>"
        f"<input type='hidden' name='stage' value='{_cell(stage)}'><input type='hidden' name='cluster_sort' value='{_cell(cluster_sort)}'>"
        f"<label>Search<input name='q' maxlength='200' value='{_cell(query)}' "
        "placeholder='title, canonical key, or identity'></label>"
        f"<label>Source<select name='source'><option value=''>All sources</option>"
        f"{source_options}</select></label>"
        f"<label>Cluster Selection state<select name='status'><option value=''>All Clusters</option>{''.join(f'<option value="{v}"' + (' selected' if v == status else '') + f'>{v}</option>' for v in CLUSTER_STATES)}</select></label>"
        "<button type='submit'>Apply filters</button><a class='reset' href='/'>Reset</a>"
        "</form>"
    )
    progression = render_progression(connection, observations, candidates,
        raw_count=filtered_observation_count, cluster_count=filtered_candidate_count,
        stage=stage, query=query, source=source, status=status, raw_page=raw_page,
        cluster_page=cluster_page, opportunity_page=opportunity_page, job_page=job_page,
        cluster_sort=cluster_sort)
    source_rows = _rows(sources, [
        lambda row: _cell(row["stable_id"]),
        lambda row: _cell(row["provider_name"]),
        lambda row: _cell(row["source_kind"]),
        lambda row: _cell(row['attempt_status'] or 'no attempt'),
        lambda row: _cell(row["health_classification"] or "no health evidence"),
        lambda row: _timestamp(row["collected_at"] or row["scheduled_for"]),
        lambda row: _cell(row["item_count"] if row["item_count"] is not None else "—"),
        lambda row: _cell(" · ".join(str(row[key]) for key in ("health_reason","failure_category","failure_detail") if row[key]) or "—"),
    ], "No active source configuration.", 8)
    evaluation_rows = _rows(evaluations, [
        lambda row: link("#" + str(row["scout_evaluation_run_id"]), evaluation_id=row["scout_evaluation_run_id"]),
        lambda row: _timestamp(row["evaluation_slot_start"]),
        lambda row: _cell(row["status"]),
        lambda row: _timestamp(row["input_frozen_at"]),
        lambda row: _json({('cluster_count' if k=='candidate_count' else k):v for k,v in json.loads(row['aggregate_counts_json']).items()}),
        lambda row: _cell(row["failure_category"] or "—"),
    ], "No Scout evaluation has run yet.", 6)
    worker_rows = _rows(workers, [
        lambda row: _cell(row["worker_type"]), lambda row: _cell(row["state"] + " / " + _worker_freshness(row, utc_datetime_now())),
        lambda row: _timestamp(row["last_seen_at"]), _worker_summary,
    ], "No worker heartbeat has been recorded yet.", 4)
    worker_run_rows = _rows(worker_runs, [
        lambda row: str(row["worker_run_id"]),
        lambda row: _cell(row["worker_type"]),
        lambda row: _cell(row["claim_type"] or "—"),
        lambda row: _cell(row["claim_id"] or "—"),
        lambda row: _cell(row["status"]),
        lambda row: _timestamp(row["started_at"]),
        lambda row: _timestamp(row["completed_at"]),
        lambda row: _worker_summary(row) if row['safe_summary'] else _cell(row['safe_error'] or '—'),
    ], "No substantive worker run has been recorded yet.", 8)
    return f"""<!doctype html>
<html lang='en'><head><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'>
<title>Content Factory</title><script>{AUTO_REFRESH_SCRIPT}</script>
<style>
:root{{--ink:#17202a;--muted:#65717c;--line:#dce3e8;--paper:#fff;--wash:#f4f6f8;--accent:#136f63}}
*{{box-sizing:border-box}} body{{margin:0;background:var(--wash);color:var(--ink);font:12px/1.25 system-ui,-apple-system,sans-serif}}
main{{width:100%;padding:6px 8px}} h2{{font-size:13px;line-height:1.15;margin:0;font-weight:700}} h3{{font-size:12px;margin:0}}
.filters{{display:flex;gap:5px;align-items:end;flex-wrap:wrap;background:var(--paper);border:1px solid var(--line);padding:5px;margin:0 0 5px}}
.filters label{{display:grid;gap:2px;color:var(--muted);font-size:11px}} .filters input{{width:min(300px,46vw)}} input,select,button,textarea{{font:inherit;padding:3px 5px;border:1px solid #b9c4cb;border-radius:3px;background:#fff}} textarea{{display:block;width:min(720px,95%);min-height:70px;margin:.35rem 0}} .workflow form{{margin:.6rem 0 1rem}}
button{{background:var(--accent);color:#fff;border-color:var(--accent);cursor:pointer}} .reset{{padding:4px 2px}}
.metrics{{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:4px;margin-bottom:5px}} .metric{{background:var(--paper);border:1px solid var(--line);padding:4px 6px;color:var(--muted)}}
.metric b{{display:inline;color:var(--ink);font-size:14px;margin-left:5px}} .panel{{overflow:auto;background:var(--paper);border:1px solid var(--line)}}
.split{{display:grid;grid-template-columns:minmax(0,1fr) minmax(0,1fr);gap:5px;margin-bottom:5px}} .section-head{{display:flex;justify-content:space-between;align-items:baseline;padding:4px 5px;background:#eaf0f3;border:1px solid var(--line);border-bottom:0}}
.count{{color:var(--muted);font-size:11px}} .operations{{display:grid;grid-template-columns:1fr 1fr;gap:5px;margin-top:5px}}
table{{width:100%;table-layout:fixed;border-collapse:collapse}} th,td{{padding:3px 5px;text-align:left;vertical-align:top;border-bottom:1px solid var(--line);overflow-wrap:anywhere}} th{{background:#f0f4f6;font-size:11px;color:#43505a}}
.ingestion-table th:nth-child(1){{width:15%}} .ingestion-table th:nth-child(2){{width:42%}} .ingestion-table th:nth-child(3){{width:8%}} .ingestion-table th:nth-child(4){{width:13%}} .ingestion-table th:nth-child(5){{width:22%}} .opportunity-table th:nth-child(1){{width:35%}} .opportunity-table th:nth-child(2){{width:8%}} .opportunity-table th:nth-child(3){{width:24%}} .opportunity-table th:nth-child(4){{width:20%}} .opportunity-table th:nth-child(5){{width:13%}} tr:last-child td{{border-bottom:0}} .empty{{padding:12px;text-align:center;color:var(--muted)}}
details{{min-width:120px}} summary{{cursor:pointer;color:var(--accent)}} pre{{white-space:pre-wrap;max-width:420px;max-height:180px;overflow:auto;background:#f7f8f9;padding:5px;margin:3px 0}}
a{{color:#0969a2}} .pagination{{display:flex;gap:10px;align-items:center;margin:5px 0;color:var(--muted)}}
@media(max-width:640px){{.operations{{grid-template-columns:1fr}}}} @media(max-width:560px){{main{{padding:4px}}.metrics{{grid-template-columns:repeat(2,1fr)}}.filters input{{width:260px}}}}
body{{font-size:14px;line-height:1.5;overflow-wrap:anywhere}} .pagination{{flex-wrap:wrap}} main{{max-width:1680px;margin:auto;padding:24px}}
h1{{margin:0;font-size:28px}} h2{{font-size:20px;margin:8px 0}} h3{{font-size:16px;margin:8px 0}} h4{{font-size:14px;margin:14px 0 6px}}
header{{margin-bottom:24px}} .card{{background:white;border:1px solid var(--line);border-radius:10px;padding:20px;margin:20px 0}}
.route-grid{{display:grid;grid-template-columns:repeat(auto-fit,minmax(260px,1fr));gap:12px}} .route{{padding:14px;border:1px solid var(--line);border-radius:8px;background:#f8fafb}}
.selected{{border-top:4px solid var(--accent)}} .blocked{{border-top:4px solid #bc5723}} .notice{{background:#e9f5f0;padding:12px;border-radius:6px}}
dt{{font-weight:600;color:#43505a}} dd{{margin:0 0 8px;overflow-wrap:anywhere}} .brief{{display:grid;grid-template-columns:160px 1fr;gap:8px}}
th,td{{padding:8px}} pre{{max-width:100%;max-height:480px;font-size:12px;padding:12px}} textarea{{width:100%;min-height:96px;padding:10px}}
button{{padding:8px 14px}} details{{margin:8px 0}} .conversation p{{white-space:pre-wrap}} .hint,small{{color:var(--muted)}} .filters{{padding:12px;gap:12px}}
@media(max-width:900px){{.split,.operations{{grid-template-columns:1fr}} main{{padding:12px}} .brief{{grid-template-columns:1fr}}}}
.stage-tabs{{display:flex;gap:4px;margin:6px 0;overflow:auto}} .stage-tabs a{{min-width:145px;padding:7px 9px;background:#fff;border:1px solid var(--line);text-decoration:none;color:var(--ink)}} .stage-tabs a.active{{border-color:var(--accent);background:#e9f5f0}} .stage-tabs b{{float:right;font-variant-numeric:tabular-nums}}
.flow-stage{{min-width:0;background:#fff;border:1px solid var(--line);padding:6px;overflow:auto}} .stage-head{{display:flex;justify-content:space-between;gap:8px;align-items:center}} .stage-head form{{display:flex;gap:4px;align-items:center}} .stage-table{{font-size:12px;min-width:900px}} .stage-table th,.stage-table td{{padding:5px 6px;white-space:nowrap}} .stage-table .truncate{{max-width:310px;overflow:hidden;text-overflow:ellipsis}}
.operations>section{{min-width:0}} .operations table{{min-width:640px}}
</style></head><body>
<main><header><h1>Content Factory</h1>
<nav class='pagination'><a href='/?view=detection'>Detection</a><a href='/?view=threads'>Ideas &amp; threads</a><a href='/?view=operations#queues'>Queues &amp; operations</a><a href=''>Refresh</a></nav>
<p class='hint' id='refresh-status'>Times: UTC</p></header><div id='detail-slot'></div><section id='detection'>{filters}
<div class='metrics'>
<div class='metric'>Enabled sources<b>{counts['detection_source_instances']}</b></div>
<div class='metric'>Collection attempts<b>{counts['source_collection_attempts']}</b></div>
<div class='metric'>Raw Feed Items (observations)<b>{counts['trend_observations']}</b></div>
<div class='metric'>Scored Clusters<b>{counts['trend_candidates']}</b></div>
</div>
{progression}
</section><div class='operations' id='operations'>
<section><div class='section-head'><h2>Source / Feed operations</h2></div><div class='panel'><table><tr><th>Source</th><th>Provider</th><th>Kind</th><th>Collection attempt</th><th>Source health</th><th>Latest</th><th>Items</th><th>Reason</th></tr>{source_rows}</table></div></section>
<section><div class='section-head'><h2>Scout evaluations</h2></div><div class='panel'><table><tr><th>Run</th><th>Slot</th><th>Status</th><th>Frozen</th><th>Counts</th><th>Error</th></tr>{evaluation_rows}</table></div></section>
<section><div class='section-head'><h2>Workers</h2></div><div class='panel'><table><tr><th>Worker</th><th>State</th><th>Last seen</th><th>Summary</th></tr>{worker_rows}</table></div></section>
<section><div class='section-head'><h2>Recent worker runs</h2></div><div class='panel'><table><tr><th>Run</th><th>Worker</th><th>Claim type</th><th>Claim</th><th>Status</th><th>Started</th><th>Completed</th><th>Result</th></tr>{worker_run_rows}</table></div></section>
</div>
</main></body></html>"""
