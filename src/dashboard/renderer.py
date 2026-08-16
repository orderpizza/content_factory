"""Render the read-only system observability dashboard from SQLite state."""

import json
from html import escape


def render_dashboard(database) -> str:
    """Render every currently persisted system phase without mutating state."""

    connection = database.connection

    def count(table: str, where: str = "", params: tuple = ()) -> int:
        query = f"SELECT COUNT(*) AS count FROM {table}"
        if where:
            query += f" WHERE {where}"
        return int(connection.execute(query, params).fetchone()["count"])

    def rows(query: str, params: tuple = ()):
        return connection.execute(query, params).fetchall()

    def cell(value) -> str:
        return escape("" if value is None else str(value))

    def json_cell(value) -> str:
        try:
            parsed = json.loads(value) if isinstance(value, str) else value
            return cell(json.dumps(parsed, ensure_ascii=False, sort_keys=True))
        except (TypeError, json.JSONDecodeError):
            return cell(value)

    def table_rows(items, renderers, empty_message: str, colspan: int) -> str:
        if not items:
            return f"<tr><td colspan='{colspan}' class='empty'>{cell(empty_message)}</td></tr>"
        return "".join(
            "<tr>" + "".join(f"<td>{renderer(item)}</td>" for renderer in renderers) + "</tr>"
            for item in items
        )

    latest_detection = connection.execute(
        "SELECT * FROM detection_runs ORDER BY started_at DESC, run_id DESC LIMIT 1"
    ).fetchone()
    latest_source_check = connection.execute(
        "SELECT MAX(checked_at) AS checked_at FROM source_health"
    ).fetchone()["checked_at"]

    candidates = rows("SELECT * FROM trend_candidates ORDER BY score DESC, topic LIMIT 20")
    source_health = rows("SELECT * FROM source_health ORDER BY checked_at DESC, id DESC LIMIT 30")
    detection_runs = rows("SELECT * FROM detection_runs ORDER BY started_at DESC, run_id DESC LIMIT 15")
    handoffs = rows("""
        SELECT h.*, c.topic, c.score
        FROM determination_handoffs h
        JOIN trend_candidates c ON c.id = h.candidate_id
        ORDER BY h.created_at DESC, h.handoff_id DESC
        LIMIT 20
    """)
    jobs = rows("SELECT * FROM content_jobs ORDER BY updated_at DESC, job_id DESC LIMIT 20")
    packages = rows("SELECT * FROM content_packages ORDER BY created_at DESC, content_id DESC LIMIT 20")
    posts = rows("SELECT * FROM posts ORDER BY updated_at DESC, id DESC LIMIT 20")

    def status_counts(table: str) -> str:
        values = rows(f"SELECT status, COUNT(*) AS count FROM {table} GROUP BY status ORDER BY status")
        return ", ".join(f"{cell(row['status'])}: {row['count']}" for row in values) or "none"

    def detection_status() -> tuple[str, str]:
        if latest_detection is None:
            return "NOT_STARTED", "No detection run recorded"
        status = latest_detection["status"].upper()
        if status == "RUNNING":
            return "RUNNING", f"Run {latest_detection['run_id']} in progress"
        if status in {"FAILED", "ERROR"}:
            return "FAILED", latest_detection["error"] or f"Run {latest_detection['run_id']} failed"
        return "COMPLETED", (
            f"Run {latest_detection['run_id']}: "
            f"{latest_detection['observations_collected']} observations, "
            f"{latest_detection['candidates_selected']} selected"
        )

    def determination_status() -> tuple[str, str]:
        if not handoffs and not jobs:
            return "NOT_STARTED", "No determination handoffs recorded"
        claimed = sum(row["status"] == "claimed" for row in handoffs)
        failed = sum(row["status"] == "failed" for row in handoffs)
        pending = sum(row["status"] == "pending" for row in handoffs)
        if claimed:
            return "RUNNING", f"{claimed} claimed handoff(s)"
        if failed:
            return "DEGRADED", f"{failed} failed handoff(s)"
        if pending:
            return "WAITING", f"{pending} pending handoff(s)"
        return "COMPLETED", f"{len(handoffs)} handoff(s) completed"

    def pipeline_status() -> tuple[str, str]:
        if not jobs and not packages:
            return "NOT_STARTED", "No content jobs or packages recorded"
        running = count("content_jobs", "status IN ('running', 'claimed')")
        failed = count("content_jobs", "status = 'failed'")
        if running:
            return "RUNNING", f"{running} running job(s)"
        if failed:
            return "DEGRADED", f"{failed} failed job(s)"
        return "COMPLETED", f"{len(packages)} content package(s) generated"

    def posting_status() -> tuple[str, str]:
        if not posts:
            return "NOT_STARTED", "No post records recorded"
        queued = count("posts", "status IN ('queued', 'scheduled')")
        failed = count("posts", "status = 'failed'")
        if queued:
            return "WAITING", f"{queued} post(s) queued or scheduled"
        if failed:
            return "DEGRADED", f"{failed} failed post(s)"
        published = count("posts", "status = 'published'")
        return "COMPLETED", f"{published} published post(s)"

    detection_state, detection_detail = detection_status()
    determination_state, determination_detail = determination_status()
    pipeline_state, pipeline_detail = pipeline_status()
    posting_state, posting_detail = posting_status()
    module_rows = "".join(
        f"<tr><td>{cell(name)}</td><td><span class='status {status.lower()}'>{cell(status)}</span></td><td>{cell(detail)}</td></tr>"
        for name, status, detail in (
            ("Trend Detection", detection_state, detection_detail),
            ("Determination", determination_state, determination_detail),
            ("Content Pipeline", pipeline_state, pipeline_detail),
            ("Visual Rendering", "NOT_STARTED", "No visual render records recorded"),
            ("Posting", posting_state, posting_detail),
        )
    )

    candidate_rows = table_rows(candidates, [
        lambda row: cell(row["status"]), lambda row: cell(row["lifecycle_stage"]),
        lambda row: cell(row["topic"]), lambda row: f"{row['score']:.2f}",
        lambda row: json_cell(row["supporting_sources"]), lambda row: cell(row["cooldown_until"]),
    ], "No candidates yet", 6)
    source_rows = table_rows(source_health, [
        lambda row: cell(row["source"]), lambda row: cell(row["checked_at"]),
        lambda row: "OK" if row["success"] else "FAILED", lambda row: str(row["attempts"]),
        lambda row: cell(row["error"]),
    ], "No source checks yet", 5)
    run_rows = table_rows(detection_runs, [
        lambda row: str(row["run_id"]), lambda row: cell(row["started_at"]),
        lambda row: cell(row["completed_at"]), lambda row: cell(row["status"]),
        lambda row: str(row["observations_collected"]), lambda row: str(row["candidates_selected"]),
        lambda row: cell(row["error"]),
    ], "No detection runs yet", 7)
    handoff_rows = table_rows(handoffs, [
        lambda row: str(row["handoff_id"]), lambda row: cell(row["topic"]),
        lambda row: f"{row['score']:.2f}", lambda row: cell(row["status"]),
        lambda row: cell(row["created_at"]), lambda row: cell(row["completed_at"]),
        lambda row: cell(row["failure_reason"]),
    ], "No determination handoffs yet", 7)
    job_rows = table_rows(jobs, [
        lambda row: str(row["job_id"]), lambda row: cell(row["topic"]),
        lambda row: cell(row["pipeline_id"]), lambda row: str(row["priority"]),
        lambda row: cell(row["status"]), lambda row: cell(row["updated_at"]),
    ], "No content jobs yet", 6)
    package_rows = table_rows(packages, [
        lambda row: str(row["content_id"]), lambda row: str(row["job_id"]),
        lambda row: cell(row["pipeline_id"]), lambda row: cell(row["title"]),
        lambda row: json_cell(row["assets"]), lambda row: cell(row["created_at"]),
    ], "No content packages yet", 6)
    post_rows = table_rows(posts, [
        lambda row: str(row["id"]), lambda row: str(row["content_id"]),
        lambda row: cell(row["platform"]), lambda row: cell(row["account"]),
        lambda row: cell(row["status"]), lambda row: cell(row["scheduled_at"]),
        lambda row: cell(row["published_at"]), lambda row: cell(row["error"]),
    ], "No post records yet", 8)

    return f"""<!doctype html>
<html><head><meta charset='utf-8'><meta http-equiv='refresh' content='15'>
<title>Content Factory Dashboard</title>
<style>
body{{font-family:Arial,sans-serif;max-width:1400px;margin:32px auto;padding:0 20px;color:#1f2933;background:#fafafa}}
h1{{margin-bottom:8px}} h2{{margin-top:36px}} h3{{margin-top:26px}}
table{{border-collapse:collapse;width:100%;margin:12px 0 26px;background:white}}
th,td{{border-bottom:1px solid #ddd;text-align:left;padding:9px;vertical-align:top;font-size:14px}}
th{{background:#eef2f5}} .empty{{color:#68737d;text-align:center}}
.status{{font-weight:bold;letter-spacing:.03em}} .completed{{color:#147a3d}}
.running{{color:#1769aa}} .waiting{{color:#9a6700}} .degraded,.failed{{color:#b42318}}
.not_started{{color:#68737d}} .meta{{color:#68737d}} .summary{{display:flex;gap:12px;flex-wrap:wrap}}
.card{{background:white;border:1px solid #d8dee4;padding:14px 18px;min-width:160px}}
.number{{display:block;font-size:24px;font-weight:bold;margin-top:4px}}
</style></head><body>
<h1>Content Factory Dashboard</h1>
<p class='meta'>Read-only SQLite observability | Latest source check: {cell(latest_source_check or 'not yet')} | Refresh: 15 seconds</p>
<h2>System Overview</h2>
<div class='summary'>
<div class='card'>Observations<span class='number'>{count('trend_observations')}</span></div>
<div class='card'>Candidates<span class='number'>{count('trend_candidates')}</span></div>
<div class='card'>Handoffs<span class='number'>{count('determination_handoffs')}</span></div>
<div class='card'>Content Jobs<span class='number'>{count('content_jobs')}</span></div>
<div class='card'>Packages<span class='number'>{count('content_packages')}</span></div>
<div class='card'>Posts<span class='number'>{count('posts')}</span></div>
</div>
<table><tr><th>Phase</th><th>Status</th><th>Current State</th></tr>{module_rows}</table>
<h2>Trend Detection</h2>
<p class='meta'>Latest detection run: {cell(latest_detection['run_id'] if latest_detection else 'not yet')}</p>
<h3>Detection Runs</h3><table><tr><th>Run</th><th>Started</th><th>Completed</th><th>Status</th><th>Observations</th><th>Selected</th><th>Error</th></tr>{run_rows}</table>
<h3>Ranked Candidates</h3><table><tr><th>Status</th><th>Stage</th><th>Topic</th><th>Score</th><th>Sources</th><th>Cooldown Until</th></tr>{candidate_rows}</table>
<h3>Source Health</h3><table><tr><th>Source</th><th>Checked</th><th>Status</th><th>Attempts</th><th>Error</th></tr>{source_rows}</table>
<h2>Determination</h2><p class='meta'>Status counts: {status_counts('determination_handoffs')}</p>
<table><tr><th>Handoff</th><th>Topic</th><th>Score</th><th>Status</th><th>Created</th><th>Completed</th><th>Failure</th></tr>{handoff_rows}</table>
<h2>Content Jobs</h2><p class='meta'>Status counts: {status_counts('content_jobs')}</p>
<table><tr><th>Job</th><th>Topic</th><th>Pipeline</th><th>Priority</th><th>Status</th><th>Updated</th></tr>{job_rows}</table>
<h2>Content Packages</h2><table><tr><th>Content</th><th>Job</th><th>Pipeline</th><th>Title</th><th>Assets</th><th>Created</th></tr>{package_rows}</table>
<h2>Visual Rendering</h2><p class='meta'><span class='status not_started'>NOT_STARTED</span> — No visual render status records are persisted yet.</p>
<h2>Posting</h2><p class='meta'>Status counts: {status_counts('posts')}</p>
<table><tr><th>Post</th><th>Content</th><th>Platform</th><th>Account</th><th>Status</th><th>Scheduled</th><th>Published</th><th>Error</th></tr>{post_rows}</table>
</body></html>"""
