"""Fully local rehearsal composition; no real provider or credential selection."""
from __future__ import annotations

from contextlib import contextmanager, ExitStack
from datetime import timedelta
from hashlib import sha256
from pathlib import Path
from tempfile import mkdtemp
from unittest.mock import patch
from urllib.parse import unquote, urlsplit
import json
import os

from PIL import Image, ImageDraw

from database.current import initialize_database
from detection.configuration import load_manifest
from detection.store import DetectionStore
from .delivery import CredentialedPostingAgent, DeliveryError, R2TransientRelay
from .delivery_artifacts import prepare_bundle
from .delivery_fixtures import production_configuration, seed_review
from .store import WorkflowStore, canonical, digest, now

MODE = "offline_delivery_simulation_v1"
DESTINATION = "instagram:simulation"


@contextmanager
def offline_only():
    """Defense in depth for this single-threaded CLI, including DNS and sockets."""
    def refused(*args, **kwargs):
        raise RuntimeError("network access is forbidden in offline delivery simulation")
    with ExitStack() as stack:
        for target in ("socket.socket.connect", "socket.socket.connect_ex",
                       "socket.create_connection", "socket.getaddrinfo", "socket.socket.sendto"):
            stack.enter_context(patch(target, refused))
        yield


def initialize_simulation(workspace=None, *, slide_count=6):
    if type(slide_count) is not int or not 4 <= slide_count <= 6:
        raise ValueError("simulation requires 4–6 slides")
    root = Path(mkdtemp(prefix="content-factory-simulation-")) if workspace is None else Path(workspace).absolute()
    if workspace is not None:
        root.mkdir(exist_ok=False)
    root = root.resolve()
    database = root / "simulation.sqlite"
    initialize_database(database)
    with DetectionStore(database) as detection:
        detection.apply_manifest(load_manifest(Path(__file__).resolve().parents[2] / "config/releases/detection.json"))
    source_dir = root / "review-png"
    source_dir.mkdir()
    assets = []
    for ordinal in range(1, slide_count + 1):
        image = Image.new("RGB", (1080, 1350), (220, 230, 240))
        ImageDraw.Draw(image).text((80, 80), f"SIMULATION ONLY - synthetic slide {ordinal}", fill="black")
        path = source_dir / f"slide-{ordinal:02d}.png"
        image.save(path, format="PNG")
        data = path.read_bytes()
        assets.append({"role": "preview_png", "ordinal": ordinal, "path": str(path),
                       "mime": "image/png", "width": 1080, "height": 1350,
                       "bytes": len(data), "sha256": sha256(data).hexdigest()})
    from .active_visual_profiles import EXPRESSION_ROLES
    from .content_contract import english_positions
    package = {"schema_version": "synthetic_delivery_fixture_v1", "platform": "instagram",
               "account": "simulation", "format": "instagram_static_carousel_v2",
               "delivery_ready": False, "execution_mode": "simulation",
               "caption": "SIMULATION ONLY. Synthetic offline carousel; no English quality claim.",
               "alt_text": f"{slide_count} numbered synthetic slides used to rehearse delivery.",
               "visual_units": [{"role": role, "title": "Synthetic", "body": "Fixture", "claim_ids": []}
                                for role in [EXPRESSION_ROLES[i] for i in english_positions(slide_count)]]}
    manifest = {"review_only": True, "content_hash": digest(package), "assets": assets}
    (source_dir / "source.json").write_text(canonical({"package": package, "manifest": manifest}) + "\n")
    bundle = prepare_bundle(package, manifest, lineage={"kind": MODE, "destination_key": DESTINATION},
                            artifact_root=root, output=root / "delivery-jpeg")
    with WorkflowStore(database, catalog_kind="production") as store:
        configuration = production_configuration()
        configuration.update(approved_by="synthetic_fixture_not_human", approved_at=now())
        destination = configuration["destinations"][0]
        destination.update(destination_key=DESTINATION, account_key="simulation", provider_account_id="0")
        for binding in configuration["bindings"]:
            binding["destination_key"] = DESTINATION
        store.register_production_configuration(configuration)
        destination_id = store.connection.execute("SELECT social_destination_id FROM social_destinations").fetchone()[0]
        store.record_destination_readiness(destination_id, status="ready", reasons=[],
                                          facts={"mode": MODE, "real_readiness": False},
                                          valid_for=timedelta(days=1))
        review_id = seed_review(store, root, bundle=bundle)
    (root / "simulation.json").write_text(canonical({"mode": MODE, "database": str(database),
                                                    "review_id": review_id}) + "\n")
    return root


@contextmanager
def simulation_store(workspace, *, read_only=False):
    root = Path(workspace).resolve(strict=True)
    marker = json.loads((root / "simulation.json").read_text())
    database = root / "simulation.sqlite"
    if (marker.get("mode") != MODE or marker.get("database") != str(database)
            or database.is_symlink()):
        raise ValueError("not an isolated simulation workspace")
    # Inspect before opening for writes. Never accept an arbitrary operator DB.
    with WorkflowStore(database, read_only=True) as check:
        destinations = check.connection.execute("SELECT destination_key,provider_account_id FROM social_destinations").fetchall()
        packages = check.connection.execute("SELECT package_json FROM content_packages").fetchall()
        if ([tuple(d) for d in destinations] != [(DESTINATION, "0")]
                or not packages or any(json.loads(p[0]).get("execution_mode") != "simulation" for p in packages)):
            raise ValueError("database is not synthetic simulation evidence")
    with WorkflowStore(database, read_only=read_only, catalog_kind="production") as store:
        yield store


def _local_directory(root, name):
    root = Path(root).resolve(strict=True)
    directory = root / name
    if directory.is_symlink() or directory.resolve().parent != root:
        raise ValueError("simulation directory escapes workspace")
    return directory


class LocalObjectClient:
    """Tiny on-disk fake of the S3 methods used by the existing exact-byte relay."""
    def __init__(self, root):
        self.root = _local_directory(root, "fake-r2")
        self.root.mkdir(exist_ok=True)

    def _path(self, key):
        path = (self.root / key).resolve()
        if not path.is_relative_to(self.root.resolve()) or path == self.root.resolve():
            raise ValueError("fake object path escapes simulation")
        return path

    def put_object(self, *, Bucket, Key, Body, ContentType, CacheControl, Metadata):
        path = self._path(Key)
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("xb") as handle:
            handle.write(Body)
        path.with_suffix(".json").write_text(canonical({"ContentLength": len(Body),
                                                      "ContentType": ContentType, "Metadata": Metadata}))

    def head_object(self, *, Bucket, Key):
        path = self._path(Key)
        if not path.exists():
            error = FileNotFoundError("simulated object absent")
            error.response = {"Error": {"Code": "NoSuchKey"}}
            raise error
        metadata = json.loads(path.with_suffix(".json").read_text())
        metadata["ContentLength"] = path.stat().st_size
        return metadata

    def delete_object(self, *, Bucket, Key):
        path = self._path(Key)
        path.unlink(missing_ok=True)
        path.with_suffix(".json").unlink(missing_ok=True)

    def get_exact_bytes(self, url, *, expected_bytes, timeout, stage):
        parts = urlsplit(url)
        if parts.scheme != "https" or parts.netloc != "simulation.invalid":
            raise ValueError("fake fetch accepts only simulation.invalid")
        data = self._path(unquote(parts.path.lstrip("/"))).read_bytes()
        if len(data) != expected_bytes:
            raise ValueError("fake object length differs")
        return data


def local_relay(root):
    client = LocalObjectClient(root)
    return R2TransientRelay({"r2_bucket_name": "simulation", "r2_account_id": "simulation",
                             "r2_public_domain": "https://simulation.invalid"},
                            client=client, transport=client)


class SimulatedInstagramAdapter:
    execution_mode = "simulation"

    def __init__(self, root, *, outcome="success"):
        if outcome not in {"success", "unknown", "outage"}:
            raise ValueError("unsupported simulated outcome")
        self.root, self.outcome = Path(root), outcome
        self.relay = local_relay(root)

    def stage(self, context, record):
        if (context["destination_key"] != DESTINATION or context["provider_account_id"] != "0"
                or context["package"].get("execution_mode") != "simulation"):
            raise ValueError("fake adapter requires the synthetic destination and package")
        for asset in context["assets"]:
            # Intent is durable before staging, so a failed probe still has cleanup evidence.
            key = f"simulation/{context['post_attempt_id']}/{asset['ordinal']}.jpg"
            resource = record(resource_type="r2_object", remote_id=key, asset_ordinal=asset["ordinal"],
                              safe_metadata={"mode": MODE, "sha256": asset["sha256"]})
            self.relay.stage(context, asset, key=key)
            record(resource_id=resource, status="ready")
            record(resource_type="external_media", remote_id=f"simulated:child:{context['post_attempt_id']}:{asset['ordinal']}",
                   asset_ordinal=asset["ordinal"], status="ready",
                   safe_metadata={"mode": MODE, "sha256": asset["sha256"]})
        if self.outcome == "outage":
            raise DeliveryError("simulated_outage", "fake staging outage before final marker", True, "stage")
        parent = f"simulated:container:{context['post_attempt_id']}"
        record(resource_type="external_media", remote_id=parent, status="ready", safe_metadata={"mode": MODE})
        return {"parent": parent}

    def publish(self, context, staged):
        receipt = {"mode": MODE, "post_attempt_id": context["post_attempt_id"],
                   "publication_identity": context["publication_identity"],
                   "caption": context["package"]["caption"],
                   "alt_text": context["package"]["alt_text"],
                   "package_hash": context["package_hash"], "manifest_hash": context["manifest_hash"],
                   "submitted_sha256": [a["sha256"] for a in context["assets"]],
                   "parent": staged["parent"], "outcome": self.outcome,
                   "external_post_id": f"simulated:post:{context['post_record_id']}"}
        directory = _local_directory(self.root, "fake-provider")
        directory.mkdir(exist_ok=True)
        # Exclusive evidence also catches accidental duplicate final calls across restarts.
        with (directory / f"send-{context['post_record_id']}.json").open("x") as handle:
            handle.write(canonical(receipt) + "\n")
            handle.flush()
            os.fsync(handle.fileno())
        if self.outcome == "unknown":
            raise DeliveryError("simulated_timeout", "fake final response lost; acceptance is unknown", False, "publish")
        return receipt["external_post_id"]


def review_identity(row):
    return digest({key: row[key] for key in ("review_request_id", "package_hash", "manifest_hash", "destination_key")})


def post_now(store, *, review_id, row_version, identity, destination, command_id):
    row = store.connection.execute("SELECT * FROM review_requests WHERE review_request_id=?", (review_id,)).fetchone()
    if row is None or identity != review_identity(row) or destination != row["destination_key"] or destination != DESTINATION:
        raise ValueError("exact displayed JPEG review identity and simulation destination are required")
    return store.authorize_post_now(review_id, row_version=row_version, command_id=command_id)


def run_once(store, root, *, outcome="success"):
    return CredentialedPostingAgent(store, artifact_root=root, instance_id="offline-simulation",
                                   adapters={"instagram": SimulatedInstagramAdapter(root, outcome=outcome)}).run_once()


def report(store):
    """Read-only projection of persisted evidence, with no readiness writes."""
    def rows(query):
        return [dict(row) for row in store.connection.execute(query)]
    sends = []
    for path in sorted(_local_directory(store.path.parent, "fake-provider").glob("send-*.json")):
        try:
            sends.append(json.loads(path.read_text()))
        except (OSError, ValueError):
            sends.append({"mode": MODE, "evidence_file": path.name, "outcome": "incomplete_evidence"})
    reviews = rows("SELECT * FROM review_requests ORDER BY review_request_id")
    for review in reviews:
        review["review_identity"] = review_identity(review)
        try:
            store._review_delivery_context(review["review_request_id"], moment=now())
            review["local_readiness"] = "eligible_for_explicit_simulated_post_now"
        except (ValueError, OSError) as error:
            review["local_readiness"] = str(error)
    return {"mode": MODE, "real_publication": False, "database": str(store.path),
            "reviews": reviews,
            "packages": rows("SELECT content_package_id,package_json,content_hash FROM content_packages"),
            "fake_sends": sends,
            "review_assets": rows("SELECT asset_role,ordinal,local_path,mime_type,width,height,bytes,sha256 FROM render_assets"),
            "authorizations": rows("SELECT * FROM post_requests"),
            "commands": rows("SELECT * FROM human_command_receipts"),
            "posts": rows("SELECT * FROM post_records"), "attempts": rows("SELECT * FROM post_attempts"),
            "resources": rows("SELECT * FROM publication_resources"),
            "cleanup": rows("SELECT * FROM delivery_cleanup_tasks"),
            "reconciliation": rows("SELECT * FROM reconciliation_requests"),
            "checks": rows("SELECT * FROM reconciliation_checks"),
            "decisions": rows("SELECT * FROM human_reconciliation_decisions")}
