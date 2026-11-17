"""Real Phase 3B1 authorization and posting state, with exclusively fake I/O."""
from unittest.mock import patch
import json

import pytest

from test_delivery_revision import make_source, prepared, accept, command
from workflow.delivery_fixtures import production_configuration
from workflow.instagram_composition import registration
from instagram_fakes import composition
from workflow.delivery import CredentialedPostingAgent, PublicationReconciliationWorker
from workflow.offline import offline_only
from workflow.store import WorkflowStore


@pytest.fixture(autouse=True)
def no_network():
    with offline_only():
        yield


@pytest.fixture(params=[4, 5, 6])
def source(tmp_path, request):
    config = production_configuration(max_posts_per_day=20, min_post_interval_minutes=0)
    config['destinations'][0]['config'] = registration(enabled=True, app_id='789')
    return make_source(tmp_path, migrated=request.param == 6, configuration=config, count=request.param,
                       readiness=lambda store: composition(store)[0].preflight())


def authorized(store, root, png):
    count = len(json.loads(store.connection.execute(
        "SELECT manifest_json FROM render_runs JOIN review_requests USING(render_run_id) WHERE review_request_id=?",
        (png,)).fetchone()[0])['assets'])
    review = prepared(store, root, png, image_alt_text=[f'Slide {i}: complete lesson description' for i in range(1, count+1)])
    accept(store, review)
    post = store.authorize_post_now(review, command_id="post-test", **command(store, review))
    return review, post


def run_fake(store, root, factory, post):
    # Real persisted registration, preflight and single-post activation; no config patch.
    proof = factory.preflight()
    activation = factory.activate(proof, post_record_id=post, command_id='run-test', confirm=True)
    return factory.agent(activation, artifact_root=root).run_once()


@pytest.mark.parametrize("failure", [None, "child", "parent", "publish", "persist"])
def test_real_revision_state_machine_and_no_replay(source, failure):
    path, root, png = source
    with WorkflowStore(path) as store:
        review, post = authorized(store, root, png)
        approval = tuple(store.connection.execute(
            "SELECT status,actor_id,package_hash,manifest_hash FROM review_requests WHERE review_request_id=?",
            (review,)).fetchone())
        provider, objects, http = composition(store)
        transport = http.protocol
        if failure:
            count = len(json.loads(store.connection.execute("SELECT manifest_json FROM delivery_revisions").fetchone()[0])["assets"])
            transport.fail_at = {"child": 1, "parent": count * 2 + 1, "publish": count * 2 + 3}.get(failure)
        if failure == "persist":
            with patch.object(store, "complete_publication", side_effect=RuntimeError("disk failure")):
                assert run_fake(store, root, provider, post) == post
        else:
            assert run_fake(store, root, provider, post) == post
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
        if failure is None:
            revision = store.connection.execute('SELECT package_json,manifest_json FROM delivery_revisions').fetchone()
            package, manifest = map(json.loads, revision)
            creates = [body for method, path, body in transport.calls if method == 'POST' and path.endswith('/media')]
            children, parent = creates[:-1], creates[-1]
            assert len(children) == len(manifest['assets'])
            assert [child['alt_text'] for child in children] == package['image_alt_text']
            assert all(child['is_carousel_item'] == 'true' for child in children)
            assert parent['caption'] == package['caption']
            assert parent['children'] == ','.join(str(101 + i) for i in range(len(children)))
            from pathlib import Path
            assert [objects.objects[child['image_url'].split('example.invalid/', 1)[1]][0] for child in children] == [
                Path(asset['path']).read_bytes() for asset in manifest['assets']]
        calls = list(transport.calls)
    with WorkflowStore(path) as store:
        assert CredentialedPostingAgent(store).run_once() is None
        assert transport.calls == calls
        assert sum(p.endswith("media_publish") for _, p, _ in calls) <= 1


def test_create_intent_survives_worker_death_and_blocks_retry(source):
    path, root, png = source
    class ProcessDeath(BaseException):
        pass
    with WorkflowStore(path) as store:
        _, post = authorized(store, root, png)
        provider, _, http = composition(store)
        transport = http.protocol
        def die(method, path, body):
            transport.calls.append((method, path, dict(body)))
            raise ProcessDeath()
        transport.request = die
        with pytest.raises(ProcessDeath):
            run_fake(store, root, provider, post)
        assert store.connection.execute(
            "SELECT COUNT(*) FROM publication_resources WHERE resource_type='instagram_create_intent'"
        ).fetchone()[0] == 1
        with store.transaction():
            store.connection.execute("UPDATE post_records SET lease_expires_at='2000-01-01T00:00:00' WHERE post_record_id=?", (post,))
    with WorkflowStore(path) as store:
        assert CredentialedPostingAgent(store).run_once() is None
        assert store.connection.execute("SELECT status FROM post_records WHERE post_record_id=?", (post,)).fetchone()[0] == "failed"
        assert len(transport.calls) == 1
        assert store.connection.execute("SELECT COUNT(*) FROM delivery_cleanup_tasks").fetchone()[0] == 0


def test_stale_preflight_stops_before_final_marker(source):
    from datetime import timedelta
    from common.timestamps import utc_datetime_now
    path, root, png = source
    with WorkflowStore(path) as store:
        _, post = authorized(store, root, png)
        clock = [utc_datetime_now()]
        provider, objects, http = composition(store, clock=lambda: clock[0])
        proof = provider.preflight()
        activation = provider.activate(proof, post_record_id=post, command_id='run', confirm=True)
        agent = provider.agent(activation, artifact_root=root)
        # Let staging finish but expire the evidence before the final marker.
        http.after = lambda: clock.__setitem__(0, clock[0] + timedelta(minutes=6))
        assert agent.run_once() == post
        attempt = store.connection.execute("SELECT * FROM post_attempts WHERE post_record_id=?", (post,)).fetchone()
        assert attempt['final_publication_request_sent_at'] is None
        assert not any(path.endswith('media_publish') for _, path, _ in http.protocol.calls)


def test_retryable_error_after_intent_cannot_replay(source):
    from workflow.delivery import DeliveryError
    path, root, png = source
    with WorkflowStore(path) as store:
        _, post = authorized(store, root, png)
        provider, _, http = composition(store)
        def interrupted(method, path, body):
            raise DeliveryError('transport', 'unknown create result', True, 'stage')
        http.protocol.request = interrupted
        assert run_fake(store, root, provider, post) == post
        assert store.connection.execute("SELECT status FROM post_records WHERE post_record_id=?", (post,)).fetchone()[0] == 'failed'
    with WorkflowStore(path) as store:
        assert CredentialedPostingAgent(store).run_once() is None


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


def test_configuration_preflight_approval_and_run_are_separate(source):
    from workflow.delivery import DeliveryConfigurationError
    path, root, png = source
    with WorkflowStore(path) as store:
        factory, objects, http = composition(store)
        proof = factory.preflight()
        with pytest.raises(ValueError):
            factory.activate(proof, post_record_id=1, command_id='too-early', confirm=True)
        review, post = authorized(store, root, png)
        with pytest.raises(DeliveryConfigurationError, match='explicit'):
            factory.activate(proof, post_record_id=post, command_id='no-confirm')
        # Configuration, preflight, JPEG approval and Post now still produced no I/O.
        assert not objects.objects and not http.protocol.calls
        activation = factory.activate(proof, post_record_id=post, command_id='run', confirm=True)
        agent = factory.agent(activation, artifact_root=root)
        assert not objects.objects and not http.protocol.calls
        assert store.connection.execute('SELECT COUNT(*) FROM post_attempts').fetchone()[0] == 0
        with pytest.raises(DeliveryConfigurationError, match='already'):
            factory.activate(proof, post_record_id=post, command_id='second-run', confirm=True)
        assert agent.run_once() == post
        sent = list(http.protocol.calls)
        assert agent.run_once() is None
        assert http.protocol.calls == sent
        assert store.connection.execute("SELECT COUNT(*) FROM human_command_receipts WHERE command_kind='instagram_run_activate'").fetchone()[0] == 1
        assert store.connection.execute("SELECT COUNT(*) FROM human_command_receipts WHERE command_kind='instagram_run_consume'").fetchone()[0] == 1


def test_rotation_revokes_activation_and_requires_new_preflight(source):
    from workflow.instagram_composition import EnvironmentCredentials
    from workflow.delivery import DeliveryConfigurationError
    path, root, png = source
    with WorkflowStore(path) as store:
        _, post = authorized(store, root, png)
        environment = {'DELIVERY_TOKEN': 'fixture-secret'}
        factory, objects, http = composition(store, credentials=EnvironmentCredentials(environment))
        proof = factory.preflight()
        activation = factory.activate(proof, post_record_id=post, command_id='run', confirm=True)
        agent = factory.agent(activation, artifact_root=root)
        environment['DELIVERY_TOKEN'] = 'rotated-fixture-secret'
        http.accepted_token = 'rotated-fixture-secret'
        with pytest.raises(DeliveryConfigurationError, match='credential changed'):
            factory.agent(activation, artifact_root=root)
        refreshed = factory.preflight()
        assert refreshed._token_binding != proof._token_binding
        # A refreshed preflight does not silently upgrade an old run authorization.
        with pytest.raises(DeliveryConfigurationError, match="credential changed"):
            agent.run_once()
        assert not objects.objects and not http.protocol.calls
        assert store.connection.execute('SELECT COUNT(*) FROM post_attempts').fetchone()[0] == 0
        dump = '\n'.join(store.connection.iterdump())
        assert 'fixture-secret' not in dump


def test_registered_configuration_rejects_direct_adapter_injection(source):
    path, root, png = source
    class Untrusted:
        def stage(self, *args): pytest.fail('untrusted adapter was invoked')
    with WorkflowStore(path) as store:
        _, post = authorized(store, root, png)
        assert CredentialedPostingAgent(store, adapters={'instagram': Untrusted()}).run_once() == post
        assert store.connection.execute('SELECT failure_category FROM post_attempts').fetchone()[0] == 'configuration'
        assert store.connection.execute('SELECT COUNT(*) FROM publication_resources').fetchone()[0] == 0


def test_activation_expiry_and_scope_are_checked_before_staging(source):
    from datetime import timedelta
    from common.timestamps import utc_datetime_now
    from workflow.delivery import DeliveryConfigurationError
    path, root, png = source
    with WorkflowStore(path) as store:
        _, post = authorized(store, root, png)
        clock = [utc_datetime_now()]
        factory, objects, http = composition(store, clock=lambda: clock[0])
        proof = factory.preflight()
        with pytest.raises(ValueError):
            factory.activate(proof, post_record_id=post + 1, command_id='wrong-post', confirm=True)
        activation = factory.activate(proof, post_record_id=post, command_id='run', confirm=True)
        agent = factory.agent(activation, artifact_root=root)
        clock[0] += timedelta(minutes=3)
        with pytest.raises(DeliveryConfigurationError, match="authorization-to-start expired"):
            agent.run_once()
        assert not objects.objects and not http.protocol.calls
        assert store.connection.execute('SELECT COUNT(*) FROM post_attempts').fetchone()[0] == 0


def test_quota_reservation_survives_new_preflight_and_restart(source):
    from workflow.delivery import DeliveryConfigurationError
    path, root, png = source
    with WorkflowStore(path) as store:
        _, post = authorized(store, root, png)
        factory, objects, http = composition(store)
        http.quota['data'][0]['config']['quota_total'] = 1
        proof = factory.preflight()
        factory.activate(proof, post_record_id=post, command_id='run', confirm=True)
    with WorkflowStore(path) as store:
        factory, objects, http = composition(store)
        http.quota['data'][0]['config']['quota_total'] = 1
        proof = factory.preflight()
        with pytest.raises(DeliveryConfigurationError, match='quota'):
            factory.activate(proof, post_record_id=post, command_id='restart-run', confirm=True)
        assert not http.protocol.calls and not objects.objects


def test_concurrent_posts_share_one_atomic_quota_reservation(source):
    from concurrent.futures import ThreadPoolExecutor
    from contextvars import copy_context
    from threading import Barrier
    from workflow.delivery import DeliveryConfigurationError
    path, root, png = source
    with WorkflowStore(path, catalog_kind='production') as store:
        _, first = authorized(store, root, png)
        from workflow.delivery_artifacts import read_review_source
        from workflow.delivery_fixtures import seed_review
        package, manifest, _ = read_review_source(store, png)
        second_png = seed_review(store, root, bundle={'package': package, 'manifest': manifest})
        review = prepared(store, root, second_png, output=root / 'second-delivery', command_id='second-prepare',
                          image_alt_text=[f'Description {i}' for i in range(len(manifest['assets']))])
        accept(store, review, command_id='second-approve')
        second = store.authorize_post_now(review, command_id='second-post', **command(store, review))
        factory, _, http = composition(store)
        http.quota['data'][0]['config']['quota_total'] = 1
        proof = factory.preflight()
    barrier = Barrier(2)
    def activate(post):
        with WorkflowStore(path) as store:
            factory, objects, http = composition(store)
            barrier.wait(timeout=5)
            try:
                factory.activate(proof, post_record_id=post, command_id=f'concurrent-{post}', confirm=True)
                return 'reserved'
            except DeliveryConfigurationError as error:
                assert 'quota' in str(error)
                return 'refused'
            finally:
                assert not objects.objects and not http.protocol.calls
    # The outer network-refusal patch stays installed; copy only its context flag.
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(copy_context().run, activate, post) for post in (first, second)]
        assert sorted(f.result(timeout=10) for f in futures) == ['refused', 'reserved']
    with WorkflowStore(path) as store:
        assert store.connection.execute("SELECT COUNT(*) FROM human_command_receipts WHERE command_kind='instagram_run_activate'").fetchone()[0] == 1
        assert store.connection.execute('SELECT COUNT(*) FROM post_attempts').fetchone()[0] == 0


def test_identical_refresh_cannot_revive_old_run_activation(source):
    from workflow.delivery import DeliveryConfigurationError
    path, root, png = source
    with WorkflowStore(path) as store:
        _, post = authorized(store, root, png)
        factory, _, _ = composition(store)
        first = factory.preflight()
        activation = factory.activate(first, post_record_id=post, command_id='run', confirm=True)
        second = factory.preflight()
        assert first.evidence_id != second.evidence_id
        with pytest.raises(DeliveryConfigurationError, match='revoked or replaced'):
            factory.agent(activation, artifact_root=root)


def test_rotation_between_gate_and_transport_does_not_stage(source):
    path, root, png = source
    with WorkflowStore(path) as store:
        _, post = authorized(store, root, png)
        factory, objects, http = composition(store)
        proof = factory.preflight()
        activation = factory.activate(proof, post_record_id=post, command_id='run', confirm=True)
        agent = factory.agent(activation, artifact_root=root)
        class RotatingCredentials:
            calls = 0
            def resolve(self, config):
                from workflow.instagram_readiness import ScopedToken
                self.calls += 1
                return ScopedToken('fixture-secret' if self.calls == 1 else 'changed-secret')
        factory.credentials = RotatingCredentials()
        assert agent.run_once() == post
        assert not objects.objects and not http.protocol.calls
        assert store.connection.execute('SELECT final_publication_request_sent_at FROM post_attempts').fetchone()[0] is None
