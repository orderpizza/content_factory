"""Bounded, thread-first read model for the local editorial scaffold."""

from __future__ import annotations

from html import escape
from datetime import datetime, timezone
import json
import sqlite3
import uuid


def render_workflow_trace(
    connection: sqlite3.Connection,
    *,
    limit: int = 20,
    interactive: bool = False,
    csrf_token: str = "",
) -> str:
    limit = max(1, min(int(limit), 100))
    production = int(connection.execute("PRAGMA user_version").fetchone()[0]) >= 4
    rows = connection.execute(
        "SELECT * FROM content_threads ORDER BY updated_at DESC,thread_id DESC LIMIT ?", (limit,)
    ).fetchall()
    delivery_note = (
        "Post now is available only for exact delivery-ready assets and current destinations."
        if production else "Public authorization and delivery are disabled in this schema."
    )
    parts = ["<section class='workflow'><h2>Editorial workflow</h2>"
             f"<p>Latest {limit} threads. {delivery_note} "
             "Messages, requests and branches below are bounded recent history.</p>"]
    if production:
        parts.append(_production_status(connection))
    if interactive:
        parts.append(
            "<p><b>Local input:</b> Do not paste credentials, tokens, private URLs, or personal data.</p>"
            "<form method='post' action='/commands'><h3>Submit an idea</h3>"
            f"{_hidden('csrf_token', csrf_token)}{_hidden('command_kind', 'new_idea')}"
            f"{_hidden('command_id', str(uuid.uuid4()))}"
            "<textarea name='body' maxlength='8000' required "
            "placeholder='What should the content help someone understand or do?'></textarea>"
            "<button type='submit'>Submit idea</button></form>"
        )
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
        if interactive and thread["status"] == "open":
            parts.append(
                "<form method='post' action='/commands'><h4>Reply or refine</h4>"
                f"{_hidden('csrf_token', csrf_token)}{_hidden('command_kind', 'continue_thread')}"
                f"{_hidden('command_id', str(uuid.uuid4()))}{_hidden('thread_id', thread_id)}"
                f"{_hidden('row_version', thread['row_version'])}"
                "<textarea name='body' maxlength='8000' required "
                "placeholder='Answer Intake or request a revision'></textarea>"
                "<button type='submit'>Send reply</button></form>"
            )
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
                    if branch["review_request_id"] is not None:
                        parts.append(_review_preview(
                            connection,
                            int(branch["review_request_id"]),
                            interactive=interactive,
                            csrf_token=csrf_token,
                            production=production,
                        ))
                parts.append("</ul></details>")
        parts.append("</article>")
    return "".join(parts) + "</section>"


def _hidden(name: str, value: object) -> str:
    return f"<input type='hidden' name='{escape(name)}' value='{escape(str(value))}'>"


def _review_preview(
    connection: sqlite3.Connection,
    review_id: int,
    *,
    interactive: bool,
    csrf_token: str,
    production: bool,
) -> str:
    review = connection.execute(
        "SELECT v.status,v.row_version,p.package_json,r.render_run_id "
        "FROM review_requests v JOIN content_packages p "
        "ON p.content_package_id=v.content_package_id "
        "JOIN render_runs r ON r.render_run_id=v.render_run_id "
        "WHERE v.review_request_id=?",
        (review_id,),
    ).fetchone()
    if review is None:
        return ""
    package = json.loads(review["package_json"])
    public_text = package.get("public_text") or package.get("caption") or package.get("post_text") or ""
    assets = connection.execute(
        "SELECT render_asset_id,ordinal FROM render_assets WHERE render_run_id=? "
        "AND asset_role='delivery_jpeg' ORDER BY ordinal LIMIT 8",
        (review["render_run_id"],),
    ).fetchall()
    images = "".join(
        f"<img src='/asset?render_asset_id={asset['render_asset_id']}' "
        f"alt='{escape(str(package.get('alt_text', 'Review image')))}' "
        "style='max-width:220px;height:auto;margin:.35rem'>"
        for asset in assets
    )
    parts = [
        f"<div class='review-preview'><p><b>Review #{review_id}</b>: "
        f"{escape(review['status'])}</p><div>{images}</div>"
        f"<pre style='white-space:pre-wrap'>{escape(str(public_text))}</pre>"
    ]
    if interactive and review["status"] == "awaiting_review":
        common = (
            f"{_hidden('csrf_token', csrf_token)}"
            f"{_hidden('review_id', review_id)}"
            f"{_hidden('row_version', review['row_version'])}"
        )
        if production and package.get("delivery_ready") is True and _review_destination_ready(
            connection, review_id
        ):
            parts.append(
                "<form method='post' action='/commands'>"
                f"{common}{_hidden('command_kind', 'post_now')}"
                f"{_hidden('command_id', str(uuid.uuid4()))}"
                "<button type='submit'>Post now</button></form>"
            )
        parts.append(
            "<form method='post' action='/commands'>"
            f"{common}{_hidden('command_kind', 'review_approved')}"
            f"{_hidden('command_id', str(uuid.uuid4()))}"
            "<button type='submit'>Accept without posting</button></form>"
        )
        parts.append(
            "<form method='post' action='/commands'>"
            f"{common}{_hidden('command_kind', 'review_changes')}"
            f"{_hidden('command_id', str(uuid.uuid4()))}"
            "<textarea name='note' maxlength='2000' required "
            "placeholder='Describe exactly what should change'></textarea>"
            "<button type='submit'>Request changes</button></form>"
        )
        parts.append(
            "<form method='post' action='/commands'>"
            f"{common}{_hidden('command_kind', 'review_rejected')}"
            f"{_hidden('command_id', str(uuid.uuid4()))}"
            "<textarea name='note' maxlength='2000' required "
            "placeholder='Why should this preview be rejected?'></textarea>"
            "<button type='submit'>Reject preview</button></form>"
        )
    if production:
        parts.append(_delivery_controls(
            connection, review_id, interactive=interactive, csrf_token=csrf_token
        ))
    parts.append("</div>")
    return "".join(parts)


def _review_destination_ready(connection: sqlite3.Connection, review_id: int) -> bool:
    row = connection.execute(
        "SELECT b.delivery_enabled,b.profile_approved,d.enabled,r.status,r.valid_until "
        "FROM review_requests v JOIN content_packages p ON p.content_package_id=v.content_package_id "
        "JOIN output_requests o ON o.output_request_id=p.output_request_id "
        "JOIN output_bindings b ON b.output_binding_id=o.output_binding_id "
        "JOIN social_destinations d ON d.social_destination_id=b.social_destination_id "
        "JOIN capability_readiness r ON r.social_destination_id=d.social_destination_id "
        "WHERE v.review_request_id=?", (review_id,),
    ).fetchone()
    moment = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    return bool(
        row is not None and row["delivery_enabled"] and row["profile_approved"]
        and row["enabled"] and row["status"] == "ready" and row["valid_until"] > moment
    )


def _production_status(connection: sqlite3.Connection) -> str:
    storage = connection.execute(
        "SELECT state,free_bytes,sampled_at FROM storage_samples "
        "ORDER BY storage_sample_id DESC LIMIT 1"
    ).fetchone()
    destinations = connection.execute(
        "SELECT d.destination_key,r.status,r.valid_until,r.reasons_json "
        "FROM social_destinations d JOIN capability_readiness r "
        "ON r.social_destination_id=d.social_destination_id "
        "ORDER BY d.destination_key"
    ).fetchall()
    delivery = connection.execute(
        "SELECT status,COUNT(*) count FROM post_records GROUP BY status ORDER BY status"
    ).fetchall()
    cleanup = int(connection.execute(
        "SELECT COUNT(*) FROM delivery_cleanup_tasks "
        "WHERE status IN ('pending','claimed','retry_wait','failed')"
    ).fetchone()[0])
    budget = connection.execute(
        "SELECT COALESCE(SUM(CASE WHEN status='settled' THEN settled_micro_usd "
        "ELSE worst_case_micro_usd END),0) used,"
        "COALESCE(MAX(daily_limit_micro_usd),0) hard_limit,"
        "COALESCE(MAX(daily_warning_micro_usd),0) warning_limit "
        "FROM gemini_budget_reservations WHERE accounting_day=? "
        "AND status IN ('reserved','settled','uncertain')",
        (datetime.now(timezone.utc).date().isoformat(),),
    ).fetchone()
    storage_text = (
        "missing (new work fails closed)" if storage is None
        else f"{storage['state']}; {int(storage['free_bytes']) / 1024**3:.1f} GiB free; "
             f"sampled {storage['sampled_at']}"
    )
    destination_items = "".join(
        "<li>" + escape(row["destination_key"]) + ": " + escape(row["status"])
        + " through " + escape(row["valid_until"])
        + (" — " + escape("; ".join(json.loads(row["reasons_json"])))
           if json.loads(row["reasons_json"]) else "") + "</li>"
        for row in destinations
    ) or "<li>No production destinations configured.</li>"
    delivery_text = ", ".join(
        f"{row['status']}={row['count']}" for row in delivery
    ) or "none"
    used = int(budget["used"])
    hard = int(budget["hard_limit"])
    warning = int(budget["warning_limit"])
    budget_text = f"${used / 1_000_000:.6f} conservative usage"
    if hard:
        budget_text += f" of ${hard / 1_000_000:.2f} daily hard limit"
    else:
        budget_text += "; no production reservation has recorded a limit yet"
    if warning and used >= warning:
        budget_text += "; warning threshold reached"
    return (
        "<aside class='production-status'><h3>Production safety status</h3>"
        f"<p><b>Storage:</b> {escape(storage_text)}</p>"
        f"<p><b>Gemini budget:</b> {escape(budget_text)}</p>"
        f"<p><b>Delivery:</b> {escape(delivery_text)}; cleanup attention={cleanup}</p>"
        f"<details><summary>Destination readiness</summary><ul>{destination_items}</ul></details>"
        "</aside>"
    )


def _delivery_controls(
    connection: sqlite3.Connection,
    review_id: int,
    *,
    interactive: bool,
    csrf_token: str,
) -> str:
    record = connection.execute(
        "SELECT pr.post_record_id,pr.status,pr.row_version,pr.eligible_at,pr.failure_reason,"
        "pr.external_post_id,pq.expires_at,a.final_publication_request_sent_at "
        "FROM post_requests pq JOIN post_records pr ON pr.post_request_id=pq.post_request_id "
        "LEFT JOIN post_attempts a ON a.post_record_id=pr.post_record_id "
        "AND a.attempt_number=pr.attempt_count WHERE pq.review_request_id=?",
        (review_id,),
    ).fetchone()
    if record is None:
        return ""
    parts = [
        f"<section class='delivery'><p><b>Delivery #{record['post_record_id']}</b>: "
        f"{escape(record['status'])}; eligible {escape(record['eligible_at'])}; "
        f"authorization expires {escape(record['expires_at'])}</p>"
    ]
    if record["external_post_id"]:
        parts.append(f"<p>Provider post ID: {escape(record['external_post_id'])}</p>")
    if record["failure_reason"]:
        parts.append(f"<p>{escape(record['failure_reason'])}</p>")
    if (
        interactive
        and record["status"] in {"pending", "claimed", "publishing", "retry_wait"}
        and record["final_publication_request_sent_at"] is None
    ):
        parts.append(
            "<form method='post' action='/commands'>"
            f"{_hidden('csrf_token', csrf_token)}{_hidden('command_kind', 'cancel_delivery')}"
            f"{_hidden('command_id', str(uuid.uuid4()))}"
            f"{_hidden('post_record_id', record['post_record_id'])}"
            f"{_hidden('row_version', record['row_version'])}"
            "<button type='submit'>Cancel delivery</button></form>"
        )
    if interactive and record["status"] == "publication_unknown":
        reconciliation = connection.execute(
            "SELECT * FROM reconciliation_requests WHERE post_record_id=? "
            "ORDER BY reconciliation_request_id DESC LIMIT 1", (record["post_record_id"],),
        ).fetchone()
        if reconciliation is None:
            parts.append(
                "<form method='post' action='/commands'>"
                f"{_hidden('csrf_token', csrf_token)}"
                f"{_hidden('command_kind', 'request_reconciliation')}"
                f"{_hidden('command_id', str(uuid.uuid4()))}"
                f"{_hidden('post_record_id', record['post_record_id'])}"
                "<button type='submit'>Request reconciliation</button></form>"
            )
        elif reconciliation["status"] == "needs_human":
            check = connection.execute(
                "SELECT reconciliation_check_id,outcome FROM reconciliation_checks "
                "WHERE reconciliation_request_id=? ORDER BY reconciliation_check_id DESC LIMIT 1",
                (reconciliation["reconciliation_request_id"],),
            ).fetchone()
            if check is not None:
                parts.append(
                    f"<p>Latest reconciliation check: {escape(check['outcome'])}</p>"
                    "<form method='post' action='/commands'>"
                    f"{_hidden('csrf_token', csrf_token)}"
                    f"{_hidden('command_kind', 'resolve_reconciliation')}"
                    f"{_hidden('command_id', str(uuid.uuid4()))}"
                    f"{_hidden('reconciliation_request_id', reconciliation['reconciliation_request_id'])}"
                    f"{_hidden('reconciliation_check_id', check['reconciliation_check_id'])}"
                    f"{_hidden('row_version', reconciliation['row_version'])}"
                    "<textarea name='note' maxlength='2000' required "
                    "placeholder='Record the evidence for this decision'></textarea>"
                    "<button name='decision' value='published' type='submit'>Mark published</button>"
                    "<button name='decision' value='not_published_cancel' type='submit'>Mark not published</button>"
                    "<button name='decision' value='leave_unknown' type='submit'>Leave unknown</button>"
                    "</form>"
                )
    parts.append("</section>")
    return "".join(parts)
