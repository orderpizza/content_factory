"""Bounded, thread-first read model for the local editorial scaffold."""

from __future__ import annotations

from html import escape
import json
import sqlite3


def render_workflow_trace(connection: sqlite3.Connection, *, limit: int = 20) -> str:
    limit = max(1, min(int(limit), 100))
    rows = connection.execute(
        "SELECT * FROM content_threads ORDER BY updated_at DESC,thread_id DESC LIMIT ?", (limit,)
    ).fetchall()
    parts = ["<section class='workflow'><h2>Editorial workflow — local placeholders</h2>"
             f"<p>Latest {limit} threads; public authorization and delivery are disabled. "
             "Messages, requests and branches below are bounded recent history.</p>"]
    if not rows:
        parts.append("<p>No threads yet.</p>")
    for thread in rows:
        thread_id = thread["thread_id"]
        messages = connection.execute(
            "SELECT author_kind,body,sequence_number FROM thread_messages WHERE thread_id=? "
            "ORDER BY sequence_number DESC LIMIT 50", (thread_id,)
        ).fetchall()
        revisions = connection.execute(
            "SELECT revision_id,revision_number,brief_json FROM brief_revisions WHERE thread_id=? "
            "ORDER BY revision_number DESC LIMIT 10", (thread_id,)
        ).fetchall()
        topic = json.loads(revisions[0]["brief_json"]).get("topic", "Untitled") if revisions else "Awaiting Intake"
        parts.append(f"<article><h3>Thread #{thread_id}: {escape(topic)}</h3>"
                     f"<p>{escape(thread['origin'])} / {escape(thread['status'])}; row version "
                     f"{thread['row_version']}</p><details><summary>Idea conversation (latest 50)</summary><ol>")
        parts.extend(f"<li value='{m['sequence_number']}'><b>{escape(m['author_kind'])}</b>: "
                     f"{escape(m['body'])}</li>" for m in reversed(messages))
        parts.append("</ol></details><ul>")
        requests = connection.execute(
            "SELECT intake_request_id,status,failure_detail FROM intake_requests WHERE thread_id=? "
            "ORDER BY intake_request_id DESC LIMIT 20", (thread_id,)
        ).fetchall()
        for request in requests:
            parts.append(f"<li>Intake #{request['intake_request_id']}: {escape(request['status'])}"
                         f" — {escape(request['failure_detail'] or '')}</li>")
        parts.append("</ul>")
        for revision in revisions:
            decision = connection.execute(
                "SELECT q.determination_request_id,q.status,q.failure_reason,d.determination_decision_id,"
                "d.outcome,d.rationale FROM determination_requests q LEFT JOIN determination_decisions d "
                "ON d.determination_request_id=q.determination_request_id WHERE q.revision_id=?",
                (revision["revision_id"],),
            ).fetchone()
            parts.append(f"<p>Revision {revision['revision_number']} (#{revision['revision_id']})</p>")
            if decision is None:
                parts.append("<p>Missing Determination handoff.</p>")
                continue
            parts.append(f"<p>Determination #{decision['determination_request_id']}: "
                         f"{escape(decision['outcome'] or decision['status'])} — "
                         f"{escape(decision['rationale'] or decision['failure_reason'] or '')}</p>")
            if decision["determination_decision_id"] is not None:
                routes = connection.execute(
                    "SELECT pipeline_id,disposition,reason FROM determination_routes "
                    "WHERE determination_decision_id=? ORDER BY pipeline_id LIMIT 5",
                    (decision["determination_decision_id"],),
                ).fetchall()
                parts.append("<details><summary>Five domain routes</summary><ul>")
                parts.extend(f"<li><b>{escape(r['pipeline_id'])}</b>: {escape(r['disposition'])} — "
                             f"{escape(r['reason'])}</li>" for r in routes)
                parts.append("</ul></details>")
            branches = connection.execute(
                "SELECT j.content_job_id,j.pipeline_id,g.status generation_status,c.canonical_content_id,"
                "o.output_request_id,o.platform,o.account,a.status adaptation_status,p.content_package_id,"
                "rr.render_run_id,rr.status render_status,v.review_request_id,v.status review_status,"
                "pr.status post_status FROM content_jobs j "
                "LEFT JOIN generation_runs g ON g.content_job_id=j.content_job_id "
                "LEFT JOIN canonical_contents c ON c.content_job_id=j.content_job_id "
                "LEFT JOIN output_requests o ON o.canonical_content_id=c.canonical_content_id "
                "LEFT JOIN adaptation_runs a ON a.output_request_id=o.output_request_id "
                "LEFT JOIN content_packages p ON p.output_request_id=o.output_request_id "
                "LEFT JOIN render_runs rr ON rr.content_package_id=p.content_package_id "
                "LEFT JOIN review_requests v ON v.render_run_id=rr.render_run_id "
                "LEFT JOIN post_requests pq ON pq.review_request_id=v.review_request_id "
                "LEFT JOIN post_records pr ON pr.post_request_id=pq.post_request_id "
                "WHERE j.brief_revision_id=? ORDER BY j.content_job_id,o.output_request_id,"
                "g.run_number DESC,a.run_number DESC,rr.run_number DESC,v.review_cycle_number DESC LIMIT 20",
                (revision["revision_id"],),
            ).fetchall()
            if branches:
                parts.append("<details><summary>Production branches (latest 20 rows)</summary><ul>")
                for branch in branches:
                    values = " · ".join(f"{key}: {value}" for key, value in dict(branch).items() if value is not None)
                    parts.append(f"<li>{escape(values)}</li>")
                parts.append("</ul></details>")
        parts.append("</article>")
    return "".join(parts) + "</section>"
