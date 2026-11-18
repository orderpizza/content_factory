"""Retain uncertain source dependencies; authorize/delete only exact fake objects."""
from concurrent.futures import ThreadPoolExecutor
from contextvars import copy_context
from datetime import timedelta
import json
from unittest.mock import patch

import pytest

from common.timestamps import parse_timestamp, serialize_timestamp
from instagram_fakes import composition
from test_instagram_posting_integration import source, authorized, run_fake, no_network  # noqa: F401
from workflow.delivery import CredentialedPostingAgent
from workflow.resource_lifecycle import resource_report, release, schedule_safe
from workflow.store import WorkflowStore


def setup(store, root, png, mode='verified'):
    _, post = authorized(store, root, png)
    factory, objects, http = composition(store)
    count = len(json.loads(store.connection.execute('SELECT manifest_json FROM delivery_revisions').fetchone()[0])['assets'])
    if mode in {'child_lost', 'parent_lost'}:
        http.protocol.fail_at = 1 if mode == 'child_lost' else count * 2 + 1
    elif mode == 'unknown':
        http.receipt_response = {}
    elif mode == 'prefinal':
        http.protocol.status = 'ERROR'
    elif mode == 'cancelled':
        def cancel():
            if len(http.protocol.calls) == 2:
                version = store.connection.execute('SELECT row_version FROM post_records').fetchone()[0]
                store.cancel_delivery(post, row_version=version, command_id='cancel-staging')
                http.after = lambda: None
        http.after = cancel
    run_fake(store, root, factory, post)
    attempt = store.connection.execute('SELECT post_attempt_id FROM post_attempts').fetchone()[0]
    http.protocol.fail_at = None
    return post, attempt, factory, objects, http


def approve(store, item, command='release-one', **changes):
    values = dict(identity=item['identity'], fingerprint=item['fingerprint'], expected_state=item['state'], command_id=command, confirm=True)
    values.update(changes)
    return release(store, item['resource_id'], **values)


def investigate(factory, attempt, http, status='FINISHED'):
    http.protocol.status = status
    return factory.investigate_orphans(factory.preflight(), attempt)


def test_verified_receipt_alone_never_releases_then_full_positive_evidence_cleans(source):
    path, root, png = source
    with WorkflowStore(path) as store:
        post, attempt, factory, objects, http = setup(store, root, png)
        before = len(objects.objects)
        assert all(x['eligibility'] == 'retain' for x in resource_report(store, attempt)['objects'])
        assert schedule_safe(store, attempt) == []
        report = investigate(factory, attempt, http)
        assert report['verified_publication'] and not report['unknown_create_outcomes']
        assert len(report['known_children']) == before and len(report['known_parents']) == 1
        assert all(x['eligibility'] == 'automatic' for x in report['objects'])
        tasks = schedule_safe(store, attempt)
        assert len(tasks) == before and len(objects.objects) == before  # Scheduling itself never deletes.
        worker = factory.cleanup_worker()
        assert [worker.run_once() for _ in tasks] == tasks
        assert worker.run_once() is None and not objects.objects
        assert all(x['state'] == 'cleaned' for x in resource_report(store, attempt)['objects'])
        assert schedule_safe(store, attempt) == []
        assert store.connection.execute("SELECT COUNT(*) FROM publication_resources WHERE resource_type='r2_cleanup_audit'").fetchone()[0] >= before * 4
        assert sum(p.endswith('/media_publish') for _, p, _ in http.protocol.calls) == 1


@pytest.mark.parametrize('mode', ['child_lost', 'parent_lost'])
def test_unknown_create_ids_retained_across_restarts_even_when_known_ids_expire(source, mode):
    path, root, png = source
    with WorkflowStore(path) as store:
        post, attempt, factory, objects, http = setup(store, root, png, mode)
        report = investigate(factory, attempt, http, 'EXPIRED')
        assert report['unknown_create_outcomes'] and all(x['eligibility'] == 'retain' for x in report['objects'])
        with pytest.raises(ValueError, match='source dependence'):
            approve(store, report['objects'][0])
        count = len(http.protocol.calls)
    with WorkflowStore(path) as store:
        assert CredentialedPostingAgent(store).run_once() is None
        assert schedule_safe(store, attempt) == []
        assert len(http.protocol.calls) == count and objects.objects


def test_delayed_ingestion_and_explicit_expiry_are_distinct_from_age_or_absence(source):
    path, root, png = source
    with WorkflowStore(path) as store:
        post, attempt, factory, objects, http = setup(store, root, png, 'prefinal')
        for status in ('IN_PROGRESS', 'ERROR', 'UNAVAILABLE'):
            report = investigate(factory, attempt, http, status)
            assert report['objects'][0]['eligibility'] == 'retain'
            assert schedule_safe(store, attempt) == []
        report = investigate(factory, attempt, http, 'EXPIRED')
        assert report['objects'][0]['eligibility'] == 'automatic'
        assert len(schedule_safe(store, attempt)) == 1
        assert factory.cleanup_worker().run_once() is not None and not objects.objects
        assert not any(p.endswith('/media_publish') for _, p, _ in http.protocol.calls)


@pytest.mark.parametrize('mode', ['unknown', 'cancelled'])
def test_unverified_outcome_requires_independent_operator_release_after_ingestion(source, mode):
    path, root, png = source
    with WorkflowStore(path) as store:
        post, attempt, factory, objects, http = setup(store, root, png, mode)
        report = investigate(factory, attempt, http)
        item = report['objects'][0]
        assert item['eligibility'] == 'operator' and schedule_safe(store, attempt) == []
        with pytest.raises(ValueError, match='confirmation'):
            approve(store, item, confirm=False)
        with pytest.raises(ValueError, match='source dependence'):
            approve(store, item, automatic=True)
        task = approve(store, item)
        assert approve(store, item) == task  # Same command is idempotent after the state changed.
        with pytest.raises(ValueError, match='stale'):
            approve(store, item, command='stale-command')
        assert factory.cleanup_worker().run_once() == task
        assert store.connection.execute('SELECT status FROM post_records').fetchone()[0] == ('publication_unknown' if mode == 'unknown' else 'cancelled')


@pytest.mark.parametrize('during_put', [False, True])
def test_crash_with_completed_unexposed_staging_vs_uncertain_upload(source, monkeypatch, during_put):
    class Death(BaseException): pass
    path, root, png = source
    with WorkflowStore(path) as store:
        _, post = authorized(store, root, png)
        factory, objects, http = composition(store)
        if during_put:
            original = objects.put_object
            def die(**values):
                original(**values)
                raise Death()
            monkeypatch.setattr(objects, 'put_object', die)
        else:
            original = store.record_publication_resource
            def die(*args, **values):
                result = original(*args, **values)
                if values.get('resource_type') == 'r2_staged':
                    raise Death()
                return result
            monkeypatch.setattr(store, 'record_publication_resource', die)
        with pytest.raises(Death): run_fake(store, root, factory, post)
        attempt = store.connection.execute('SELECT post_attempt_id FROM post_attempts').fetchone()[0]
        assert resource_report(store, attempt)['objects'][0]['eligibility'] == 'retain'
        with store.transaction():
            store.connection.execute("UPDATE post_records SET lease_expires_at='2000-01-01T00:00:00'")
    with WorkflowStore(path) as store:
        assert CredentialedPostingAgent(store).run_once() is None
        item = resource_report(store, attempt)['objects'][0]
        assert item['eligibility'] == ('retain' if during_put else 'automatic')
        factory, _, _ = composition(store, objects=objects, http=http)
        if during_put:
            assert schedule_safe(store, attempt) == [] and objects.objects
        else:
            from workflow.offline import _OFFLINE
            token = _OFFLINE.set(False)
            try:
                assert resource_report(store, attempt)['objects'][0]['eligibility'] == 'retain'
            finally:
                _OFFLINE.reset(token)
            assert len(schedule_safe(store, attempt)) == 1
            assert factory.cleanup_worker().run_once() is not None and not objects.objects
        assert not http.protocol.calls


def test_two_operator_releases_serialize_and_reject_stale_identity(source):
    path, root, png = source
    with WorkflowStore(path) as store:
        _, attempt, factory, objects, http = setup(store, root, png, 'unknown')
        item = investigate(factory, attempt, http)['objects'][0]
    def submit(command):
        with WorkflowStore(path) as store:
            try: return approve(store, item, command=command)
            except ValueError: return 'stale'
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(copy_context().run, submit, 'release-' + str(i)) for i in range(2)]
        results = [f.result() for f in futures]
    assert results.count('stale') == 1
    with WorkflowStore(path) as store:
        assert store.connection.execute('SELECT COUNT(*) FROM delivery_cleanup_tasks').fetchone()[0] == 1
        assert store.connection.execute("SELECT COUNT(*) FROM human_command_receipts WHERE command_kind='release_r2_resource'").fetchone()[0] == 1
        assert objects.objects


@pytest.mark.parametrize('fault', ['hash', 'destination', 'key', 'state', 'evidence_expiry'])
def test_release_requires_exact_current_object_and_fresh_evidence(source, fault):
    path, root, png = source
    with WorkflowStore(path) as store:
        _, attempt, factory, _, http = setup(store, root, png, 'unknown')
        item = investigate(factory, attempt, http)['objects'][0]
        changes = {}
        if fault == 'state': changes['expected_state'] = 'created'
        elif fault != 'evidence_expiry':
            identity = dict(item['identity'])
            identity[{'hash': 'sha256', 'destination': 'destination_key', 'key': 'object_key'}[fault]] = 'wrong'
            changes['identity'] = identity
        future = serialize_timestamp(parse_timestamp(resource_report(store, attempt)['investigation']['valid_until']) + timedelta(seconds=1))
        from contextlib import nullcontext
        with patch('workflow.resource_lifecycle.now', return_value=future) if fault == 'evidence_expiry' else nullcontext():
            with pytest.raises(ValueError): approve(store, item, **changes)
        assert store.connection.execute('SELECT COUNT(*) FROM delivery_cleanup_tasks').fetchone()[0] == 0


@pytest.mark.parametrize('fault', ['timeout_before', 'timeout_after', 'crash_after', 'claim_loss', 'replaced_object'])
def test_cleanup_failures_and_restarts_never_delete_unrelated_objects(source, monkeypatch, fault):
    class Death(BaseException): pass
    path, root, png = source
    with WorkflowStore(path) as store:
        _, attempt, factory, objects, http = setup(store, root, png, 'unknown')
        item = investigate(factory, attempt, http)['objects'][0]
        task = approve(store, item)
        key = item['identity']['object_key']
        objects.objects['unrelated'] = (b'keep', 'image/jpeg', {})
        original_delete, original_head = objects.delete_object, objects.head_object
        deletes = []
        def delete(**values):
            deletes.append(values)
            if fault == 'timeout_before': raise TimeoutError('private credentials')
            if fault == 'replaced_object':
                _, kind, metadata = objects.objects[key]
                objects.objects[key] = (b'replaced', kind, metadata)
            original_delete(**values)
            if fault == 'timeout_after': raise TimeoutError('private credentials')
            if fault == 'crash_after': raise Death()
        def head(**values):
            result = original_head(**values)
            if fault == 'claim_loss':
                with store.transaction():
                    store.connection.execute("UPDATE delivery_cleanup_tasks SET claim_owner='other',claim_version=claim_version+1")
            return result
        monkeypatch.setattr(objects, 'delete_object', delete)
        monkeypatch.setattr(objects, 'head_object', head)
        if fault == 'crash_after':
            with pytest.raises(Death): factory.cleanup_worker().run_once()
        else:
            assert factory.cleanup_worker().run_once() == task
        assert objects.objects['unrelated'][0] == b'keep'
        assert 'private credentials' not in '\n'.join(store.connection.iterdump())
        if fault == 'claim_loss': assert not deletes
        if fault == 'replaced_object':
            assert objects.objects[key][0] == b'replaced'
            assert store.connection.execute('SELECT status FROM delivery_cleanup_tasks').fetchone()[0] == 'failed'
            return
        with store.transaction():
            store.connection.execute("UPDATE delivery_cleanup_tasks SET lease_expires_at='2000-01-01T00:00:00',next_attempt_at='2000-01-01T00:00:00'")
    monkeypatch.setattr(objects, 'delete_object', original_delete)
    monkeypatch.setattr(objects, 'head_object', original_head)
    with WorkflowStore(path) as store:
        factory, _, _ = composition(store, objects=objects, http=http)
        assert factory.cleanup_worker().run_once() == task
        assert store.connection.execute('SELECT status FROM delivery_cleanup_tasks').fetchone()[0] == 'succeeded'
        assert key not in objects.objects and objects.objects['unrelated'][0] == b'keep'
        assert sum(p.endswith('/media_publish') for _, p, _ in http.protocol.calls) == 1


def test_new_contradictory_investigation_revokes_pending_cleanup(source):
    path, root, png = source
    with WorkflowStore(path) as store:
        _, attempt, factory, objects, http = setup(store, root, png, 'unknown')
        item = investigate(factory, attempt, http)['objects'][0]
        approve(store, item)
        investigate(factory, attempt, http, 'IN_PROGRESS')
        before = dict(objects.objects)
        factory.cleanup_worker().run_once()
        assert objects.objects == before
        assert store.connection.execute('SELECT status FROM delivery_cleanup_tasks').fetchone()[0] == 'failed'


@pytest.mark.parametrize('fault', ['concurrent', 'snapshot_changed', 'elapsed'])
def test_orphan_investigation_lease_and_snapshot_fence_each_get(source, fault):
    path, root, png = source
    with WorkflowStore(path) as store:
        _, attempt, factory, _, http = setup(store, root, png, 'unknown')
        proof = factory.preflight()
        seen = []
        elapsed = [0]
        factory.monotonic = lambda: elapsed[0]
        before = len(http.protocol.calls)
        def interrupt():
            if seen: return
            seen.append(True)
            if fault == 'concurrent':
                with pytest.raises(RuntimeError, match='live lease'):
                    factory.investigate_orphans(proof, attempt)
            elif fault == 'snapshot_changed':
                with store.transaction():
                    store.connection.execute('UPDATE post_records SET claim_version=claim_version+1')
            else:
                elapsed[0] = 181
        http.after = interrupt
        if fault == 'concurrent':
            assert factory.investigate_orphans(proof, attempt)['investigation']
        else:
            with pytest.raises(RuntimeError, match='lease|snapshot'):
                factory.investigate_orphans(proof, attempt)
            assert len(http.protocol.calls) == before + 1
            assert store.connection.execute("SELECT COUNT(*) FROM publication_resources WHERE resource_type='instagram_orphan_check'").fetchone()[0] == 0
        assert store.connection.execute("SELECT COUNT(*) FROM publication_resources WHERE resource_type='instagram_orphan_run'").fetchone()[0] == 1


def test_offline_ingestion_evidence_cannot_release_outside_its_boundary(source):
    from workflow.offline import _OFFLINE
    path, root, png = source
    with WorkflowStore(path) as store:
        _, attempt, factory, _, http = setup(store, root, png)
        assert investigate(factory, attempt, http)['objects'][0]['eligibility'] == 'automatic'
        token = _OFFLINE.set(False)
        try:
            assert resource_report(store, attempt)['objects'][0]['eligibility'] == 'retain'
            assert schedule_safe(store, attempt) == []
        finally:
            _OFFLINE.reset(token)


def test_local_report_and_release_cli_never_perform_provider_operations(source, monkeypatch, capsys):
    from scripts.review_staging import main
    path, root, png = source
    with WorkflowStore(path) as store:
        _, attempt, factory, objects, http = setup(store, root, png, 'unknown')
        item = investigate(factory, attempt, http)['objects'][0]
        before = dict(objects.objects), list(http.protocol.calls)
    monkeypatch.setattr('sys.argv', ['review_staging', '--database', str(path), 'report', '--attempt-id', str(attempt)])
    main()
    output = json.loads(capsys.readouterr().out)
    assert output['provider_operations'] is False and output['result']['objects'][0]['fingerprint'] == item['fingerprint']
    identity_file = root / 'object-identity.json'
    identity_file.write_text(json.dumps(item['identity']))
    monkeypatch.setattr('sys.argv', ['review_staging', '--database', str(path), 'release', '--resource-id', str(item['resource_id']),
        '--identity', str(identity_file), '--fingerprint', item['fingerprint'], '--expected-state', item['state'],
        '--command-id', 'cli-release', '--confirm-source-independent'])
    main()
    assert json.loads(capsys.readouterr().out)['provider_operations'] is False
    assert (objects.objects, http.protocol.calls) == before


def test_concurrent_cleanup_and_investigation_cannot_share_a_live_delete_claim(source, monkeypatch):
    path, root, png = source
    with WorkflowStore(path) as store:
        _, attempt, factory, objects, http = setup(store, root, png, 'unknown')
        proof = factory.preflight()
        item = factory.investigate_orphans(proof, attempt)['objects'][0]
        task = approve(store, item)
        original = objects.head_object
        checked = []
        def head(**values):
            result = original(**values)
            if not checked:
                checked.append(True)
                assert factory.cleanup_worker().run_once() is None
                with pytest.raises(RuntimeError, match='race deletion'):
                    factory.investigate_orphans(proof, attempt)
            return result
        monkeypatch.setattr(objects, 'head_object', head)
        assert factory.cleanup_worker().run_once() == task and checked
        assert store.connection.execute('SELECT attempt_count FROM delivery_cleanup_tasks').fetchone()[0] == 1


def test_crashed_orphan_reader_leaves_durable_lease_then_allows_fresh_investigation(source):
    class Death(BaseException): pass
    path, root, png = source
    with WorkflowStore(path) as store:
        _, attempt, factory, objects, http = setup(store, root, png, 'unknown')
        proof = factory.preflight()
        http.after = lambda: (_ for _ in ()).throw(Death())
        with pytest.raises(Death): factory.investigate_orphans(proof, attempt)
        http.after = lambda: None
        with pytest.raises(RuntimeError, match='live lease'): factory.investigate_orphans(proof, attempt)
        with store.transaction():
            store.connection.execute("UPDATE publication_resources SET safe_metadata_json=json_set(safe_metadata_json,'$.lease_until','2000-01-01T00:00:00') WHERE resource_type='instagram_orphan_run'")
    with WorkflowStore(path) as store:
        factory, _, _ = composition(store, objects=objects, http=http)
        report = investigate(factory, attempt, http)
        assert report['objects'][0]['eligibility'] == 'operator'
        assert store.connection.execute("SELECT COUNT(*) FROM publication_resources WHERE resource_type='instagram_orphan_run'").fetchone()[0] == 2


@pytest.mark.parametrize('change', ['downgrade', 'completion_snapshot'])
def test_registered_cleanup_cannot_downgrade_or_complete_changed_evidence(source, monkeypatch, change):
    path, root, png = source
    with WorkflowStore(path) as store:
        post, attempt, factory, objects, http = setup(store, root, png)
        investigate(factory, attempt, http)
        schedule_safe(store, attempt)
        if change == 'downgrade':
            row = store.connection.execute('SELECT social_destination_id,config_json FROM social_destinations').fetchone()
            config = json.loads(row['config_json'])
            config['adapter_version'] = 'unimplemented'
            import sqlite3
            with pytest.raises(sqlite3.IntegrityError, match='immutable'), store.transaction():
                store.connection.execute('UPDATE social_destinations SET config_json=? WHERE social_destination_id=?',
                                         (json.dumps(config), row['social_destination_id']))
            assert objects.objects
        else:
            complete = store.complete_cleanup
            def change_before_commit(task):
                with store.transaction():
                    store.connection.execute('UPDATE post_records SET row_version=row_version+1 WHERE post_record_id=?', (post,))
                return complete(task)
            monkeypatch.setattr(store, 'complete_cleanup', change_before_commit)
            factory.cleanup_worker().run_once()
        assert not store.connection.execute("SELECT 1 FROM delivery_cleanup_tasks WHERE status='succeeded'").fetchone()
        assert not store.connection.execute("SELECT 1 FROM publication_resources WHERE resource_type='r2_object' AND status='cleaned'").fetchone()
