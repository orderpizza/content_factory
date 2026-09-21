"""Escaped, bounded evidence views; no calls to workers or providers."""
from html import escape
import json
from urllib.parse import urlencode, urlsplit
from common.diagnostics import safe_diagnostic
from common.storage import storage_status, storage_recovery


def text(value):
    return escape(str(value) if value is not None else "—")


def json_detail(label, value, *, diagnostic=False):
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except ValueError:
            pass
    body = json.dumps(value, ensure_ascii=False, indent=2)
    if diagnostic:
        body = safe_diagnostic(body, limit=100000)
    return f"<details><summary>{text(label)}</summary><pre>{text(body)}</pre></details>"


def link(label, **query):
    return f"<a href='/?{text(urlencode(query))}'>{text(label)}</a>"


def public_link(title, url):
    try:
        valid = urlsplit(url or "").scheme in {"https", "http"} and not urlsplit(url or "").username
    except ValueError:
        valid = False
    return f"<a href='{text(url)}' target='_blank' rel='noopener noreferrer'>{text(title)}</a>" if valid else text(title)


def render_candidate(connection, candidate_id):
    row = connection.execute(
        "SELECT c.*,s.evidence_snapshot_json,s.scout_evaluation_run_id,s.evidence_fingerprint "
        "FROM trend_candidates c JOIN topic_snapshots s ON s.topic_snapshot_id=c.latest_topic_snapshot_id "
        "WHERE c.trend_candidate_id=?", (candidate_id,),
    ).fetchone()
    if row is None:
        return "<section><h2>Cluster not found</h2></section>"
    parts = [f"<section class='card' id='cluster'><h2>Cluster #{candidate_id}: {text(row['canonical_subject'])}</h2>",
             f"<p><b>Detection selection: {text(row['eligibility_status'])}</b> · Detection attention score {row['score']:.4f} · {text(row['eligibility_reason'])}</p>",
             f"<p>Snapshot #{row['latest_topic_snapshot_id']} · {link('Scout evaluation #' + str(row['scout_evaluation_run_id']), evaluation_id=row['scout_evaluation_run_id'])}</p>"]
    if row['selected_thread_id']:
        parts.append(link('Open resulting thread →', thread_id=row['selected_thread_id']))
    parts.append(json_detail('Detection attention score components and selection gates', row['score_breakdown_json']))
    parts.append(json_detail('Frozen source and semantic membership evidence', row['evidence_snapshot_json']))
    observations = connection.execute(
        "SELECT o.*,s.stable_id,m.contribution FROM candidate_observation_memberships m "
        "JOIN trend_observations o ON o.trend_observation_id=m.trend_observation_id "
        "JOIN detection_source_instances s ON s.detection_source_instance_id=o.source_instance_id "
        "WHERE m.topic_snapshot_id=? ORDER BY o.trend_observation_id LIMIT 200",
        (row['latest_topic_snapshot_id'],),
    ).fetchall()
    parts.append('<h3>Raw Feed Items (first 200 in this snapshot)</h3><ul>')
    for observation in observations:
        parts.append(f"<li>{link('Item #' + str(observation['trend_observation_id']), raw_item_id=observation['trend_observation_id'])} {text(observation['stable_id'])}: "
                     f"{public_link(observation['title'], observation['canonical_url'])} · scoring credit {observation['contribution']}</li>")
    return ''.join(parts) + '</ul></section>'


def render_evaluation(connection, evaluation_id):
    row = connection.execute('SELECT * FROM scout_evaluation_runs WHERE scout_evaluation_run_id=?', (evaluation_id,)).fetchone()
    if row is None:
        return '<section><h2>Scout evaluation not found</h2></section>'
    parts = [f"<section class='card'><h2>Scout evaluation #{evaluation_id}</h2>",
             f"<p>{text(row['status'])} · {text(row['evaluation_slot_start'])} · {text(row['failure_category'])}</p>",
             json_detail('Evaluation status, lease and input fingerprint', dict(row), diagnostic=True)]
    resolution = connection.execute('SELECT * FROM scout_event_resolutions WHERE scout_evaluation_run_id=?', (evaluation_id,)).fetchone()
    if resolution:
        value = json.loads(resolution['resolution_json'])
        parts.append('<p>Resolved membership is frozen. Semantic neighbors do not pool scoring credit.</p>')
        parts.append(json_detail('Semantic decisions: model, thresholds, lexical clusters and pair signals', value))
    else:
        parts.append('<p>No frozen semantic resolution yet. Check the evaluation status and failure above.</p>')
    inputs = connection.execute('SELECT * FROM scout_evaluation_inputs WHERE scout_evaluation_run_id=? ORDER BY ordinal', (evaluation_id,)).fetchall()
    parts.append(json_detail('Frozen source health and availability', [dict(x) for x in inputs], diagnostic=True))
    return ''.join(parts) + '</section>'


def render_queue_status(connection):
    parts = ["<section class='card' id='queues'><h2>Planning queues</h2><p>Pending GenerationRuns are expected in planning-only mode. All times are UTC.</p><div class='route-grid'>"]
    for table, label in [('intake_requests', 'Idea Intake'), ('determination_requests', 'Determination'), ('generation_runs', 'Generation'), ('visual_plan_runs', 'Visual planning'), ('render_runs', 'Rendering')]:
        rows = connection.execute(f'SELECT status,COUNT(*) n FROM {table} GROUP BY status').fetchall()
        summary = ' · '.join(f"{r['status']}: {r['n']}" for r in rows) or 'no work yet'
        parts.append(f"<div><h3>{label}</h3><p>{text(summary)}</p></div>")
    parts.append('</div><h3>Required planning workers</h3><ul>')
    for worker in ('trend_source_collector', 'trend_scout_shortlist', 'idea_intake', 'determination'):
        row = connection.execute('SELECT state,last_seen_at FROM worker_heartbeats WHERE worker_type=? ORDER BY last_seen_at DESC LIMIT 1', (worker,)).fetchone()
        parts.append(f"<li>{text(worker)}: {text(row['state']) + ' · ' + text(row['last_seen_at']) if row else 'not started / no heartbeat'}</li>")
    parts.append('</ul>')
    parts.append(render_storage_status(connection))
    parts.append(render_storage_growth(connection))
    usage = connection.execute("SELECT COUNT(*) n,COALESCE(SUM(estimated_cost_micro_usd),0) cost FROM model_invocations WHERE started_at>=date('now')").fetchone()
    reservations = connection.execute("SELECT COALESCE(SUM(worst_case_micro_usd),0) amount FROM gemini_budget_reservations WHERE status IN ('reserved','uncertain') AND accounting_day=date('now')").fetchone()
    parts.append(f"<p>Gemini today (UTC): {usage['n']} attempts · recorded estimated USD {usage['cost']/1000000:.6f} · reserved/uncertain USD {reservations['amount']/1000000:.6f}.</p>")
    return ''.join(parts) + '</section>'


def render_storage_status(connection):
    status = storage_status(connection)
    detail = (f"Storage observation (advisory for planning): {status['reason']} · last measured state: {status['state'] or 'none'}"
              f" · sampled {status['sampled_at'] or 'never'}")
    if status['free_bytes'] is not None:
        detail += f" · {status['free_bytes']/1024**3:.1f} GiB free at that sample"
    guidance = '' if status['reason']=='normal' else '<p>' + text(storage_recovery(status)) + '</p>'
    return f"<aside class='notice'><b>{text(detail)}</b><p>Storage samples never block ideas, Intake, Detection, Determination or ContentJobs.</p>{guidance}</aside>"


def render_storage_growth(connection):
    rows = connection.execute("SELECT sampled_at,database_bytes,wal_bytes,artifact_bytes,backup_bytes,summary_json FROM storage_samples WHERE sampled_at>=datetime('now','-31 days') AND json_type(summary_json,'$.growth')='object' ORDER BY storage_sample_id DESC LIMIT 31").fetchall()
    if not rows:
        return '<p>Storage growth: no daily measurement yet; start the storage monitor.</p>'
    latest, earliest = rows[0], rows[-1]
    first = json.loads(earliest['summary_json'])['growth']
    last = json.loads(latest['summary_json'])['growth']
    tables = []
    for name, data in last['tables'].items():
        prior = first['tables'].get(name)
        tables.append({'table': name, **data, 'row_growth': data['rows']-prior['rows'] if prior else None})
    sizes = [{k: row[k] for k in ('sampled_at','database_bytes','wal_bytes','artifact_bytes','backup_bytes')} for row in rows]
    return (f"<h3>Storage growth · {len(rows)} daily samples</h3>"
            f"<p>{text(earliest['sampled_at'])} → {text(latest['sampled_at'])}. "
            f"Latest table scan: {'complete' if last['complete'] else 'partial (time limit/error)'}. "
            "Review after 7 and 30 days. JSON byte lengths are logical UTF-8 sizes, not physical SQLite allocation. No database rows are deleted.</p>"
            + json_detail('Daily database / WAL / artifact / backup bytes', sizes)
            + json_detail('Row growth and JSON evidence / provider-metadata bytes by table', tables))
