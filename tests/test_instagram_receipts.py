"""Receipt identity and conservative read-only recovery through the actual factory."""
import json
from unittest.mock import patch

import pytest

from instagram_fakes import composition
from test_instagram_posting_integration import source, authorized, run_fake, no_network  # noqa: F401
from workflow.delivery import CredentialedPostingAgent, PublicationReconciliationWorker
from workflow.instagram_receipts import receipt_summary, VerifiedReceipt
from workflow.store import WorkflowStore


def state(store):
    return store.connection.execute('SELECT status FROM post_records').fetchone()[0]


def reconcile(store, factory, post):
    request = store.request_publication_reconciliation(post, command_id='receipt-investigation')
    worker = factory.reconciliation_worker(factory.preflight())
    check = worker.run_once()
    return request, check


def final_calls(http):
    return sum(path.endswith('/media_publish') for _, path, _ in http.protocol.calls)


def test_verified_receipt_has_account_attempt_and_review_binding(source):
    path, root, png = source
    with WorkflowStore(path) as store:
        review, post = authorized(store, root, png)
        factory, objects, http = composition(store)
        assert run_fake(store, root, factory, post) == post
        assert state(store) == 'published'
        summary = receipt_summary(store, post)
        assert summary['classification'] == 'identity_verified'
        facts, = summary['verification']
        assert facts['provider_account_id'] == '123456' and facts['post_record_id'] == post
        assert facts['media_id'] == summary['accepted_media_ids'][0]
        row = store.connection.execute('SELECT package_hash,manifest_hash,delivery_revision_id FROM review_requests WHERE review_request_id=?', (review,)).fetchone()
        assert all(facts[k] == row[k] for k in row.keys())
        assert facts['provenance'] == 'offline' and 'jpeg_bytes' in facts['unverified_fields']
        assert len(http.receipt_calls) == 1 and final_calls(http) == 1
        assert store.connection.execute('SELECT COUNT(*) FROM delivery_cleanup_tasks').fetchone()[0] == 0
        from scripts.review_delivery import report
        result = report(store, review, root / 'receipt-report.html')
        assert result['publication_evidence'][0]['classification'] == 'identity_verified'
        assert 'Publication receipt and reconciliation' in (root / 'receipt-report.html').read_text()
        assert 'fixture-secret' not in '\n'.join(store.connection.iterdump())


@pytest.mark.parametrize('fault', ['owner', 'id', 'caption', 'type', 'children', 'paging', 'missing', 'unavailable'])
def test_inconsistent_or_unavailable_readback_never_confirms(source, fault):
    path, root, png = source
    with WorkflowStore(path) as store:
        _, post = authorized(store, root, png)
        factory, _, http = composition(store)
        def change_response():
            if not http.media:
                return
            media = next(iter(http.media.values()))
            media['private_debug'] = 'private-provider-secret'
            if fault == 'owner': media['owner']['id'] = '999'
            elif fault == 'id': media['id'] = '999'
            elif fault == 'caption': media['caption'] = 'different content'
            elif fault == 'type': media['media_type'] = 'IMAGE'
            elif fault == 'children': media['children']['data'] = []
            elif fault == 'paging': media['children']['paging'] = {'next': 'https://untrusted.invalid'}
            elif fault == 'missing': http.receipt_response = {}
            elif http.receipt_calls: http.status = 503
        http.after = change_response
        run_fake(store, root, factory, post)
        assert state(store) == 'publication_unknown'
        summary = receipt_summary(store, post)
        assert summary['classification'] == 'accepted_unverified'
        assert len(summary['accepted_media_ids']) == 1 and not summary['verification']
        assert final_calls(http) == 1
        assert CredentialedPostingAgent(store).run_once() is None
        dump = '\n'.join(store.connection.iterdump())
        assert 'private-provider-secret' not in dump and 'fixture-secret' not in dump


def test_delayed_media_is_verified_after_restart_without_activation_or_send(source):
    path, root, png = source
    with WorkflowStore(path) as store:
        _, post = authorized(store, root, png)
        factory, _, http = composition(store)
        http.receipt_response = {}
        run_fake(store, root, factory, post)
        assert state(store) == 'publication_unknown'
    http.receipt_response = None
    before = len(http.protocol.calls)
    with WorkflowStore(path) as store:
        factory, _, _ = composition(store, http=http)
        _, check = reconcile(store, factory, post)
        assert state(store) == 'published'
        assert store.connection.execute('SELECT outcome FROM reconciliation_checks WHERE reconciliation_check_id=?', (check,)).fetchone()[0] == 'confirmed_published'
        assert store.connection.execute('SELECT status FROM post_attempts').fetchone()[0] == 'succeeded'
        assert store.connection.execute("SELECT COUNT(*) FROM human_command_receipts WHERE command_kind='instagram_run_consume'").fetchone()[0] == 1
        assert len(http.protocol.calls) == before and final_calls(http) == 1


@pytest.mark.parametrize('failure', ['publish_response', 'acceptance_persist', 'verified_persist', 'status_persist'])
def test_lost_reply_or_persistence_keeps_ids_and_unknown_without_duplicate(source, failure):
    path, root, png = source
    with WorkflowStore(path) as store:
        _, post = authorized(store, root, png)
        factory, _, http = composition(store)
        if failure == 'publish_response':
            def lose():
                if http.media:
                    raise TimeoutError('private-provider-secret')
            http.after = lose
        if failure == 'verified_persist':
            store.connection.execute("CREATE TEMP TRIGGER receipt_disk_failure BEFORE INSERT ON publication_resources "
                                     "WHEN NEW.resource_type='instagram_verified_receipt' BEGIN SELECT RAISE(ABORT,'disk failure'); END")
        if failure == 'status_persist':
            store.connection.execute("CREATE TEMP TRIGGER status_disk_failure BEFORE UPDATE ON post_records "
                                     "WHEN NEW.status='published' BEGIN SELECT RAISE(ABORT,'disk failure'); END")
        if failure == 'acceptance_persist':
            with patch.object(store, 'record_publish_acceptance', side_effect=OSError('disk failure')):
                run_fake(store, root, factory, post)
        else:
            run_fake(store, root, factory, post)
        assert state(store) == 'publication_unknown'
        summary = receipt_summary(store, post)
        assert bool(summary['accepted_media_ids']) == (failure in {'verified_persist', 'status_persist'})
        assert not summary['verification']
    http.after = lambda: None
    http.protocol.status = 'PUBLISHED'  # Even this is not a media-ID/account mapping.
    with WorkflowStore(path) as store:
        factory, _, _ = composition(store, http=http)
        _, check = reconcile(store, factory, post)
        assert state(store) == ('published' if failure in {'verified_persist', 'status_persist'} else 'publication_unknown')
        outcome = store.connection.execute('SELECT outcome FROM reconciliation_checks WHERE reconciliation_check_id=?', (check,)).fetchone()[0]
        assert outcome == ('confirmed_published' if failure in {'verified_persist', 'status_persist'} else 'ambiguous')
        assert final_calls(http) == 1 and CredentialedPostingAgent(store).run_once() is None
        assert 'private-provider-secret' not in '\n'.join(store.connection.iterdump())


def test_stale_publisher_preserves_response_but_cannot_verify(source):
    path, root, png = source
    with WorkflowStore(path) as store:
        _, post = authorized(store, root, png)
        factory, _, http = composition(store)
        def lose_claim():
            if http.media:
                with store.transaction():
                    store.connection.execute("UPDATE post_records SET claim_owner='replacement',claim_version=claim_version+1,lease_expires_at='2000-01-01T00:00:00'")
        http.after = lose_claim
        run_fake(store, root, factory, post)
        assert not http.receipt_calls and receipt_summary(store, post)['accepted_media_ids']
        http.after = lambda: None
        assert CredentialedPostingAgent(store).run_once() is None
        assert state(store) == 'publication_unknown'
        reconcile(store, factory, post)
        assert state(store) == 'published' and final_calls(http) == 1


@pytest.mark.parametrize('fault', ['claim', 'expiry', 'human'])
def test_stale_reconciliation_cannot_persist_or_confirm(source, fault):
    path, root, png = source
    with WorkflowStore(path) as store:
        _, post = authorized(store, root, png)
        factory, _, http = composition(store)
        http.receipt_response = {}
        run_fake(store, root, factory, post)
        http.receipt_response = None
        store.request_publication_reconciliation(post, command_id='lookup')
        worker = factory.reconciliation_worker(factory.preflight())
        def lose():
            if len(http.receipt_calls) > 1:
                with store.transaction():
                    if fault == 'claim': store.connection.execute("UPDATE reconciliation_requests SET claim_owner='other',claim_version=claim_version+1")
                    elif fault == 'expiry': store.connection.execute("UPDATE reconciliation_requests SET lease_expires_at='2000-01-01T00:00:00'")
                    else: store.connection.execute("UPDATE post_records SET status='cancelled'")
        http.after = lose
        with pytest.raises(RuntimeError, match='stale|resolved'):
            worker.run_once()
        assert store.connection.execute('SELECT COUNT(*) FROM reconciliation_checks').fetchone()[0] == 0
        assert not receipt_summary(store, post)['verification'] and final_calls(http) == 1


@pytest.mark.parametrize('decision', ['published', 'not_published_cancel', 'leave_unknown'])
def test_unavailable_investigation_preserves_human_decisions_without_verified_claim(source, decision):
    path, root, png = source
    with WorkflowStore(path) as store:
        _, post = authorized(store, root, png)
        factory, _, http = composition(store)
        http.receipt_response = {}
        run_fake(store, root, factory, post)
        request = store.request_publication_reconciliation(post, command_id='human-lookup')
        check = PublicationReconciliationWorker(store).run_once()
        row = store.connection.execute('SELECT row_version FROM reconciliation_requests').fetchone()
        store.resolve_publication_unknown(request, reconciliation_check_id=check, decision=decision,
            note='Owner reviewed independent evidence; no retry approved.', row_version=row[0], command_id='resolve')
        assert state(store) == {'published': 'published', 'not_published_cancel': 'cancelled', 'leave_unknown': 'publication_unknown'}[decision]
        summary = receipt_summary(store, post)
        assert summary['classification'] == 'accepted_unverified' and not summary['verification']
        assert summary['human_decisions'][0]['decision'] == decision
        assert final_calls(http) == 1


def test_unissued_receipt_and_negative_evidence_cannot_authorize_confirmation(source):
    path, root, png = source
    with WorkflowStore(path) as store:
        _, post = authorized(store, root, png)
        factory, _, http = composition(store)
        http.receipt_response = {}
        run_fake(store, root, factory, post)
        store.request_publication_reconciliation(post, command_id='fake-lookup')
        request = store.claim('reconciliation_requests', 'reconciliation_request_id', 'fake-worker')
        for outcome, receipt in [('confirmed_published', None), ('confirmed_published', VerifiedReceipt('{}')),
                                 ('confirmed_not_published', None)]:
            with pytest.raises(ValueError):
                store.record_reconciliation_check(request, outcome=outcome, query_version='forged', evidence={}, receipt=receipt)
        assert state(store) == 'publication_unknown' and final_calls(http) == 1


@pytest.mark.parametrize('fault', ['wrong_owner', 'unavailable', 'deadline', 'conflicting_ids'])
def test_read_only_investigation_fails_closed_and_is_bounded(source, fault):
    path, root, png = source
    with WorkflowStore(path) as store:
        _, post = authorized(store, root, png)
        factory, _, http = composition(store)
        http.receipt_response = {}
        run_fake(store, root, factory, post)
        http.receipt_response = None
        store.request_publication_reconciliation(post, command_id='bounded-lookup')
        worker = factory.reconciliation_worker(factory.preflight())
        if fault == 'wrong_owner': next(iter(http.media.values()))['owner']['id'] = '999'
        elif fault == 'unavailable': http.status = 404
        elif fault == 'conflicting_ids':
            with store.transaction():
                store.connection.execute("INSERT INTO publication_resources(post_attempt_id,resource_type,remote_id,status,safe_metadata_json,created_at,updated_at) "
                                         "SELECT post_attempt_id,resource_type,'999',status,safe_metadata_json,created_at,updated_at FROM publication_resources WHERE resource_type='instagram_publish_acceptance'")
        else:
            elapsed = [0]
            factory.monotonic = lambda: elapsed[0]
            http.after = lambda: elapsed.__setitem__(0, 181)
        before = len(http.receipt_calls)
        worker.run_once()
        assert state(store) == 'publication_unknown'
        assert len(http.receipt_calls) - before <= 1 and final_calls(http) == 1
        assert not receipt_summary(store, post)['verification']
        assert store.connection.execute('SELECT status FROM reconciliation_requests').fetchone()[0] == 'needs_human'


def test_copied_or_offline_proof_cannot_confirm_real_publication(source):
    from dataclasses import replace
    from workflow.offline import _OFFLINE
    from workflow.instagram_receipts import persist_verified
    path, root, png = source
    with WorkflowStore(path) as store:
        _, post = authorized(store, root, png)
        factory, _, http = composition(store)
        proofs = []
        def interrupt(context, external_id, *, receipt):
            proofs.append(receipt)
            raise OSError('finalization failed')
        with patch.object(store, 'complete_publication', side_effect=interrupt):
            run_fake(store, root, factory, post)
        proof, = proofs
        with pytest.raises(ValueError, match='issued'):
            persist_verified(store, post, replace(proof))
        token = _OFFLINE.set(False)  # Socket refusal remains installed throughout.
        try:
            with pytest.raises(RuntimeError, match='offline'):
                persist_verified(store, post, proof)
        finally:
            _OFFLINE.reset(token)
        assert state(store) == 'publication_unknown' and not receipt_summary(store, post)['verification']
        assert final_calls(http) == 1
