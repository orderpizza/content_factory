"""Offline safety journeys through the real durable store and local fake providers."""
from copy import deepcopy
from hashlib import sha256
from pathlib import Path
import json
import socket
import subprocess
import sys

import pytest
from PIL import Image

from workflow.delivery import CredentialedPostingAgent, PublicationReconciliationWorker, R2CleanupWorker
from workflow.delivery_artifacts import prepare_bundle, prepare_review_bundle
from workflow.delivery_fixtures import seed_review
from workflow.delivery_simulation import (
    DESTINATION, initialize_simulation, local_relay, offline_only, post_now,
    report, review_identity, run_once, simulation_store, SimulatedInstagramAdapter,
)


@pytest.fixture(autouse=True)
def no_network():
    with offline_only():
        yield


@pytest.fixture
def root(tmp_path):
    return initialize_simulation(tmp_path / "rehearsal")


def authorize(store, **overrides):
    row = dict(store.connection.execute("SELECT * FROM review_requests ORDER BY review_request_id LIMIT 1").fetchone())
    args = dict(review_id=row["review_request_id"], row_version=row["row_version"],
                identity=review_identity(row), destination=DESTINATION, command_id="explicit-simulated-review")
    args.update(overrides)
    return post_now(store, **args)


@pytest.mark.parametrize("count", [4, 5, 6])
def test_exact_jpeg_authorization_success_duplicate_and_restart(tmp_path, count):
    root = initialize_simulation(tmp_path / "simulation", slide_count=count)
    with simulation_store(root) as store:
        evidence = report(store)
        assert evidence["real_publication"] is False
        assert not evidence["authorizations"] and not evidence["commands"]
        assert evidence["reviews"][0]["actor_id"] is None
        assert run_once(store, root) is None  # preparation is never authorization
        post = authorize(store)
        assert authorize(store, row_version=1) == post
        run_once(store, root)
        evidence = report(store)
        assert evidence["posts"][0]["status"] == "published"
        assert evidence["posts"][0]["external_post_id"].startswith("simulated:")
        assert evidence["attempts"][0]["final_publication_request_sent_at"]
        assert evidence["fake_sends"][0]["submitted_sha256"] == [a["sha256"] for a in evidence["review_assets"]]
        package = json.loads(evidence["packages"][0]["package_json"])
        assert evidence["fake_sends"][0]["caption"] == package["caption"]
        assert evidence["fake_sends"][0]["alt_text"] == package["alt_text"]
        assert len(evidence["review_assets"]) == count
        assert len(evidence["resources"]) == 2 * count + 1
    with simulation_store(root) as reopened:
        assert run_once(reopened, root) is None
        assert len(report(reopened)["attempts"]) == 1
        assert len(report(reopened)["fake_sends"]) == 1


@pytest.mark.parametrize("change", ["missing", "tampered"])
@pytest.mark.parametrize("after_approval", [False, True])
def test_changed_jpeg_never_reaches_fake_send(root, change, after_approval):
    with simulation_store(root) as store:
        if after_approval:
            authorize(store)
        path = root / "delivery-jpeg/slide-01.jpg"
        if change == "missing":
            path.unlink()
        else:
            path.write_bytes(b"tampered")
        if after_approval:
            run_once(store, root)
        else:
            with pytest.raises((ValueError, FileNotFoundError)):
                authorize(store)
        assert not report(store)["fake_sends"]
        assert not report(store)["attempts"]


@pytest.mark.parametrize("overrides", [
    {"destination": "instagram:another"}, {"identity": "0" * 64}, {"row_version": 99},
])
def test_wrong_destination_or_stale_review_refused(root, overrides):
    with simulation_store(root) as store:
        with pytest.raises(ValueError):
            authorize(store, **overrides)
        assert not report(store)["authorizations"]


def test_store_rejects_destination_substitution(root):
    with simulation_store(root) as store:
        store.connection.execute("UPDATE review_requests SET destination_key='instagram:other'")
        store.connection.commit()
        with pytest.raises(ValueError, match="destination"):
            store.authorize_post_now(1, row_version=1, command_id="wrong-destination")
        assert not report(store)["posts"]


def test_expired_readiness_and_review_block_authorization(root):
    with simulation_store(root) as store:
        store.connection.execute("UPDATE capability_readiness SET valid_until='2000-01-01T00:00:00'")
        store.connection.commit()
        with pytest.raises(ValueError, match="readiness"):
            authorize(store)
        store.connection.execute("UPDATE review_requests SET expires_at='2000-01-01T00:00:00'")
        store.connection.commit()
        with pytest.raises(ValueError, match="current"):
            authorize(store)


def test_outage_is_prefinal_retryable_and_cleanup_is_independent(root):
    with simulation_store(root) as store:
        authorize(store)
        run_once(store, root, outcome="outage")
        evidence = report(store)
        assert evidence["posts"][0]["status"] == "retry_wait"
        assert evidence["attempts"][0]["final_publication_request_sent_at"] is None
        assert not evidence["fake_sends"]
        store.connection.execute("UPDATE post_records SET next_attempt_at='2000-01-01T00:00:00'")
        store.connection.commit()
    with simulation_store(root) as store:
        run_once(store, root)
        assert report(store)["posts"][0]["status"] == "published"
        assert len(report(store)["fake_sends"]) == 1
        assert len(report(store)["attempts"]) == 2
        cleanup_due(store, root)
        assert all(t["status"] == "succeeded" for t in report(store)["cleanup"])
        assert not list((root / "fake-r2").rglob("*.jpg"))
        assert report(store)["posts"][0]["status"] == "published"


def cleanup_due(store, root):
    # Time travel only in tests; the operator command respects persisted due times.
    store.connection.execute("UPDATE delivery_cleanup_tasks SET next_attempt_at='2000-01-01T00:00:00'")
    store.connection.commit()
    cleanup = R2CleanupWorker(store, relay_factory=lambda config: local_relay(root))
    while cleanup.run_once() is not None:
        pass


@pytest.mark.parametrize("decision,expected", [("published", "published"),
    ("not_published_cancel", "cancelled"), ("leave_unknown", "publication_unknown")])
def test_unknown_survives_restart_cleanup_and_requires_manual_resolution(root, decision, expected):
    with simulation_store(root) as store:
        post = authorize(store)
        run_once(store, root, outcome="unknown")
        assert report(store)["posts"][0]["status"] == "publication_unknown"
    with simulation_store(root) as store:
        assert run_once(store, root) is None
        cleanup_due(store, root)
        assert report(store)["posts"][0]["status"] == "publication_unknown"
        request = store.request_publication_reconciliation(post, command_id="explicit-reconcile")
        PublicationReconciliationWorker(store).run_once()
        evidence = report(store)
        assert evidence["checks"][0]["outcome"] == "provider_unavailable"
        store.resolve_publication_unknown(request, reconciliation_check_id=evidence["checks"][0]["reconciliation_check_id"],
            decision=decision, note="Synthetic operator decision; no real publication evidence.",
            row_version=evidence["reconciliation"][0]["row_version"], command_id="explicit-resolution")
        assert report(store)["posts"][0]["status"] == expected
        assert run_once(store, root) is None
        assert len(report(store)["fake_sends"]) == 1


def test_crash_after_final_marker_recovers_unknown_without_publish(root):
    with simulation_store(root) as store:
        authorize(store)
        record = store.claim("post_records", "post_record_id", "crashing-worker")
        context = store.prepare_post_attempt(record)
        store.mark_attempt_ready(context["post_attempt_id"])
        store.mark_final_publication_request(context)
        store.connection.execute("UPDATE post_records SET lease_expires_at='2000-01-01T00:00:00'")
        store.connection.commit()
    with simulation_store(root) as store:
        assert run_once(store, root) is None
        assert report(store)["posts"][0]["status"] == "publication_unknown"
        assert not report(store)["fake_sends"]


def test_cancellation_during_staging_wins_before_final_marker(root):
    with simulation_store(root) as store:
        post = authorize(store)
        class CancellingAdapter(SimulatedInstagramAdapter):
            def stage(self, context, record):
                staged = super().stage(context, record)
                version = report(store)["posts"][0]["row_version"]
                store.cancel_delivery(post, row_version=version, command_id="explicit-cancel")
                return staged
        CredentialedPostingAgent(store, adapters={"instagram": CancellingAdapter(root)}).run_once()
        assert report(store)["posts"][0]["status"] == "cancelled"
        assert report(store)["attempts"][0]["final_publication_request_sent_at"] is None
        assert not report(store)["fake_sends"]
        cleanup_due(store, root)
        assert not list((root / "fake-r2").rglob("*.jpg"))


def test_simulated_package_cannot_reach_unmarked_adapter(root):
    with simulation_store(root) as store:
        authorize(store)
        class ForbiddenAdapter:
            def stage(self, *args):
                pytest.fail("simulation must not reach a real adapter")
        CredentialedPostingAgent(store, adapters={"instagram": ForbiddenAdapter()}).run_once()
        assert report(store)["posts"][0]["status"] == "failed"
        assert report(store)["attempts"][0]["failure_category"] == "configuration"


def test_preparation_deterministic_and_never_inherits_approval(root):
    source = json.loads((root / "review-png/source.json").read_text())
    before = deepcopy(source)
    candidates = [prepare_bundle(**source, lineage={"source_review_status": "approved"},
                                artifact_root=root, output=root / name) for name in ("candidate-a", "candidate-b")]
    assert source == before
    assert candidates[0]["authorization"] is None
    assert candidates[0]["requires_new_review"] is True
    assert candidates[0]["package"]["caption"] == source["package"]["caption"]
    assert candidates[0]["package"]["alt_text"] == source["package"]["alt_text"]
    assert [a["sha256"] for a in candidates[0]["manifest"]["assets"]] == [a["sha256"] for a in candidates[1]["manifest"]["assets"]]
    for asset in candidates[0]["manifest"]["assets"]:
        with Image.open(asset["path"]) as image:
            assert image.format == "JPEG" and image.size == (1080, 1350)
    with pytest.raises(FileExistsError):
        prepare_bundle(**source, lineage={}, artifact_root=root, output=root / "candidate-a")
    with simulation_store(root) as store:
        assert not report(store)["authorizations"]


@pytest.mark.parametrize("fault", ["order", "mime", "hash", "geometry", "oversize", "missing", "outside", "alpha"])
def test_png_preparation_fails_closed(root, tmp_path, fault):
    source = json.loads((root / "review-png/source.json").read_text())
    asset = source["manifest"]["assets"][0]
    if fault == "order": asset["ordinal"] = 7
    elif fault == "mime": asset["mime"] = "image/jpeg"
    elif fault == "hash": asset["sha256"] = "0" * 64
    elif fault == "geometry": asset["height"] = 1080
    elif fault == "oversize": asset["bytes"] = 8_000_001
    elif fault == "missing": Path(asset["path"]).unlink()
    else:
        path = tmp_path / "outside.png" if fault == "outside" else Path(asset["path"])
        Image.new("RGBA" if fault == "alpha" else "RGB", (1080, 1350)).save(path)
        data = path.read_bytes()
        asset.update(path=str(path), bytes=len(data), sha256=sha256(data).hexdigest())
    with pytest.raises((ValueError, FileNotFoundError)):
        prepare_bundle(**source, lineage={}, artifact_root=root, output=root / "invalid-candidate")
    assert not (root / "invalid-candidate").exists()


def test_approved_png_export_does_not_change_immutable_records_or_authorize_derivative(root):
    source = json.loads((root / "review-png/source.json").read_text())
    with simulation_store(root) as store:
        review = seed_review(store, root, bundle=source)
        store.approve_review(review, row_version=1, command_id="editorial-png-only")
        before = list(store.connection.iterdump())
    with simulation_store(root, read_only=True) as store:
        bundle = prepare_review_bundle(store, review, artifact_root=root, output=root / "exported")
        assert bundle["authorization"] is None
        assert bundle["manifest"]["source"]["review_request_id"] == review
        assert before == list(store.connection.iterdump())
    with simulation_store(root) as store:
        with pytest.raises(ValueError):
            store.authorize_post_now(review, row_version=2, command_id="not-a-jpeg-approval")
        assert not report(store)["authorizations"]


def test_workspace_guard_and_network_guard(root, tmp_path):
    with pytest.raises(FileExistsError):
        initialize_simulation(root)
    with pytest.raises(FileNotFoundError):
        with simulation_store(tmp_path): pass
    with pytest.raises(RuntimeError, match="network access"):
        socket.create_connection(("example.invalid", 443))
    marker = json.loads((root / "simulation.json").read_text())
    marker["database"] = str(tmp_path / "operator.db")
    (root / "simulation.json").write_text(json.dumps(marker))
    with pytest.raises(ValueError, match="isolated"):
        with simulation_store(root): pass


def test_cli_requires_explicit_post_command_and_preserves_restart(tmp_path):
    script = Path(__file__).resolve().parents[1] / "scripts/simulate_delivery.py"
    def cli(*args):
        return json.loads(subprocess.check_output([sys.executable, str(script), *map(str, args)], text=True))
    root = tmp_path / "cli"
    initial = cli("init", "--workspace", root)
    assert initial["reviews"][0]["actor_id"] is None
    assert not cli("run", "--workspace", root)["posts"]
    review = initial["reviews"][0]
    cli("post-now", "--workspace", root, "--review-id", review["review_request_id"],
        "--row-version", review["row_version"], "--review-identity", review["review_identity"],
        "--destination", DESTINATION, "--command-id", "human-command-fixture")
    assert cli("run", "--workspace", root, "--outcome", "unknown")["posts"][0]["status"] == "publication_unknown"
    assert len(cli("run", "--workspace", root)["fake_sends"]) == 1


def test_fake_storage_cannot_escape_workspace(root, tmp_path):
    outside = tmp_path / "operator-artifacts"
    outside.mkdir()
    (root / "fake-r2").symlink_to(outside, target_is_directory=True)
    with pytest.raises(ValueError, match="escapes"):
        local_relay(root)
    assert not list(outside.iterdir())


def test_read_only_report_survives_interrupted_fake_send_evidence(root):
    directory = root / "fake-provider"
    directory.mkdir()
    (directory / "send-1.json").write_text('{"mode":')
    with simulation_store(root, read_only=True) as store:
        before = list(store.connection.iterdump())
        assert report(store)["fake_sends"][0]["outcome"] == "incomplete_evidence"
        assert before == list(store.connection.iterdump())


def test_same_size_tampering_checks_hash(root):
    with simulation_store(root) as store:
        path = root / "delivery-jpeg/slide-01.jpg"
        data = bytearray(path.read_bytes())
        data[-1] ^= 1
        path.write_bytes(data)
        with pytest.raises(ValueError, match="hash"):
            authorize(store)
        assert not report(store)["authorizations"]


def test_lost_receipt_persistence_does_not_authorize_duplicate(root, monkeypatch):
    with simulation_store(root) as store:
        authorize(store)
        def failed_commit(*args):
            raise OSError("simulated receipt persistence failure")
        monkeypatch.setattr(store, "complete_publication", failed_commit)
        run_once(store, root)
        assert report(store)["posts"][0]["status"] == "publication_unknown"
    with simulation_store(root) as store:
        assert run_once(store, root) is None
        assert len(report(store)["fake_sends"]) == 1
