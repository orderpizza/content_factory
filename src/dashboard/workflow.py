"""Read-only v2 workflow trace appended to the detection dashboard."""

from __future__ import annotations

from html import escape
import sqlite3


def render_workflow_trace(connection: sqlite3.Connection) -> str:
    rows = connection.execute(
        "SELECT d.determination_decision_id,d.outcome,d.rationale,r.thread_id,r.brief_json "
        "FROM determination_decisions d JOIN determination_requests q ON q.determination_request_id=d.determination_request_id "
        "JOIN brief_revisions r ON r.revision_id=q.revision_id ORDER BY d.determination_decision_id DESC LIMIT 100"
    ).fetchall()
    parts=["<section class='workflow'><h2>Editorial workflow</h2><p>Persisted worker handoffs; disabled integrations are labelled explicitly.</p>"]
    if not rows: parts.append("<p>No completed determination decisions yet.</p>")
    for row in rows:
        routes=connection.execute("SELECT pipeline_id,disposition,fit,reason FROM determination_routes WHERE determination_decision_id=? ORDER BY pipeline_id",(row["determination_decision_id"],)).fetchall()
        import json
        topic=json.loads(row["brief_json"]).get("topic","untitled")
        messages=connection.execute("SELECT author_kind,body FROM thread_messages WHERE thread_id=? ORDER BY sequence_number",(row["thread_id"],)).fetchall()
        parts.append(f"<article><h3>{escape(topic)} <small>#{row['determination_decision_id']} — {escape(row['outcome'])}</small></h3><p>{escape(row['rationale'])}</p><details><summary>Idea conversation ({len(messages)} messages)</summary><ol>")
        parts.extend(f"<li><b>{escape(message['author_kind'])}</b>: {escape(message['body'])}</li>" for message in messages)
        parts.append("</ol></details><details><summary>Five domain routes</summary><ul>")
        parts.extend(f"<li><b>{escape(route['pipeline_id'])}</b>: {escape(route['disposition'])} — {escape(route['reason'])}</li>" for route in routes)
        parts.append("</ul></details></article>")
    return "".join(parts)+"</section>"
