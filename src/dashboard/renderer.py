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
    decisions = rows("""
        SELECT d.*, h.candidate_id
        FROM determination_decisions d
        JOIN determination_handoffs h ON h.handoff_id = d.handoff_id
        ORDER BY d.created_at DESC, d.decision_id DESC
        LIMIT 20
    """)
    jobs = rows("SELECT * FROM content_jobs ORDER BY updated_at DESC, job_id DESC LIMIT 20")
    packages = rows("SELECT * FROM content_packages ORDER BY created_at DESC, content_id DESC LIMIT 20")
    posts = rows("SELECT * FROM posts ORDER BY updated_at DESC, id DESC LIMIT 20")
    awaiting_render = rows("SELECT * FROM content_packages WHERE status = 'awaiting_render' ORDER BY created_at DESC, content_id DESC LIMIT 20")
    recently_rendered = rows("SELECT * FROM content_packages WHERE status = 'ready_for_posting' ORDER BY created_at DESC, content_id DESC LIMIT 15")
    observations = rows("SELECT * FROM trend_observations ORDER BY observed_at DESC, id DESC LIMIT 30")
    snapshots = rows("SELECT * FROM topic_snapshots ORDER BY observed_at DESC, id DESC LIMIT 30")
    posting_policies = rows("SELECT * FROM posting_policies ORDER BY pipeline_id, platform, account")

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

    def visual_status() -> tuple[str, str]:
        awaiting = count("content_packages", "status = 'awaiting_render'")
        rendered = count("content_packages", "status = 'ready_for_posting'")
        if not awaiting and not rendered:
            return "NOT_STARTED", "No packages to render"
        if awaiting:
            return "WAITING", f"{awaiting} package(s) awaiting render"
        return "COMPLETED", f"{rendered} package(s) rendered"

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
    visual_state, visual_detail = visual_status()
    posting_state, posting_detail = posting_status()
    module_rows = "".join(
        f"<tr><td>{cell(name)}</td><td><span class='status {status.lower()}'>{cell(status)}</span></td><td>{cell(detail)}</td></tr>"
        for name, status, detail in (
            ("Trend Detection", detection_state, detection_detail),
            ("Determination", determination_state, determination_detail),
            ("Content Pipeline", pipeline_state, pipeline_detail),
            ("Visual Rendering", visual_state, visual_detail),
            ("Posting", posting_state, posting_detail),
        )
    )

    candidate_rows = table_rows(candidates, [
        lambda row: cell(row["status"]), lambda row: cell(row["lifecycle_stage"]),
        lambda row: cell(row["topic"]), lambda row: f"{row['score']:.2f}", lambda row: json_cell(row["score_breakdown"]),
        lambda row: json_cell(row["supporting_sources"]), lambda row: cell(row["cooldown_until"]),
    ], "No candidates yet", 7)
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
    decision_rows = table_rows(decisions, [
        lambda row: str(row["decision_id"]), lambda row: str(row["handoff_id"]),
        lambda row: cell(row["status"]), lambda row: json_cell(row["recipe_json"]),
        lambda row: cell(row["reasoning"]), lambda row: cell(row["created_at"]),
    ], "No determination decisions yet", 6)
    job_rows = table_rows(jobs, [
        lambda row: str(row["job_id"]), lambda row: cell(row["topic"]), lambda row: cell(row["pipeline_id"]),
        lambda row: cell(row["target_platform"]), lambda row: cell(row["target_account"]), lambda row: cell(row["content_format"]), lambda row: str(row["priority"]),
        lambda row: cell(row["status"]), lambda row: cell(row["updated_at"]),
    ], "No content jobs yet", 9)
    package_rows = table_rows(packages, [
        lambda row: str(row["content_id"]), lambda row: str(row["job_id"]), lambda row: cell(row["pipeline_id"]),
        lambda row: cell(row["platform"]), lambda row: cell(row["account"]), lambda row: cell(row["content_format"]), lambda row: cell(row["title"]),
        lambda row: cell(row["status"]), lambda row: cell(row["metadata_status"]),
        lambda row: json_cell(row["assets"]), lambda row: cell(row["created_at"]),
    ], "No content packages yet", 11)
    post_rows = table_rows(posts, [
        lambda row: str(row["id"]), lambda row: str(row["content_id"]),
        lambda row: cell(row["platform"]), lambda row: cell(row["account"]),
        lambda row: cell(row["status"]), lambda row: cell(row["scheduled_at"]),
        lambda row: cell(row["published_at"]), lambda row: cell(row["external_post_id"]), lambda row: cell(row["error"]),
    ], "No post records yet", 9)
    awaiting_render_rows = table_rows(awaiting_render, [
        lambda row: str(row["content_id"]), lambda row: str(row["job_id"]), lambda row: cell(row["pipeline_id"]),
        lambda row: cell(row["title"]), lambda row: cell(row["created_at"]),
    ], "No packages awaiting render", 5)
    rendered_rows = table_rows(recently_rendered, [
        lambda row: str(row["content_id"]), lambda row: cell(row["pipeline_id"]), lambda row: cell(row["title"]),
        lambda row: str(len(json.loads(row["assets"]))), lambda row: cell(row["created_at"]),
    ], "No rendered packages", 5)
    observation_rows = table_rows(observations, [
        lambda row: cell(row["topic"]), lambda row: cell(row["source"]), lambda row: str(row["activity_value"]),
        lambda row: str(row["baseline_value"]), lambda row: cell(row["observed_at"]),
    ], "No observations yet", 5)
    snapshot_rows = table_rows(snapshots, [
        lambda row: cell(row["topic"]), lambda row: str(row["activity"]), lambda row: str(row["source_count"]),
        lambda row: str(row["mention_count"]), lambda row: cell(row["observed_at"]),
    ], "No topic snapshots yet", 5)
    policy_rows = table_rows(posting_policies, [
        lambda row: cell(row["pipeline_id"]), lambda row: cell(row["platform"]), lambda row: cell(row["account"]),
        lambda row: str(row["max_posts_per_day"]), lambda row: str(row["min_post_interval_minutes"]),
    ], "No posting policies configured.", 5)

    def phase_card(name: str, status: str, detail: str, anchor: str) -> str:
        return (
            f"<a class='phase-card {status.lower()}' href='#{anchor}'>"
            f"<span class='phase-name'>{cell(name)}</span>"
            f"<span class='phase-status'>{cell(status)}</span>"
            f"<span class='phase-detail'>{cell(detail)}</span></a>"
        )

    phase_cards = "".join([
        phase_card("Detection", detection_state, detection_detail, "detection"),
        phase_card("Determination", determination_state, determination_detail, "determination"),
        phase_card("Content Job", pipeline_state, pipeline_detail, "content-jobs"),
        phase_card("Visual", visual_state, visual_detail, "visual"),
        phase_card("Posting", posting_state, posting_detail, "posting"),
    ])

    return f"""<!doctype html>
<html><head><meta charset='utf-8'><meta http-equiv='refresh' content='15'>
<title>Content Factory Dashboard</title>
<style>
body{{font-family:Arial,sans-serif;max-width:1500px;margin:0 auto;padding:0 28px 60px;color:#17212b;background:#f3f6f8}}
header{{background:#17212b;color:white;margin:0 -28px 28px;padding:28px 28px 24px}}
h1{{margin:0 0 8px;font-size:30px}} h2{{margin:38px 0 14px}} h3{{margin:24px 0 10px}}
nav{{display:flex;gap:16px;flex-wrap:wrap;margin-top:20px}} nav a{{color:#c9d8e5;text-decoration:none;font-size:13px}}
table{{border-collapse:collapse;width:100%;margin:12px 0 26px;background:white;box-shadow:0 1px 3px #d9e0e5}}
th,td{{border-bottom:1px solid #e0e6eb;text-align:left;padding:10px;vertical-align:top;font-size:14px}}
th{{background:#e8eef2;color:#40505c}} .empty{{color:#68737d;text-align:center}}
.status,.phase-status{{font-weight:bold;letter-spacing:.03em}} .completed{{color:#147a3d}}
.running{{color:#1769aa}} .waiting{{color:#9a6700}} .degraded,.failed{{color:#b42318}}
.not_started{{color:#68737d}} .meta{{color:#71808c}} .summary{{display:grid;grid-template-columns:repeat(6,minmax(120px,1fr));gap:12px}}
.metric{{background:white;border:1px solid #d8e1e7;border-radius:8px;padding:15px 16px;box-shadow:0 1px 3px #dfe6ea}}
.number{{display:block;font-size:25px;font-weight:bold;margin-top:5px;color:#17212b}}
.phase-flow{{display:grid;grid-template-columns:repeat(5,1fr);gap:12px;margin:18px 0 12px}}
.phase-card{{display:flex;flex-direction:column;gap:8px;background:white;border:1px solid #d8e1e7;border-top:5px solid #9aa8b2;border-radius:8px;padding:16px;text-decoration:none;color:#17212b;min-height:112px;box-shadow:0 1px 3px #dfe6ea}}
.phase-card.completed{{border-top-color:#2e9b5b}} .phase-card.running{{border-top-color:#3786bd}} .phase-card.waiting{{border-top-color:#d29a2e}} .phase-card.not_started{{border-top-color:#9aa8b2}}
.phase-name{{font-size:14px;font-weight:bold}} .phase-status{{font-size:18px}} .phase-detail{{font-size:12px;color:#71808c;line-height:1.35}}
.section{{scroll-margin-top:20px}} details{{margin:10px 0}} summary{{cursor:pointer;font-size:16px;font-weight:bold;color:#334e60}}
@media(max-width:900px){{.summary{{grid-template-columns:repeat(3,1fr)}}.phase-flow{{grid-template-columns:repeat(2,1fr)}}}}
@media(max-width:600px){{.summary{{grid-template-columns:repeat(2,1fr)}}.phase-flow{{grid-template-columns:1fr}}}}
</style></head><body>
<header><h1>Content Factory</h1>
<div class='meta' style='color:#c9d8e5'>System observability · SQLite state · read-only · auto-refresh 15s</div>
<nav><a href='#overview'>Overview</a><a href='#detection'>Detection</a><a href='#determination'>Determination</a><a href='#content-jobs'>Content</a><a href='#visual'>Visual</a><a href='#posting'>Posting</a></nav></header>
<h2 id='overview'>System Overview</h2>
<div class='summary'>
<div class='metric'>Observations<span class='number'>{count('trend_observations')}</span></div>
<div class='metric'>Candidates<span class='number'>{count('trend_candidates')}</span></div>
<div class='metric'>Handoffs<span class='number'>{count('determination_handoffs')}</span></div>
<div class='metric'>Content Jobs<span class='number'>{count('content_jobs')}</span></div>
<div class='metric'>Packages<span class='number'>{count('content_packages')}</span></div>
<div class='metric'>Posts<span class='number'>{count('posts')}</span></div>
</div>
<div class='phase-flow'>{phase_cards}</div>
<p class='meta'>Latest source check: {cell(latest_source_check or 'not yet')} · Click a phase to inspect its persisted details.</p>
<table><tr><th>Phase</th><th>Status</th><th>Current State</th></tr>{module_rows}</table>
<section id='detection' class='section'><h2>Trend Detection</h2>
<p class='meta'>Latest detection run: {cell(latest_detection['run_id'] if latest_detection else 'not yet')}</p>
<details open><summary>Detection Runs</summary><table><tr><th>Run</th><th>Started</th><th>Completed</th><th>Status</th><th>Observations</th><th>Selected</th><th>Error</th></tr>{run_rows}</table></details>
<details open><summary>Ranked Candidates</summary><table><tr><th>Status</th><th>Stage</th><th>Topic</th><th>Score</th><th>Score Breakdown</th><th>Sources</th><th>Cooldown Until</th></tr>{candidate_rows}</table></details>
<details><summary>Source Health</summary><table><tr><th>Source</th><th>Checked</th><th>Status</th><th>Attempts</th><th>Error</th></tr>{source_rows}</table></details>
<details><summary>Recent Observations</summary><table><tr><th>Topic</th><th>Source</th><th>Activity</th><th>Baseline</th><th>Observed</th></tr>{observation_rows}</table></details>
<details><summary>Topic Snapshots</summary><table><tr><th>Topic</th><th>Activity</th><th>Sources</th><th>Mentions</th><th>Observed</th></tr>{snapshot_rows}</table></details></section>
<section id='determination' class='section'><h2>Determination</h2><p class='meta'>Status counts: {status_counts('determination_handoffs')}</p>
<table><tr><th>Handoff</th><th>Topic</th><th>Score</th><th>Status</th><th>Created</th><th>Completed</th><th>Failure</th></tr>{handoff_rows}</table>
<h3>Decisions</h3><table><tr><th>Decision</th><th>Handoff</th><th>Status</th><th>Recipe</th><th>Reasoning</th><th>Created</th></tr>{decision_rows}</table>
 </section><section id='content-jobs' class='section'><h2>Content Production</h2><h3>Content Jobs</h3><p class='meta'>Status counts: {status_counts('content_jobs')}</p>
<table><tr><th>Job</th><th>Topic</th><th>Pipeline</th><th>Platform</th><th>Account</th><th>Format</th><th>Priority</th><th>Status</th><th>Updated</th></tr>{job_rows}</table>
<h3>Content Packages</h3><table><tr><th>Content</th><th>Job</th><th>Pipeline</th><th>Platform</th><th>Account</th><th>Format</th><th>Title</th><th>Package</th><th>Metadata</th><th>Assets</th><th>Created</th></tr>{package_rows}</table></section>
<section id='visual' class='section'><h2>Visual Rendering</h2><p class='meta'>Package readiness is persisted on each ContentPackage: awaiting render packages are not eligible for posting.</p>
<details open><summary>Awaiting Render</summary><table><tr><th>Content</th><th>Job</th><th>Pipeline</th><th>Title</th><th>Created</th></tr>{awaiting_render_rows}</table></details>
<details><summary>Recently Rendered</summary><table><tr><th>Content</th><th>Pipeline</th><th>Title</th><th>Assets</th><th>Created</th></tr>{rendered_rows}</table></details></section>
<section id='posting' class='section'><h2>Posting</h2><p class='meta'>Status counts: {status_counts('posts')}</p>
<h3>Cadence Policies</h3><table><tr><th>Pipeline</th><th>Platform</th><th>Account</th><th>Daily Limit</th><th>Minimum Interval (minutes)</th></tr>{policy_rows}</table>
<table><tr><th>Post</th><th>Content</th><th>Platform</th><th>Account</th><th>Status</th><th>Scheduled</th><th>Published</th><th>External Post ID</th><th>Error</th></tr>{post_rows}</table>
</section></body></html>"""
