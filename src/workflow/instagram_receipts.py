"""Receipt evidence for the registered Instagram adapter, never a publish/retry API.

The selected-version owner/children readback contract is a fixture hypothesis.
No live receipt contract is registered. Offline proofs cannot confirm real media.
"""
from dataclasses import dataclass
from datetime import timedelta
import json
import re
from weakref import WeakSet

from common.timestamps import parse_timestamp, serialize_timestamp
from .delivery import DeliveryError
from .offline import require_offline
from . import store as workflow_store
from .store import canonical, digest

CONTRACT = 'instagram_receipt_candidate_v1'
VERIFIED_RECEIPT_CONTRACTS = frozenset()
_ISSUED = WeakSet()


def now():
    # Evidence and its owning store share one wall clock, including offline
    # time-travel tests. Do not capture a prior worker's injected clock at import.
    return workflow_store.now()


def media_id(value):
    if not isinstance(value, str) or not re.fullmatch(r'[1-9][0-9]{0,29}', value):
        raise ValueError('invalid published-media identity')
    return value


def registered(store, post_id):
    row = store.connection.execute(
        'SELECT d.config_json FROM post_records p JOIN post_requests q USING(post_request_id) '
        'JOIN content_packages c USING(content_package_id) JOIN output_requests o USING(output_request_id) '
        'JOIN output_bindings b USING(output_binding_id) JOIN social_destinations d USING(social_destination_id) '
        'WHERE p.post_record_id=?', (post_id,)).fetchone()
    return row is not None and json.loads(row[0]).get('adapter_version') == 'instagram_login_v1'


def context(store, post_id, attempt_id=None):
    """Read immutable historical identity; expired approval never authorizes a send.

    Readback needs no JPEG file access or live posting lease. Its own worker claim
    is checked separately; it cannot prepare an attempt or consume an activation.
    """
    rows = store.connection.execute(
        'SELECT a.post_attempt_id,p.post_record_id,q.package_hash,q.manifest_hash,q.destination_key, '
        'v.delivery_revision_id,d.social_destination_id,d.provider_account_id,d.config_json, '
        'r.package_json,r.manifest_json FROM post_attempts a JOIN post_records p USING(post_record_id) '
        'JOIN post_requests q USING(post_request_id) JOIN review_requests v USING(review_request_id) '
        'JOIN delivery_revisions r ON r.delivery_revision_id=v.delivery_revision_id '
        'JOIN content_packages c ON c.content_package_id=q.content_package_id '
        'JOIN output_requests o ON o.output_request_id=c.output_request_id '
        'JOIN output_bindings b USING(output_binding_id) JOIN social_destinations d USING(social_destination_id) '
        'WHERE p.post_record_id=? AND a.final_publication_request_sent_at IS NOT NULL', (post_id,)).fetchall()
    if len(rows) != 1 or (attempt_id is not None and rows[0]['post_attempt_id'] != attempt_id):
        raise ValueError('a unique final publication attempt is required')
    row = dict(rows[0])
    package, manifest, config = (json.loads(row.pop(key)) for key in ('package_json', 'manifest_json', 'config_json'))
    if (digest(package) != row['package_hash'] or digest(manifest) != row['manifest_hash']
            or config.get('adapter_version') != 'instagram_login_v1'):
        raise ValueError('reviewed publication identity changed')
    resources = store.connection.execute(
        "SELECT * FROM publication_resources WHERE post_attempt_id=? AND resource_type='external_media' ORDER BY asset_ordinal",
        (row['post_attempt_id'],)).fetchall()
    parents = [r['remote_id'] for r in resources if json.loads(r['safe_metadata_json']).get('kind') == 'parent']
    children = [r['remote_id'] for r in resources if json.loads(r['safe_metadata_json']).get('kind') == 'child']
    if len(parents) != 1 or len(children) != len(manifest['assets']) or not 4 <= len(children) <= 6:
        raise ValueError('durable carousel identities are incomplete')
    row.update(parent_id=media_id(parents[0]), child_container_ids=[media_id(x) for x in children],
               caption_hash=digest(package['caption']), slide_count=len(children),
               configuration_hash=digest(config), api_version=config['api_version'])
    row['binding'] = digest(row)
    return row


def persist_acceptance(store, claimed, external_id):
    """Retain the returned ID even after lease loss; this never confirms publication."""
    external_id = media_id(external_id)
    with store.transaction():
        expected = context(store, claimed['post_record_id'], claimed['post_attempt_id'])
        grant = store.connection.execute(
            "SELECT safe_metadata_json FROM publication_resources WHERE post_attempt_id=? AND resource_type='instagram_run'",
            (claimed['post_attempt_id'],)).fetchone()
        grant = json.loads(grant[0]) if grant else {}
        if any(grant.get(k) != claimed[k] for k in ('claim_owner', 'claim_version', 'package_hash', 'manifest_hash', 'provider_account_id', 'destination_key')):
            raise ValueError('publish response does not belong to the authorized attempt')
        facts = dict(expected, classification='accepted_unverified', media_id=external_id,
                     observed_at=now(), provenance='offline', contract=CONTRACT)
        require_offline()  # A future authenticated issuer requires a reviewed live contract.
        store.connection.execute(
            "INSERT OR IGNORE INTO publication_resources(post_attempt_id,resource_type,remote_id,status,safe_metadata_json,created_at,updated_at) "
            "VALUES (?,'instagram_publish_acceptance',?,'retained',?,?,?)",
            (claimed['post_attempt_id'], external_id, canonical(facts), now(), now()))


def accepted_id(store, expected):
    rows = store.connection.execute(
        "SELECT remote_id,safe_metadata_json FROM publication_resources WHERE post_attempt_id=? AND resource_type='instagram_publish_acceptance'",
        (expected['post_attempt_id'],)).fetchall()
    if not rows:
        return None
    if len(rows) != 1 or json.loads(rows[0]['safe_metadata_json']).get('binding') != expected['binding']:
        raise ValueError('conflicting publish response identities')
    return media_id(rows[0]['remote_id'])


@dataclass(frozen=True, eq=False)
class VerifiedReceipt:
    evidence_json: str

    def facts(self):
        return json.loads(self.evidence_json)


def verify(transport, expected, external_id, *, clock, before_request):
    """One bounded GET, exact ID/owner and observable metadata, no list inference."""
    require_offline()
    before_request()
    response = transport.request('GET', '/' + media_id(external_id),
                                 {'fields': 'id,owner,media_type,caption,children{id}'})
    before_request()
    try:
        children = response['children']
        ids = [media_id(item['id']) for item in children['data']]
        if (response['id'] != external_id or response['owner']['id'] != expected['provider_account_id']
                or response['media_type'] != 'CAROUSEL_ALBUM' or digest(response['caption']) != expected['caption_hash']
                or children.get('paging') or len(ids) != expected['slide_count'] or len(set(ids)) != len(ids)
                or external_id in ids):
            raise ValueError()
    except (KeyError, TypeError, ValueError):
        raise DeliveryError('receipt_identity', 'published-media identity or reviewed metadata is inconsistent', False, 'instagram') from None
    facts = dict(expected, classification='identity_verified', media_id=external_id, child_media_ids=ids,
                 provenance='offline', contract=CONTRACT, observed_at=serialize_timestamp(clock()),
                 verified_fields=['media_id', 'owner_id', 'media_type', 'caption', 'child_count'],
                 unverified_fields=['jpeg_bytes', 'child_order_to_reviewed_assets', 'alt_text'])
    proof = VerifiedReceipt(canonical(facts))
    _ISSUED.add(proof)
    return proof


def persist_verified(store, post_id, proof, *, external_id=None):
    if type(proof) is not VerifiedReceipt or proof not in _ISSUED:
        raise ValueError('issued account/media verification evidence is required')
    require_offline()
    facts = proof.facts()
    expected = context(store, post_id, facts['post_attempt_id'])
    moment, observed = parse_timestamp(now()), parse_timestamp(facts['observed_at'])
    if (any(facts.get(k) != v for k, v in expected.items()) or accepted_id(store, expected) != facts['media_id']
            or external_id is not None and external_id != facts['media_id']
            or not observed <= moment < observed + timedelta(minutes=5)):
        raise ValueError('receipt is stale or bound to different publication evidence')
    store.connection.execute(
        "INSERT OR IGNORE INTO publication_resources(post_attempt_id,resource_type,remote_id,status,safe_metadata_json,created_at,updated_at) "
        "VALUES (?,'instagram_verified_receipt',?,'published',?,?,?)",
        (expected['post_attempt_id'], digest(facts), canonical(facts), now(), now()))
    return facts


def check_reconciliation_claim(store, request):
    row = store.connection.execute(
        "SELECT 1 FROM reconciliation_requests r JOIN post_records p USING(post_record_id) "
        "WHERE reconciliation_request_id=? AND r.status='claimed' AND r.claim_owner=? AND r.claim_version=? "
        "AND r.lease_expires_at>? AND p.status='publication_unknown' AND r.post_record_id=?",
        (request['reconciliation_request_id'], request['claim_owner'], request['claim_version'], now(), request['post_record_id'])).fetchone()
    if row is None:
        raise RuntimeError('reconciliation claim is stale or outcome was resolved')


def receipt_summary(store, post_id):
    """Safe operator projection; a human decision is never called API verification."""
    post = store.connection.execute(
        'SELECT status,EXISTS(SELECT 1 FROM post_attempts a WHERE a.post_record_id=p.post_record_id '
        'AND final_publication_request_sent_at IS NOT NULL) AS final_marker FROM post_records p WHERE post_record_id=?',
        (post_id,)).fetchone()
    if post is None:
        raise ValueError('publication record is missing')
    rows = store.connection.execute(
        "SELECT r.resource_type,r.remote_id,r.safe_metadata_json FROM publication_resources r "
        "JOIN post_attempts a USING(post_attempt_id) WHERE a.post_record_id=? "
        "AND r.resource_type IN ('instagram_publish_acceptance','instagram_verified_receipt') ORDER BY publication_resource_id",
        (post_id,)).fetchall()
    verified = [json.loads(r['safe_metadata_json']) for r in rows if r['resource_type'] == 'instagram_verified_receipt']
    accepted = [r['remote_id'] for r in rows if r['resource_type'] == 'instagram_publish_acceptance']
    checks = [dict(r) for r in store.connection.execute(
        'SELECT c.* FROM reconciliation_checks c JOIN reconciliation_requests r USING(reconciliation_request_id) '
        'WHERE r.post_record_id=? ORDER BY reconciliation_check_id', (post_id,))]
    decisions = [dict(r) for r in store.connection.execute(
        'SELECT h.* FROM human_reconciliation_decisions h JOIN reconciliation_requests r USING(reconciliation_request_id) '
        'WHERE r.post_record_id=? ORDER BY human_reconciliation_decision_id', (post_id,))]
    return {'classification': 'identity_verified' if verified else 'accepted_unverified' if accepted else
            'outcome_uncertain' if post['final_marker'] else 'not_sent', 'post_status': post['status'],
            'accepted_media_ids': accepted, 'verification': verified, 'checks': checks, 'human_decisions': decisions,
            'interpretation': 'Offline fixture verification is not real Instagram evidence. Accepted IDs alone are unverified. '
                              'Human decisions are recorded separately from provider identity verification; no outcome permits automatic reposting.'}
