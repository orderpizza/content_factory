"""Bounded, thread-first read model for the local editorial scaffold."""

from __future__ import annotations

from html import escape
from datetime import datetime, timezone
import json
import sqlite3
import uuid


from .planning import render_threads as render_workflow_trace

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
        "missing (planning remains available; downstream admission is separate)" if storage is None
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
