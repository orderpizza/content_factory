"""Minutes of processing, simulated by clocks rather than rapid mock responses."""
import json
from collections import defaultdict

import pytest

from common.timestamps import parse_timestamp
from instagram_fakes import FakeClock, FakeHTTP, composition
from test_instagram_posting_integration import source, authorized, no_network  # noqa: F401
from workflow.delivery import CredentialedPostingAgent, DeliveryConfigurationError
from workflow.store import WorkflowStore


class ProcessingHTTP(FakeHTTP):
    def __init__(self, clock, *, processing_seconds=120):
        super().__init__()
        self.clock = clock
        self.processing_seconds = processing_seconds
        self.created = {}
        self.polls = defaultdict(list)
        self.dispatches = []
        self.after_dispatch = lambda: None
        original = self.protocol.request

        def processing(method, path, body):
            started = clock.monotonic()
            response = original(method, path, body)
            if method == 'POST' and path.endswith('/media'):
                self.created[response['id']] = started
            if method == 'GET':
                container = path[1:]
                self.polls[container].append(started)
                response = {'id': path[1:], 'status_code': 'FINISHED' if started - self.created[container] >= self.processing_seconds
                            else 'IN_PROGRESS'}
            return response
        self.protocol.request = processing

    def __call__(self, method, target, headers, body, timeout, limit):
        self.dispatches.append((method, target, self.clock.monotonic()))
        reply = super().__call__(method, target, headers, body, timeout, limit)
        self.clock.advance(3)  # Include finite request/response time in elapsed budgets.
        self.after_dispatch()
        return reply


def setup(store, post, root, monkeypatch, *, processing_seconds=120):
    clock = FakeClock()
    monkeypatch.setattr('workflow.store.now', clock.timestamp)
    monkeypatch.setattr('workflow.instagram_composition.utc_datetime_now', clock.now)
    monkeypatch.setattr('workflow.delivery_revision.now', clock.timestamp)
    http = ProcessingHTTP(clock, processing_seconds=processing_seconds)
    factory, objects, _ = composition(store, http=http, clock=clock.now,
                                      monotonic=clock.monotonic, sleep=clock.sleep)
    proof = factory.preflight()
    activation = factory.activate(proof, post_record_id=post, command_id='slow-run', confirm=True)
    agent = factory.agent(activation, artifact_root=root)
    return clock, http, factory, objects, proof, activation, agent


@pytest.mark.parametrize('processing_seconds', [60, 120, 240])
def test_slow_carousels_continue_with_same_grant_and_renewed_lease(source, monkeypatch, processing_seconds):
    path, root, png = source
    with WorkflowStore(path) as store:
        _, post = authorized(store, root, png)
        clock, http, factory, objects, proof, activation, agent = setup(
            store, post, root, monkeypatch, processing_seconds=processing_seconds)
        assert agent.run_once() == post
        result = store.connection.execute('SELECT * FROM post_records WHERE post_record_id=?', (post,)).fetchone()
        assert result['status'] == 'published'
        assert clock.elapsed > 300 and clock.now() > parse_timestamp(activation.expires_at)
        assert parse_timestamp(result['lease_expires_at']) > parse_timestamp(result['claimed_at'])
        assert (parse_timestamp(result['lease_expires_at']) - parse_timestamp(result['claimed_at'])).total_seconds() > 300
        assert store.connection.execute('SELECT COUNT(*) FROM post_attempts').fetchone()[0] == 1
        assert store.connection.execute("SELECT COUNT(*) FROM human_command_receipts WHERE command_kind='instagram_run_consume'").fetchone()[0] == 1
        grant = json.loads(store.connection.execute(
            "SELECT safe_metadata_json FROM publication_resources WHERE resource_type='instagram_run'").fetchone()[0])
        assert grant['claim_version'] == result['claim_version']
        assert grant['activation_binding'] == activation.binding
        assert clock.now() < parse_timestamp(grant['deadline_at'])
        assert len(http.read_calls) > 3  # Fresh read-only evidence, not prolonged stale evidence.
        for times in http.polls.values():
            assert 2 <= len(times) <= 5
            assert all(b - a >= 60 for a, b in zip(times, times[1:]))
        assert sum(p.endswith('media_publish') for _, p, _ in http.protocol.calls) == 1
        assert store.connection.execute('SELECT COUNT(*) FROM delivery_cleanup_tasks').fetchone()[0] == 0


@pytest.mark.parametrize('fault', ['cancel', 'claim', 'lease', 'closed_thread', 'revoked', 'refresh_failure', 'token', 'bytes'])
def test_interruption_stops_before_next_external_request(source, monkeypatch, fault):
    path, root, png = source
    with WorkflowStore(path) as store:
        _, post = authorized(store, root, png)
        clock, http, factory, objects, proof, activation, agent = setup(store, post, root, monkeypatch)
        stopped_at = []
        def interrupt():
            if stopped_at or clock.elapsed < 150:
                return
            stopped_at.append(len(http.dispatches))
            if fault == 'cancel':
                version = store.connection.execute('SELECT row_version FROM post_records WHERE post_record_id=?', (post,)).fetchone()[0]
                store.cancel_delivery(post, row_version=version, command_id='cancel-slow')
            elif fault == 'claim':
                with store.transaction():
                    store.connection.execute("UPDATE post_records SET claim_owner='other',claim_version=claim_version+1 WHERE post_record_id=?", (post,))
            elif fault == 'lease':
                with store.transaction():
                    store.connection.execute('UPDATE post_records SET lease_expires_at=? WHERE post_record_id=?', (clock.timestamp(), post))
            elif fault == 'closed_thread':
                with store.transaction():
                    store.connection.execute("UPDATE content_threads SET status='cancelled'")
            elif fault == 'revoked':
                store.record_destination_readiness(factory.destination_id, status='blocked', reasons=['owner revoked'], facts={})
            elif fault == 'refresh_failure':
                http.validity['is_valid'] = False
            elif fault == 'token':
                factory.credentials._environment['DELIVERY_TOKEN'] = 'changed-secret'
            else:
                (root / 'delivery/slide-01.jpg').write_bytes(b'changed')
        clock.on_sleep = interrupt
        assert agent.run_once() == post
        assert stopped_at
        if fault != 'refresh_failure':
            assert len(http.dispatches) == stopped_at[0]
        else:
            assert store.connection.execute('SELECT status FROM capability_readiness').fetchone()[0] == 'blocked'
            assert all(method == 'GET' for method, _, _ in http.dispatches[stopped_at[0]:])
        assert not any(p.endswith('media_publish') for _, p, _ in http.protocol.calls)
        # Expired/lost claims are never revived; stale recovery cannot replay a consumed run.
        calls = len(http.dispatches)
        clock.advance(301)
        assert CredentialedPostingAgent(store).run_once() is None
        assert len(http.dispatches) == calls
        assert store.connection.execute('SELECT status FROM post_records WHERE post_record_id=?', (post,)).fetchone()[0] in {'failed', 'cancelled'}


def test_expired_start_window_creates_no_attempt_or_external_effect(source, monkeypatch):
    path, root, png = source
    with WorkflowStore(path) as store:
        _, post = authorized(store, root, png)
        clock, http, factory, objects, proof, activation, agent = setup(store, post, root, monkeypatch)
        before = len(http.dispatches)
        clock.advance(121)
        with pytest.raises(DeliveryConfigurationError, match='authorization-to-start expired'):
            agent.run_once()
        assert len(http.dispatches) == before and not objects.objects
        assert store.connection.execute('SELECT COUNT(*) FROM post_attempts').fetchone()[0] == 0
        assert store.connection.execute("SELECT COUNT(*) FROM human_command_receipts WHERE command_kind='instagram_run_consume'").fetchone()[0] == 0


@pytest.mark.parametrize('after_create', [False, True])
def test_crashed_consumed_run_cannot_restart_even_without_create_intent(source, monkeypatch, after_create):
    class ProcessDeath(BaseException): pass
    path, root, png = source
    with WorkflowStore(path) as store:
        _, post = authorized(store, root, png)
        clock, http, factory, objects, proof, activation, agent = setup(store, post, root, monkeypatch)
        if after_create:
            def die():
                if http.protocol.calls:
                    raise ProcessDeath()
            http.after_dispatch = die
        else:
            objects.put_object = lambda **kwargs: (_ for _ in ()).throw(ProcessDeath())
        with pytest.raises(ProcessDeath): agent.run_once()
        assert store.connection.execute("SELECT COUNT(*) FROM publication_resources WHERE resource_type='instagram_run'").fetchone()[0] == 1
        assert store.connection.execute("SELECT COUNT(*) FROM publication_resources WHERE resource_type='instagram_create_intent'").fetchone()[0] == int(after_create)
        sent = len(http.dispatches)
    clock.advance(301)
    with WorkflowStore(path) as reopened:
        assert CredentialedPostingAgent(reopened).run_once() is None
        assert reopened.connection.execute('SELECT status FROM post_records WHERE post_record_id=?', (post,)).fetchone()[0] == 'failed'
        assert reopened.connection.execute('SELECT COUNT(*) FROM post_attempts').fetchone()[0] == 1
        assert len(http.dispatches) == sent


def test_poll_limit_is_bounded_and_retains_create_intent(source, monkeypatch):
    path, root, png = source
    with WorkflowStore(path) as store:
        _, post = authorized(store, root, png)
        clock, http, factory, objects, proof, activation, agent = setup(
            store, post, root, monkeypatch, processing_seconds=600)
        assert agent.run_once() == post
        attempt = store.connection.execute('SELECT * FROM post_attempts').fetchone()
        assert attempt['failure_category'] == 'container_timeout'
        assert attempt['final_publication_request_sent_at'] is None
        assert len(next(iter(http.polls.values()))) == 5
        assert 240 <= clock.elapsed < 300
        assert sum(method == 'POST' for method, _, _ in http.protocol.calls) == 1
        assert CredentialedPostingAgent(store).run_once() is None


def test_late_create_reply_cannot_resurrect_a_lease(source, monkeypatch):
    path, root, png = source
    with WorkflowStore(path) as store:
        _, post = authorized(store, root, png)
        clock, http, factory, objects, proof, activation, agent = setup(store, post, root, monkeypatch)
        def late():
            if http.protocol.calls:
                clock.advance(301)
                http.after_dispatch = lambda: None
        http.after_dispatch = late
        assert agent.run_once() == post
        assert len(http.protocol.calls) == 1 and http.protocol.calls[0][0] == 'POST'
        lease = store.connection.execute('SELECT lease_expires_at FROM post_records').fetchone()[0]
        assert parse_timestamp(lease) < clock.now()
        assert CredentialedPostingAgent(store).run_once() is None
        assert store.connection.execute('SELECT status FROM post_records').fetchone()[0] == 'failed'
        assert len(http.protocol.calls) == 1


@pytest.mark.parametrize('boundary', ['put_object', 'head_object', 'get_exact_bytes'])
def test_claim_loss_during_r2_stops_before_next_external_request(source, monkeypatch, boundary):
    path, root, png = source
    with WorkflowStore(path) as store:
        _, post = authorized(store, root, png)
        clock, http, factory, objects, proof, activation, agent = setup(store, post, root, monkeypatch)
        calls = []
        for name in ('put_object', 'head_object', 'get_exact_bytes'):
            original = getattr(objects, name)
            def request(*args, _name=name, _original=original, **kwargs):
                calls.append(_name)
                result = _original(*args, **kwargs)
                if _name == boundary:
                    with store.transaction():
                        store.connection.execute("UPDATE post_records SET claim_owner='replacement',claim_version=claim_version+1")
                return result
            monkeypatch.setattr(objects, name, request)
        before = len(http.dispatches)
        assert agent.run_once() == post
        expected = ['put_object', 'head_object', 'get_exact_bytes']
        assert calls == expected[:expected.index(boundary) + 1]
        assert len(http.dispatches) == before
        assert not http.protocol.calls


def test_claim_loss_after_final_marker_cannot_send(source, monkeypatch):
    path, root, png = source
    with WorkflowStore(path) as store:
        _, post = authorized(store, root, png)
        clock, http, factory, objects, proof, activation, agent = setup(store, post, root, monkeypatch)
        original = store.mark_final_publication_request
        def lose(context):
            original(context)
            with store.transaction():
                store.connection.execute("UPDATE post_records SET claim_owner='replacement',claim_version=claim_version+1")
        monkeypatch.setattr(store, 'mark_final_publication_request', lose)
        assert agent.run_once() == post
        assert store.connection.execute('SELECT final_publication_request_sent_at FROM post_attempts').fetchone()[0]
        assert not any(p.endswith('media_publish') for _, p, _ in http.protocol.calls)
        clock.advance(301)
        assert CredentialedPostingAgent(store).run_once() is None
        assert store.connection.execute('SELECT status FROM post_records').fetchone()[0] == 'publication_unknown'
        assert not any(p.endswith('media_publish') for _, p, _ in http.protocol.calls)


@pytest.mark.parametrize('fault', ['elapsed_budget', 'wall_deadline', 'clock_rollback', 'refresh_lease_loss'])
def test_elapsed_clock_and_refresh_fences(source, monkeypatch, fault):
    path, root, png = source
    with WorkflowStore(path) as store:
        _, post = authorized(store, root, png)
        clock, http, factory, objects, proof, activation, agent = setup(store, post, root, monkeypatch)
        stopped_at = []
        def interrupt():
            if stopped_at or clock.elapsed < 150:
                return
            stopped_at.append(len(http.dispatches))
            if fault == 'elapsed_budget':
                clock.elapsed += 2701  # Monotonic bound works even if wall time barely advanced.
            elif fault == 'wall_deadline':
                clock.advance(2701)
            elif fault == 'clock_rollback':
                clock.wall_elapsed -= 60
            else:
                def lose_during_refresh():
                    if len(http.read_calls) > 3:
                        with store.transaction():
                            store.connection.execute("UPDATE post_records SET claim_owner='replacement',claim_version=claim_version+1")
                http.after_dispatch = lose_during_refresh
        clock.on_sleep = interrupt
        assert agent.run_once() == post
        assert stopped_at and not any(p.endswith('media_publish') for _, p, _ in http.protocol.calls)
        if fault != 'refresh_lease_loss':
            assert len(http.dispatches) == stopped_at[0]
            assert store.connection.execute('SELECT failure_category FROM post_attempts').fetchone()[0] == 'stage_expired'
            assert store.connection.execute('SELECT status FROM post_records').fetchone()[0] == 'failed'
        else:
            # Only the first refresh GET was admitted, never its next permission/quota request.
            assert len(http.read_calls) == 4


@pytest.mark.parametrize('fault', ['short_wait', 'capacity_changed'])
def test_polling_refuses_early_wakeup_and_exhausted_refresh(source, monkeypatch, fault):
    path, root, png = source
    with WorkflowStore(path) as store:
        _, post = authorized(store, root, png)
        clock, http, factory, objects, _, _, agent = setup(store, post, root, monkeypatch)
        if fault == 'short_wait':
            factory.sleep = lambda seconds: clock.advance(seconds / 2)
        else:
            clock.on_sleep = lambda: http.carousel.update(containers_created=399)
        assert agent.run_once() == post
        assert store.connection.execute('SELECT status FROM post_records').fetchone()[0] == 'failed'
        assert sum(path.endswith('media_publish') for _, path, _ in http.protocol.calls) == 0
        assert len(http.dispatches) < 30 and objects.objects
