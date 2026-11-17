"""Real Phase 3B1 authorization and posting state, with exclusively fake I/O."""
from unittest.mock import patch

import pytest

from test_delivery_revision import source, prepared, accept, command  # noqa: F401
from test_instagram_protocol import FakeObjects, FakeTransport
from workflow.delivery import CredentialedPostingAgent, PublicationReconciliationWorker, R2TransientRelay
from workflow.instagram_protocol import OfflineInstagramProtocol
from workflow.offline import offline_only
from workflow.store import WorkflowStore


@pytest.fixture(autouse=True)
def no_network():
    with offline_only():
        yield


def authorized(store, root, png):
    review = prepared(store, root, png)
    accept(store, review)
    post = store.authorize_post_now(review, command_id="post-test", **command(store, review))
    return review, post


def adapter():
    objects, transport = FakeObjects(), FakeTransport()
    relay = R2TransientRelay({"r2_bucket_name": "test", "r2_account_id": "test",
                              "r2_public_domain": "https://example.invalid"},
                             client=objects, transport=objects)
    return OfflineInstagramProtocol(transport, relay, account_id="123456"), objects, transport


def run_fake(store, root, provider):
    # The persisted production catalog remains closed; replace only this test's
    # returned config so the real agent can exercise the remaining state machine.
    original = store._post_delivery_context
    def fake_config(*args, **kwargs):
        context = original(*args, **kwargs)
        context["destination_config"] = {"adapter_version": "offline-test-only"}
        return context
    with patch.object(store, "_post_delivery_context", side_effect=fake_config):
        return CredentialedPostingAgent(store, artifact_root=root,
                                       adapters={"instagram": provider}).run_once()


@pytest.mark.parametrize("failure", [None, "child", "parent", "publish", "persist"])
def test_real_revision_state_machine_and_no_replay(source, failure):
    path, root, png = source
    with WorkflowStore(path) as store:
        review, post = authorized(store, root, png)
        approval = tuple(store.connection.execute(
            "SELECT status,actor_id,package_hash,manifest_hash FROM review_requests WHERE review_request_id=?",
            (review,)).fetchone())
        provider, objects, transport = adapter()
        if failure:
            transport.fail_at = {"child": 1, "parent": 13, "publish": 15}.get(failure)
        if failure == "persist":
            with patch.object(store, "complete_publication", side_effect=RuntimeError("disk failure")):
                assert run_fake(store, root, provider) == post
        else:
            assert run_fake(store, root, provider) == post
        row = store.connection.execute("SELECT * FROM post_records WHERE post_record_id=?", (post,)).fetchone()
        assert row["status"] == ("published" if failure is None else
                                 "publication_unknown" if failure in {"publish", "persist"} else "failed")
        attempt = store.connection.execute("SELECT * FROM post_attempts WHERE post_record_id=?", (post,)).fetchone()
        assert bool(attempt["final_publication_request_sent_at"]) == (failure in {None, "publish", "persist"})
        assert tuple(store.connection.execute(
            "SELECT status,actor_id,package_hash,manifest_hash FROM review_requests WHERE review_request_id=?",
            (review,)).fetchone()) == approval
        assert store.connection.execute("SELECT COUNT(*) FROM delivery_cleanup_tasks").fetchone()[0] == 0
        if failure in {"publish", "persist"}:
            request_id = store.request_publication_reconciliation(post, command_id="reconcile-test")
            PublicationReconciliationWorker(store).run_once()
            assert store.connection.execute(
                "SELECT status FROM reconciliation_requests WHERE reconciliation_request_id=?", (request_id,)
            ).fetchone()[0] == "needs_human"
            assert store.connection.execute("SELECT status FROM post_records WHERE post_record_id=?", (post,)).fetchone()[0] == "publication_unknown"
        calls = list(transport.calls)
    with WorkflowStore(path) as store:
        assert run_fake(store, root, provider) is None
        assert transport.calls == calls
        assert sum(p.endswith("media_publish") for _, p, _ in calls) <= 1


def test_create_intent_survives_worker_death_and_blocks_retry(source):
    path, root, png = source
    class ProcessDeath(BaseException):
        pass
    with WorkflowStore(path) as store:
        _, post = authorized(store, root, png)
        provider, _, transport = adapter()
        def die(method, path, body):
            transport.calls.append((method, path, dict(body)))
            raise ProcessDeath()
        transport.request = die
        with pytest.raises(ProcessDeath):
            run_fake(store, root, provider)
        assert store.connection.execute(
            "SELECT COUNT(*) FROM publication_resources WHERE resource_type='instagram_create_intent'"
        ).fetchone()[0] == 1
        with store.transaction():
            store.connection.execute("UPDATE post_records SET lease_expires_at='2000-01-01T00:00:00' WHERE post_record_id=?", (post,))
    with WorkflowStore(path) as store:
        assert run_fake(store, root, provider) is None
        assert store.connection.execute("SELECT status FROM post_records WHERE post_record_id=?", (post,)).fetchone()[0] == "failed"
        assert len(transport.calls) == 1
        assert store.connection.execute("SELECT COUNT(*) FROM delivery_cleanup_tasks").fetchone()[0] == 0


def test_stale_fake_readiness_stops_before_final_marker(source):
    from datetime import datetime, timezone
    from workflow.instagram_readiness import (CapabilityObservation, InstagramLoginConfiguration,
                                             OfflineReadinessGate, PERMISSIONS, ScopedToken)
    path, root, png = source
    with WorkflowStore(path) as store:
        _, post = authorized(store, root, png)
        provider, _, transport = adapter()
        config = InstagramLoginConfiguration("123456", "instagram:brand", "DELIVERY_TOKEN", enabled=True)
        observation = CapabilityObservation("123456", "instagram_login", "v26.0", "BUSINESS", PERMISSIONS,
            "2026-11-17T00:00:00", "2026-11-18T00:00:00", "2026-12-17T00:00:00", 0, 20, 86400, True, True)
        token = ScopedToken.resolve(config, {"DELIVERY_TOKEN": "fake"})
        times = iter([datetime(2026, 11, 17, 10, tzinfo=timezone.utc),
                      datetime(2026, 11, 18, 1, tzinfo=timezone.utc)])
        gate = OfflineReadinessGate(provider, config, observation, token, run_approved=True, clock=lambda: next(times))
        assert run_fake(store, root, gate) == post
        attempt = store.connection.execute("SELECT * FROM post_attempts WHERE post_record_id=?", (post,)).fetchone()
        assert attempt["final_publication_request_sent_at"] is None
        assert store.connection.execute("SELECT status FROM post_records WHERE post_record_id=?", (post,)).fetchone()[0] == "failed"
        assert not any(path.endswith("media_publish") for _, path, _ in transport.calls)


def test_retryable_error_after_intent_cannot_replay(source):
    from workflow.delivery import DeliveryError
    path, root, png = source
    class InterruptedAdapter:
        def stage(self, context, record):
            record(resource_type="instagram_create_intent", remote_id="child:1", asset_ordinal=1)
            raise DeliveryError("transport", "unknown create result", True, "stage")
    with WorkflowStore(path) as store:
        _, post = authorized(store, root, png)
        assert run_fake(store, root, InterruptedAdapter()) == post
        assert store.connection.execute("SELECT status FROM post_records WHERE post_record_id=?", (post,)).fetchone()[0] == "failed"
    with WorkflowStore(path) as store:
        assert run_fake(store, root, InterruptedAdapter()) is None


def test_resource_intent_is_fenced_by_lease(source):
    path, root, png = source
    with WorkflowStore(path) as store:
        _, post = authorized(store, root, png)
        claim = store.claim("post_records", "post_record_id", "test")
        context = store.prepare_post_attempt(claim)
        with store.transaction():
            store.connection.execute("UPDATE post_records SET lease_expires_at='2000-01-01T00:00:00' WHERE post_record_id=?", (post,))
        with pytest.raises(RuntimeError, match="stale or cancelled"):
            store.record_publication_resource(context["post_attempt_id"], context=context,
                resource_type="instagram_create_intent", remote_id="child:1")
        assert store.connection.execute("SELECT COUNT(*) FROM publication_resources").fetchone()[0] == 0
