"""Exact review assets and persisted review-command forms."""

from __future__ import annotations

from html import escape
import json
import sqlite3
import uuid


def _hidden(name: str, value: object) -> str:
    return f"<input type='hidden' name='{escape(name)}' value='{escape(str(value))}'>"


def _review_preview(
    connection: sqlite3.Connection,
    review_id: int,
    *,
    interactive: bool,
    csrf_token: str,
) -> str:
    review = connection.execute(
        "SELECT v.status,v.row_version,p.package_json,r.render_run_id,vr.recipe_json,vr.selection_provenance_json "
        "FROM review_requests v JOIN content_packages p "
        "ON p.content_package_id=v.content_package_id "
        "JOIN render_runs r ON r.render_run_id=v.render_run_id "
        "JOIN visual_recipes vr ON vr.visual_recipe_id=r.visual_recipe_id "
        "WHERE v.review_request_id=?",
        (review_id,),
    ).fetchone()
    if review is None:
        return ""
    package = json.loads(review["package_json"])
    public_text = package.get("public_text") or package.get("caption") or ""
    assets = connection.execute(
        "SELECT render_asset_id,ordinal FROM render_assets WHERE render_run_id=? "
        "AND asset_role=CASE WHEN EXISTS (SELECT 1 FROM render_assets d "
        "WHERE d.render_run_id=render_assets.render_run_id AND d.asset_role='delivery_jpeg') "
        "THEN 'delivery_jpeg' ELSE 'preview_png' END ORDER BY ordinal LIMIT 14",
        (review["render_run_id"],),
    ).fetchall()
    images = "".join(
        f"<img src='/asset?render_asset_id={asset['render_asset_id']}' "
        f"alt='Slide {asset['ordinal']}: {escape(str(package.get('alt_text', 'Review image')))}' "
        "style='max-width:220px;height:auto;margin:.35rem'>"
        for asset in assets
    )
    parts = [
        f"<div class='review-preview'><p><b>Review #{review_id}</b>: "
        f"{escape(review['status'])}</p><div>{images}</div>"
        f"<pre style='white-space:pre-wrap'>{escape(str(public_text))}</pre>"
    ]
    parts.append("<details><summary>Immutable visual recipe and selection</summary><pre>"
                 + escape(json.dumps({"recipe": json.loads(review["recipe_json"]), "selection": json.loads(review["selection_provenance_json"])}, ensure_ascii=False, indent=2))
                 + "</pre></details>")
    if interactive and review["status"] == "awaiting_review":
        common = (
            f"{_hidden('csrf_token', csrf_token)}"
            f"{_hidden('review_id', review_id)}"
            f"{_hidden('row_version', review['row_version'])}"
        )
        parts.append(
            "<form method='post' action='/commands'>"
            f"{common}{_hidden('command_kind', 'review_approved')}"
            f"{_hidden('command_id', str(uuid.uuid4()))}"
            "<button type='submit'>Accept review</button></form>"
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
    parts.append("</div>")
    return "".join(parts)
