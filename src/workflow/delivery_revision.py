"""Append-only offline JPEG preparation and exact human approval commands.

The trust boundary is the same local OS owner as the dashboard. Fingerprints
bind commands to displayed evidence; they are not remote authentication tokens.
"""
from copy import deepcopy
from datetime import timedelta
from hashlib import sha256
from pathlib import Path
import json

from common.timestamps import parse_timestamp, serialize_timestamp
from .delivery_artifacts import read_review_source, prepare_review_bundle
from .store import canonical, digest, now


def source_evidence(store, review_id, *, account, destination, artifact_root):
    package, manifest, _ = read_review_source(store, review_id)
    row = store.connection.execute(
        "SELECT v.*,r.status render_status,r.content_package_id render_package_id,"
        "p.visual_recipe_id,o.output_request_id,o.output_identity,o.account,o.platform,"
        "o.output_binding_id,c.canonical_content_id,c.canonical_identity,c.canonical_hash,c.canonical_json,"
        "vr.recipe_json,vr.recipe_hash,b.account binding_account,b.platform binding_platform,"
        "pc.pipeline_id binding_pipeline,d.destination_key actual_destination,d.account_key destination_account,d.provider_account_id,"
        "br.revision_id,br.brief_json,br.source_snapshot_json,t.status thread_status "
        "FROM review_requests v JOIN content_packages p USING(content_package_id) "
        "JOIN render_runs r ON r.render_run_id=v.render_run_id "
        "JOIN visual_recipes vr ON vr.visual_recipe_id=p.visual_recipe_id "
        "JOIN output_requests o ON o.output_request_id=p.output_request_id "
        "JOIN canonical_contents c USING(canonical_content_id) JOIN content_jobs j USING(content_job_id) "
        "JOIN brief_revisions br ON br.revision_id=j.brief_revision_id "
        "JOIN content_threads t USING(thread_id) "
        "JOIN output_bindings b USING(output_binding_id) "
        "JOIN pipeline_capabilities pc USING(pipeline_capability_id) "
        "JOIN social_destinations d USING(social_destination_id) "
        "JOIN configuration_activations ca ON ca.configuration_release_id=d.configuration_release_id "
        "AND ca.scope_key='global' AND ca.status='active' WHERE v.review_request_id=?", (review_id,),
    ).fetchone()
    if (row is None or row["delivery_revision_id"] is not None
            or row["status"] not in {"awaiting_review", "approved"} or row["expires_at"] <= now()
            or row["render_status"] != "succeeded" or row["thread_status"] != "open"
            or row["render_package_id"] != row["content_package_id"]
            or row["binding_pipeline"] != "english"
            or not account or account != row["account"] or account != row["binding_account"]
            or package.get("account") != account or row["destination_account"] != account or row["platform"] != "instagram"
            or row["binding_platform"] != "instagram"
            or not destination or destination != row["destination_key"]
            or destination != row["actual_destination"]):
        raise ValueError("source review, thread, account or destination is not current")
    if (digest(json.loads(row["canonical_json"])) != row["canonical_hash"]
            or digest(json.loads(row["recipe_json"])) != row["recipe_hash"]
            or package.get("execution_mode") == "simulation"):
        raise ValueError("source canonical/visual evidence is invalid")
    root = Path(artifact_root).resolve(strict=True)
    for asset in manifest["assets"]:
        path = Path(asset["path"]).resolve(strict=True)
        if (not path.is_relative_to(root) or path.stat().st_size != asset["bytes"]
                or asset["bytes"] > 8_000_000 or sha256(path.read_bytes()).hexdigest() != asset["sha256"]):
            raise ValueError("source artifact containment, size or hash changed")
    keys = ("review_request_id", "content_package_id", "render_run_id", "package_hash", "manifest_hash",
            "visual_recipe_id", "recipe_hash", "output_request_id", "output_identity", "output_binding_id",
            "canonical_content_id", "canonical_identity", "canonical_hash", "revision_id",
            "account", "platform", "destination_key", "provider_account_id")
    return {**{key: row[key] for key in keys}, "visual_recipe": json.loads(row["recipe_json"]),
            "brief_hash": digest(json.loads(row["brief_json"])),
            "source_snapshot_hash": digest(json.loads(row["source_snapshot_json"]))}


def revision_fingerprint(package, manifest, lineage, root):
    return digest({"version": "delivery_revision_v1", "package": package, "manifest": manifest,
                   "lineage": lineage, "artifact_root": str(root)})


def prepare(store, review_id, *, account, destination, artifact_root, output, image_alt_text, command_id):
    """One explicit command converts trusted source bytes and persists an awaiting review.

    Arbitrary candidate.json imports are intentionally unsupported. Failed conversion
    may leave an unregistered directory; it is never discovered as delivery work.
    """
    root = Path(artifact_root).resolve(strict=True)
    output = Path(output).absolute()
    if not output.parent.resolve(strict=True).is_relative_to(root):
        raise ValueError("delivery output must be inside the artifact root")
    payload = digest({"kind": "prepare_delivery", "review_id": review_id, "account": account,
                      "destination": destination, "root": str(root), "output": str(output),
                      "image_alt_text": image_alt_text})
    with store.transaction():
        prior = store._command_receipt(command_id)
        if prior:
            if prior["payload_hash"] != payload:
                raise ValueError("command ID was reused with different input")
            return int(prior["result_record_id"])
        lineage = source_evidence(store, review_id, account=account, destination=destination, artifact_root=root)
        package, manifest, _ = read_review_source(store, review_id)
        if (not isinstance(image_alt_text, list) or len(image_alt_text) != len(manifest["assets"])
                or any(not isinstance(a, str) or not a.strip() or len(a) > 1000 for a in image_alt_text)):
            raise ValueError("explicit nonempty per-image alt text is required in slide order (max 1000 characters)")
        bundle = prepare_review_bundle(store, review_id, artifact_root=root, output=output)
        bundle["package"]["image_alt_text"] = list(image_alt_text)
        bundle["manifest"]["content_hash"] = digest(bundle["package"])
        for asset, alt in zip(bundle["manifest"]["assets"], image_alt_text, strict=True):
            asset["alt_text"] = alt
        fingerprint = revision_fingerprint(bundle["package"], bundle["manifest"], lineage, root)
        moment = now()
        revision = store.connection.execute(
            "INSERT INTO delivery_revisions(source_review_request_id,package_json,package_hash,manifest_json,"
            "manifest_hash,lineage_json,artifact_root,fingerprint,created_at) VALUES (?,?,?,?,?,?,?,?,?)",
            (review_id, canonical(bundle["package"]), digest(bundle["package"]), canonical(bundle["manifest"]),
             digest(bundle["manifest"]), canonical(lineage), str(root), fingerprint, moment),
        ).lastrowid
        cycle = store.connection.execute(
            "SELECT MAX(review_cycle_number)+1 FROM review_requests WHERE content_package_id=? AND render_run_id=?",
            (lineage["content_package_id"], lineage["render_run_id"]),
        ).fetchone()[0]
        result = int(store.connection.execute(
            "INSERT INTO review_requests(content_package_id,render_run_id,review_cycle_number,package_hash,"
            "manifest_hash,status,expires_at,created_at,destination_key,delivery_revision_id) "
            "VALUES (?,?,?,?,?,'awaiting_review',?,?,?,?)",
            (lineage["content_package_id"], lineage["render_run_id"], cycle, digest(bundle["package"]),
             digest(bundle["manifest"]), serialize_timestamp(parse_timestamp(moment)+timedelta(days=14)),
             moment, destination, revision),
        ).lastrowid)
        # Database is authoritative. The export is informative and never imported.
        (output / "candidate.json").write_text(canonical(bundle)+"\n", encoding="utf-8")
        store.connection.execute(
            "INSERT INTO human_command_receipts(command_id,command_kind,actor_id,payload_hash,result_record_id,created_at) "
            "VALUES (?,'prepare_delivery','local_owner',?,?,?)", (command_id, payload, result, moment),
        )
        return result


def overlay(store, row):
    """Resolve revision evidence while retaining original package/render lineage IDs."""
    row = dict(row)
    revision_id = row.get("delivery_revision_id")
    if revision_id is None:
        return row
    revision = store.connection.execute("SELECT * FROM delivery_revisions WHERE delivery_revision_id=?",
                                        (revision_id,)).fetchone()
    package = json.loads(revision["package_json"])
    manifest = json.loads(revision["manifest_json"])
    lineage = json.loads(revision["lineage_json"])
    current = source_evidence(store, revision["source_review_request_id"], account=row["account"],
                              destination=row["destination_key"], artifact_root=revision["artifact_root"])
    if (current != lineage or row["content_package_id"] != lineage["content_package_id"]
            or row["render_run_id"] != lineage["render_run_id"]
            or revision_fingerprint(package, manifest, lineage, revision["artifact_root"]) != revision["fingerprint"]):
        raise ValueError("delivery source provenance changed")
    source_package, source_manifest, _ = read_review_source(store, revision["source_review_request_id"])
    expected = deepcopy(source_package)
    expected.update(delivery_ready=True, delivery_preparation=package.get("delivery_preparation"),
                    image_alt_text=package.get("image_alt_text"))
    source = package.get("delivery_preparation", {}).get("source", {})
    if (expected != package or manifest.get("source_assets") != source_manifest["assets"]
            or any(source.get(k) != lineage[k] for k in ("review_request_id", "content_package_id", "render_run_id", "package_hash", "manifest_hash", "destination_key"))
            or manifest.get("source") != source
            or not isinstance(package.get("image_alt_text"), list)
            or len(package["image_alt_text"]) != len(manifest["assets"])):
        raise ValueError("delivery copy, alt text or provenance differs from source")
    for asset, alt in zip(manifest["assets"], package["image_alt_text"], strict=True):
        path = Path(asset["path"]).resolve(strict=True)
        if (not path.is_relative_to(Path(revision["artifact_root"])) or asset.get("alt_text") != alt
                or not isinstance(alt, str) or not alt.strip() or len(alt) > 1000):
            raise ValueError("delivery asset containment or alt text changed")
    row.update(package_json=revision["package_json"], content_hash=revision["package_hash"],
               manifest_json=revision["manifest_json"], revision_fingerprint=revision["fingerprint"],
               lineage=lineage)
    return row


def command_fingerprint(row):
    return digest({"version": "jpeg_review_command_v1", "review_id": row["review_request_id"],
                   "row_version": row["row_version"], "status": row["status"],
                   "revision": row["fingerprint"], "expires_at": row["expires_at"]})


def command_row(store, review_id):
    row = store.connection.execute(
        "SELECT v.*,d.fingerprint,d.package_json,d.manifest_json,d.lineage_json FROM review_requests v "
        "JOIN delivery_revisions d USING(delivery_revision_id) WHERE v.review_request_id=?", (review_id,),
    ).fetchone()
    if row is None:
        raise ValueError("a delivery revision review is required")
    return row


def check_command(store, review_id, *, row_version, fingerprint, account, destination):
    row = command_row(store, review_id)
    if (type(row_version) is not int or row_version != row["row_version"]
            or fingerprint != command_fingerprint(row)
            or account != json.loads(row["package_json"])["account"]
            or destination != row["destination_key"]):
        raise ValueError("stale command fingerprint, version, account or destination")
    return row


def approve(store, review_id, *, row_version, fingerprint, account, destination, reviewed_images, command_id):
    payload = digest({"kind": "approve_jpeg", "review_id": review_id, "row_version": row_version,
                      "fingerprint": fingerprint, "account": account, "destination": destination,
                      "reviewed_images": reviewed_images})
    with store.transaction():
        prior = store._command_receipt(command_id)
        if prior:
            if prior["payload_hash"] != payload:
                raise ValueError("command ID was reused with different input")
            return int(prior["result_record_id"])
        row = check_command(store, review_id, row_version=row_version, fingerprint=fingerprint,
                            account=account, destination=destination)
        if row["status"] != "awaiting_review":
            raise ValueError("only an awaiting JPEG review can be approved")
        context = store._review_delivery_context(review_id, moment=now(), required_status="awaiting_review")
        if reviewed_images != [a["sha256"] for a in context["assets"]]:
            raise ValueError("acknowledge every displayed JPEG hash in order")
        store.connection.execute(
            "UPDATE review_requests SET status='approved',actor_id='local_owner',decided_at=?,"
            "decision_note='Exact JPEGs, caption, aggregate and per-image alt text, and destination approved',"
            "row_version=row_version+1 WHERE review_request_id=?", (now(), review_id),
        )
        store.connection.execute(
            "INSERT INTO human_command_receipts(command_id,command_kind,actor_id,payload_hash,result_record_id,created_at) "
            "VALUES (?,'approve_jpeg','local_owner',?,?,?)", (command_id, payload, review_id, now()),
        )
        return review_id
