"""Offline JPEG candidates. Preparation never grants review or posting approval."""
from __future__ import annotations

from copy import deepcopy
from hashlib import sha256
from io import BytesIO
from pathlib import Path
import json

from PIL import Image, __version__ as pillow_version, features

from .store import canonical, digest

PROFILE = "instagram_english_jpeg_v1"
MAX_BYTES = 8_000_000  # Conservative local bound, not a claim about API quota.
SIZE = (1080, 1350)


def prepare_bundle(package, manifest, *, lineage, artifact_root, output):
    """Create a new, unapproved candidate directory; never overwrite source files.

    Byte determinism is scoped to the recorded Pillow/libjpeg build. A different
    encoder still needs a new manifest and human review, even if pixels agree.
    """
    sources = manifest.get("assets", [])
    if (manifest.get("review_only") is not True
            or manifest.get("content_hash") != digest(package)
            or package.get("delivery_ready") is True
            or not 4 <= len(sources) <= 6
            or [a.get("ordinal") for a in sources] != list(range(1, len(sources) + 1))
            or len(package.get("visual_units", [])) != len(sources)):
        raise ValueError("preparation requires an ordered 4–6 slide review-only English package")
    if package.get("platform") != "instagram":
        raise ValueError("only Instagram candidates are supported")
    if not isinstance(package.get("caption"), str) or not isinstance(package.get("alt_text"), str):
        raise ValueError("caption and alt text must be frozen before preparation")
    root = Path(artifact_root).resolve(strict=True)
    encoded = []
    for asset in sources:
        path = Path(asset["path"]).resolve(strict=True)
        if (not path.is_relative_to(root) or path.suffix.lower() != ".png"
                or asset.get("role") != "preview_png" or asset.get("mime") != "image/png"
                or (asset.get("width"), asset.get("height")) != SIZE
                or not 0 < asset.get("bytes", 0) <= MAX_BYTES
                or path.stat().st_size != asset["bytes"]):
            raise ValueError("source PNG path, type, geometry or size is invalid")
        with path.open("rb") as handle:
            data = handle.read(MAX_BYTES + 1)
        if len(data) != asset["bytes"] or sha256(data).hexdigest() != asset["sha256"]:
            raise ValueError("source PNG hash changed")
        with Image.open(BytesIO(data)) as source:
            if (source.format != "PNG" or source.size != SIZE or source.mode != "RGB"
                    or getattr(source, "n_frames", 1) != 1
                    or source.info.get("icc_profile") or source.getexif()):
                raise ValueError("source must be a single RGB PNG at 1080×1350 without ICC or EXIF metadata")
            # No resize, layout, overlays, metadata copying or automatic alpha flattening.
            source.load()
            image = Image.new("RGB", SIZE)
            image.paste(source)
            stream = BytesIO()
            image.save(stream, format="JPEG", quality=92, subsampling=0,
                       optimize=False, progressive=False)
            jpeg = stream.getvalue()
        if not 0 < len(jpeg) <= MAX_BYTES:
            raise ValueError("prepared JPEG exceeds the local size bound")
        with Image.open(BytesIO(jpeg)) as check:
            if check.format != "JPEG" or check.size != SIZE:
                raise ValueError("prepared JPEG failed validation")
            check.verify()
        encoded.append(jpeg)
    output = Path(output).absolute()
    output.mkdir(parents=False, exist_ok=False)
    output = output.resolve()
    assets = []
    for ordinal, jpeg in enumerate(encoded, 1):
        path = output / f"slide-{ordinal:02d}.jpg"
        with path.open("xb") as handle:
            handle.write(jpeg)
        assets.append({"role": "delivery_jpeg", "ordinal": ordinal, "path": str(path),
                       "mime": "image/jpeg", "width": SIZE[0], "height": SIZE[1],
                       "bytes": len(jpeg), "sha256": sha256(jpeg).hexdigest()})
    source_identity = {**lineage, "package_hash": digest(package), "manifest_hash": digest(manifest)}
    candidate = deepcopy(package)
    candidate.update(delivery_ready=True, delivery_preparation={
        "profile": PROFILE, "source": source_identity,
    })
    delivery_manifest = {
        "schema_version": "render_manifest_v1", "renderer": "offline_png_to_jpeg_v1",
        "profile_id": PROFILE, "review_only": False, "content_hash": digest(candidate),
        "pillow_version": pillow_version, "libjpeg_version": features.version_codec("jpg"),
        "encoder": {"quality": 92, "subsampling": 0, "optimize": False, "progressive": False},
        "source": source_identity, "source_assets": deepcopy(sources), "assets": assets,
    }
    bundle = {"schema_version": "delivery_candidate_v1", "requires_new_review": True,
              "authorization": None, "package": candidate, "manifest": delivery_manifest}
    (output / "candidate.json").write_text(canonical(bundle) + "\n", encoding="utf-8")
    return bundle


def prepare_review_bundle(store, review_id, *, artifact_root, output):
    """Read a frozen PNG review; export a candidate only, with no database writes."""
    row = store.connection.execute(
        "SELECT v.*,p.package_json,p.content_hash,r.manifest_json,j.pipeline_id "
        "FROM review_requests v JOIN content_packages p USING(content_package_id) "
        "JOIN render_runs r ON r.render_run_id=v.render_run_id "
        "JOIN output_requests o ON o.output_request_id=p.output_request_id "
        "JOIN canonical_contents c USING(canonical_content_id) "
        "JOIN content_jobs j USING(content_job_id) WHERE v.review_request_id=?", (review_id,),
    ).fetchone()
    if row is None or row["pipeline_id"] != "english":
        raise ValueError("an existing English review is required")
    package, manifest = json.loads(row["package_json"]), json.loads(row["manifest_json"])
    if digest(package) != row["package_hash"] or digest(manifest) != row["manifest_hash"]:
        raise ValueError("source review hashes differ from persisted evidence")
    stored = [dict(a) for a in store.connection.execute(
        "SELECT asset_role role,ordinal,local_path path,mime_type mime,width,height,bytes,sha256 "
        "FROM render_assets WHERE render_run_id=? AND deleted_at IS NULL ORDER BY ordinal",
        (row["render_run_id"],),
    )]
    if not stored or stored != [{k: a.get(k) for k in stored[0]} for a in manifest.get("assets", [])]:
        raise ValueError("source assets differ from persisted manifest")
    return prepare_bundle(package, manifest, lineage={
        "review_request_id": review_id, "render_run_id": row["render_run_id"],
        "content_package_id": row["content_package_id"], "source_database": str(store.path),
        "source_review_status": row["status"], "destination_key": row["destination_key"],
    }, artifact_root=artifact_root, output=output)
