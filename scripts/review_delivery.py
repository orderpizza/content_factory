"""Offline owner commands: prepare → report → approve → report → post-now. Never send."""
import argparse
import base64
from hashlib import sha256
from html import escape
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from workflow.delivery_revision import prepare, approve, command_row, command_fingerprint
from workflow.offline import offline_only
from workflow.store import WorkflowStore


def report(store, review_id, output):
    row = command_row(store, review_id)
    # Reports remain available when readiness is revoked. Validate frozen source
    # and bytes without treating this read as a capability refresh or approval.
    lineage = json.loads(row["lineage_json"])
    context = dict(row)
    context.update(account=lineage["account"], platform="instagram", pipeline_id="english",
                   content_hash=row["package_hash"], config_json="{}")
    context = store._validate_delivery_artifacts(context)
    package = context["package"]
    images = context["assets"]
    evidence = {"review_id": review_id, "status": row["status"], "row_version": row["row_version"],
                "fingerprint": command_fingerprint(row), "account": lineage["account"],
                "destination": row["destination_key"], "provider_account_id": lineage["provider_account_id"],
                "expires_at": row["expires_at"], "caption": package["caption"],
                "alt_text": package["alt_text"], "image_alt_text": package["image_alt_text"],
                "reviewed_images": [a["sha256"] for a in images], "lineage": lineage,
                "package_hash": row["package_hash"], "manifest_hash": row["manifest_hash"],
                "post_requests": [dict(r) for r in store.connection.execute(
                    "SELECT q.post_request_id,q.publication_identity,q.status,p.post_record_id,p.status delivery_status "
                    "FROM post_requests q JOIN post_records p USING(post_request_id) WHERE q.review_request_id=?",
                    (review_id,))], "report_sends_content": False}
    from workflow.instagram_receipts import receipt_summary
    evidence['publication_evidence'] = [dict(post_record_id=p['post_record_id'], **receipt_summary(store, p['post_record_id']))
                                       for p in evidence['post_requests']]
    summary = {key: evidence[key] for key in ("review_id", "status", "row_version", "fingerprint",
               "account", "destination", "provider_account_id", "expires_at")}
    html = ['<!doctype html><html lang="en"><meta charset="utf-8">',
            '<meta http-equiv="Content-Security-Policy" content="default-src \'none\'; img-src data:; style-src \'unsafe-inline\'">',
            '<title>Exact JPEG delivery review</title><style>body{max-width:960px;margin:2rem auto;font:18px sans-serif}img{max-width:100%}pre{white-space:pre-wrap;overflow-wrap:anywhere}</style>',
            '<h1>Exact JPEG delivery review</h1><p>Inspect every image in order, caption, aggregate and per-image alt text, account and destination. Approval creates no delivery request. Post now is separate; this CLI never sends.</p>',
            '<pre>' + escape(json.dumps(summary, ensure_ascii=False, indent=2)) + '</pre>',
            '<h2>Exact caption</h2><pre>' + escape(package["caption"]) + '</pre>',
            '<h2>Aggregate alt text</h2><pre>' + escape(package["alt_text"]) + '</pre>']
    if evidence['publication_evidence']:
        html += ['<h2>Publication receipt and reconciliation</h2><pre>'
                 + escape(json.dumps(evidence['publication_evidence'], ensure_ascii=False, indent=2)) + '</pre>']
    for asset in images:
        data = Path(asset["path"]).read_bytes()
        if sha256(data).hexdigest() != asset["sha256"]:
            raise ValueError("JPEG changed while building review report")
        html += [f'<h2>Slide {asset["ordinal"]}</h2><p>{escape(asset["alt_text"])}</p>',
                 f'<p>SHA256: {asset["sha256"]}</p>',
                 '<img alt="' + escape(asset["alt_text"], quote=True) + '" src="data:image/jpeg;base64,'
                 + base64.b64encode(data).decode() + '">']
    html += ['<details><summary>Full immutable lineage, hashes and authorization evidence</summary><pre>'
             + escape(json.dumps(evidence, ensure_ascii=False, indent=2)) + '</pre></details>', '</html>']
    # Never replace a source image, DB or earlier report through a report path.
    with Path(output).open("x", encoding="utf-8") as handle:
        handle.write("\n".join(html))
    return evidence


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", type=Path, required=True)
    commands = parser.add_subparsers(dest="action", required=True)
    prep = commands.add_parser("prepare")
    prep.add_argument("--source-review-id", type=int, required=True)
    prep.add_argument("--artifacts", type=Path, required=True)
    prep.add_argument("--output", type=Path, required=True)
    prep.add_argument("--image-alt-text", type=Path, required=True, help="UTF-8 JSON array, one description per slide")
    view = commands.add_parser("report")
    view.add_argument("--review-id", type=int, required=True)
    view.add_argument("--output", type=Path, required=True, help="new self-contained local HTML file")
    approval = commands.add_parser("approve")
    post = commands.add_parser("post-now")
    for cmd in (prep, approval, post):
        cmd.add_argument("--account", required=True)
        cmd.add_argument("--destination", required=True)
        cmd.add_argument("--command-id", required=True)
    for cmd in (approval, post):
        cmd.add_argument("--review-id", type=int, required=True)
        cmd.add_argument("--row-version", type=int, required=True)
        cmd.add_argument("--fingerprint", required=True)
    approval.add_argument("--reviewed-images", nargs="+", required=True, help="all displayed SHA256 values in slide order")
    approval.add_argument("--confirm-reviewed-all", action="store_true",
                          help="I inspected all JPEGs, caption, aggregate/per-image alt text and destination")
    args = parser.parse_args()
    if args.action == "approve" and not args.confirm_reviewed_all:
        parser.error("approval requires --confirm-reviewed-all")
    with offline_only(), WorkflowStore(args.database, read_only=args.action == "report",
                                       catalog_kind="production", enforce_storage=True) as store:
        if args.action == "prepare":
            result = prepare(store, args.source_review_id, account=args.account, destination=args.destination,
                             artifact_root=args.artifacts, output=args.output,
                             image_alt_text=json.loads(args.image_alt_text.read_text(encoding="utf-8")),
                             command_id=args.command_id)
        elif args.action == "report":
            result = report(store, args.review_id, args.output)
        else:
            values = dict(row_version=args.row_version, fingerprint=args.fingerprint, account=args.account,
                          destination=args.destination, command_id=args.command_id)
            if args.action == "approve":
                result = approve(store, args.review_id, reviewed_images=args.reviewed_images, **values)
            else:
                result = store.authorize_post_now(args.review_id, **values)
        print(json.dumps({"action": args.action, "result": result, "sent": False}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
