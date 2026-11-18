"""Non-live immutable measurement ingestion. No provider or credential interface."""
from dataclasses import asdict, dataclass, replace
import json
import re

from common.timestamps import serialize_timestamp, utc_now
from .offline import require_offline
from .store import canonical, digest


@dataclass(frozen=True)
class MetricDefinition:
    unit: str
    scopes: tuple[str, ...]
    provider: str
    api_version: str
    login: str
    capability: str


INSIGHTS = {
    name: MetricDefinition('count', scopes, 'synthetic', 'fixture-v1', 'fixture', 'synthetic_insights_v1')
    for name, scopes in {'reach': ('post', 'account'), 'saves': ('post',),
                         'shares': ('post',), 'follows': ('post', 'account')}.items()
}
DEFINITIONS = {
    'synthetic_insights_v1': INSIGHTS,
    'manual_insights_v1': {name: replace(d, provider='manual', api_version='not_applicable',
                                       login='none', capability='manual_insights_v1') for name, d in INSIGHTS.items()},
    'manual_operations_v1': {
        name: MetricDefinition(unit, ('post', 'account'), 'manual', 'not_applicable', 'none', 'manual_operations_v1')
        for name, unit in {'operator_minutes': 'minutes', 'storage_cost': 'micro_usd',
                           'delivery_cost': 'micro_usd'}.items()
    },
}
# Deliberately empty. Fixture files cannot register a live capability/version.
AUTHENTICATED_DEFINITIONS = frozenset()


@dataclass(frozen=True)
class Observation:
    source_key: str
    social_destination_id: int
    account_key: str
    provider_account_id: str
    definition_version: str
    metric: str
    unit: str
    scope: str
    provenance: str
    value_status: str
    value: int | None
    window_start: str
    window_end: str
    observed_at: str
    fetched_at: str
    provider: str
    api_version: str
    login: str
    capability: str
    source_response_hash: str
    evidence_ref: str
    post_record_id: int | None = None
    media_id: str | None = None
    receipt_resource_id: int | None = None
    supersedes_id: int | None = None


def destination(store, destination_id):
    row = store.connection.execute(
        'SELECT social_destination_id,destination_key,account_key,provider_account_id '
        'FROM social_destinations WHERE social_destination_id=?', (destination_id,)).fetchone()
    if row is None:
        raise ValueError('unknown destination configuration')
    return dict(row)


def publication(store, post_id):
    """Conservative identity classification, independent from status='published'."""
    row = store.connection.execute(
        'SELECT p.*,q.publication_identity,q.review_request_id,q.destination_key,b.social_destination_id, '
        'c.content_job_id FROM post_records p JOIN post_requests q USING(post_request_id) '
        'JOIN content_packages k USING(content_package_id) JOIN output_requests o USING(output_request_id) '
        'JOIN canonical_contents c USING(canonical_content_id) JOIN output_bindings b USING(output_binding_id) '
        'WHERE p.post_record_id=?', (post_id,)).fetchone()
    if row is None:
        raise ValueError('post has no canonical destination lineage')
    result = dict(row)
    resources = store.connection.execute(
        "SELECT r.* FROM publication_resources r JOIN post_attempts a USING(post_attempt_id) "
        "WHERE a.post_record_id=? AND r.resource_type IN ('instagram_verified_receipt','instagram_publish_acceptance')",
        (post_id,)).fetchall()
    accepted = {r['remote_id'] for r in resources if r['resource_type'] == 'instagram_publish_acceptance'}
    known = accepted | ({row['external_post_id']} if row['external_post_id'] else set())
    receipts = []
    # Reuse the historical review/account/attempt binding; never refresh readiness.
    try:
        from .instagram_receipts import context, accepted_id
        expected = context(store, post_id)
        accepted_media = accepted_id(store, expected)
        for resource in resources:
            if resource['resource_type'] != 'instagram_verified_receipt':
                continue
            facts = json.loads(resource['safe_metadata_json'])
            known.add(facts.get('media_id'))
            if (resource['remote_id'] == digest(facts) and facts.get('provenance') == 'offline'
                    and facts.get('classification') == 'identity_verified'
                    and all(facts.get(k) == v for k, v in expected.items())
                    and facts.get('media_id') == accepted_media == row['external_post_id']):
                receipts.append(resource['publication_resource_id'])
    except (ValueError, KeyError, TypeError):
        pass
    known.discard(None)
    human = store.connection.execute(
        "SELECT h.human_reconciliation_decision_id FROM human_reconciliation_decisions h "
        "JOIN reconciliation_requests r USING(reconciliation_request_id) "
        "WHERE r.post_record_id=? AND h.decision='published'", (post_id,)).fetchall()
    classification = 'not_published'
    if len(known) > 1:
        classification = 'conflicting_identity'
    elif row['status'] == 'published':
        classification = ('synthetic_verified' if receipts else 'human_declared' if human
                          else 'simulated' if (row['external_post_id'] or '').startswith('simulated:')
                          else 'published_unverified')
    elif row['status'] == 'publication_unknown':
        classification = 'publication_unknown'
    result.update(classification=classification, known_media_ids=sorted(known),
                  receipt_resource_ids=receipts, authenticated=False,
                  human_decision_ids=[r[0] for r in human])
    return result


def _validated(store, observation):
    if not isinstance(observation, Observation):
        raise ValueError('typed observation required')
    data = asdict(observation)
    for field in ('source_key', 'evidence_ref'):
        if not isinstance(data[field], str) or not re.fullmatch(r'[A-Za-z0-9_.:-]{1,160}', data[field]):
            raise ValueError('bounded nonsecret source/evidence identifier required')
    for field in ('social_destination_id', 'post_record_id', 'receipt_resource_id', 'supersedes_id'):
        value = data[field]
        if value is not None and (type(value) is not int or value <= 0):
            raise ValueError('positive integer identity required')
    if not isinstance(data['source_response_hash'], str) or not re.fullmatch('[0-9a-f]{64}', data['source_response_hash']):
        raise ValueError('source response SHA256 required')
    definition = DEFINITIONS.get(data['definition_version'], {}).get(data['metric'])
    if definition is None:
        raise ValueError('unknown versioned metric definition')
    if data['unit'] != definition.unit or data['scope'] not in definition.scopes:
        raise ValueError('metric unit/scope mismatch')
    if any(data[k] != getattr(definition, k) for k in ('provider', 'api_version', 'login', 'capability')):
        raise ValueError('unverified provider/version/login/capability')
    allowed = {'synthetic', 'not_collected'} if data['definition_version'].startswith('synthetic_') else {'human_estimate', 'not_collected'}
    if data['provenance'] not in allowed:
        raise ValueError('offline ingestion cannot authenticate platform observations or relabel fixtures')
    if data['value_status'] not in {'known', 'unknown', 'unavailable', 'not_authorized', 'not_collected'}:
        raise ValueError('unknown value status')
    if data['value_status'] == 'known':
        if type(data['value']) is not int or not 0 <= data['value'] <= 2**63 - 1:
            raise ValueError('known metric requires a nonnegative integer')
    elif data['value'] is not None:
        raise ValueError('missing value must be null')
    if data['provenance'] == 'not_collected' and data['value_status'] != 'not_collected':
        raise ValueError('not_collected must have no measurement')
    for field in ('window_start', 'window_end', 'observed_at', 'fetched_at'):
        data[field] = serialize_timestamp(data[field])
    if not data['window_start'] < data['window_end'] <= data['observed_at'] <= data['fetched_at']:
        raise ValueError('invalid measurement window or observation/fetch chronology')
    dest = destination(store, data['social_destination_id'])
    if any(data[k] != dest[k] for k in ('account_key', 'provider_account_id')):
        raise ValueError('account identity mismatch')
    binding = 'account_only'
    if data['scope'] == 'post':
        if data['post_record_id'] is None:
            raise ValueError('post metric requires a PostRecord')
        post = publication(store, data['post_record_id'])
        if post['social_destination_id'] != dest['social_destination_id']:
            raise ValueError('post destination mismatch')
        if data['media_id'] is not None and (post['classification'] == 'conflicting_identity'
                or data['media_id'] not in post['known_media_ids']):
            raise ValueError('media identity is missing or conflicts with publication evidence')
        if data['receipt_resource_id'] is not None and (
                data['receipt_resource_id'] not in post['receipt_resource_ids'] or data['media_id'] is None):
            raise ValueError('matching verified receipt and media identity required')
        binding = 'synthetic_verified' if data['receipt_resource_id'] is not None else 'unverified'
    elif any(data[k] is not None for k in ('post_record_id', 'media_id', 'receipt_resource_id')):
        raise ValueError('account metric cannot carry post/media identity')
    # Identity/provenance/window form the stream. Missing proof may later be supplied
    # by an explicit correction, but never changes the observation's provenance.
    stream_fields = ('social_destination_id', 'post_record_id', 'definition_version', 'metric', 'unit',
                     'scope', 'provenance', 'window_start', 'window_end')
    stream_hash = digest({k: data[k] for k in stream_fields})
    evidence_fields = ('account_key', 'provider_account_id', 'media_id', 'receipt_resource_id', 'provider',
                       'api_version', 'login', 'capability', 'source_response_hash', 'evidence_ref')
    evidence = {k: data[k] for k in evidence_fields}
    evidence.update(destination_key=dest['destination_key'], publication_binding=binding, authenticated=False)
    return data, stream_hash, evidence


def ingest_offline(store, observations: list[Observation]) -> list[int]:
    """One atomic batch, immutable correction history and replay across restarts."""
    require_offline()
    ids = []
    with store.transaction():
        for observation in observations:
            if not isinstance(observation, Observation):
                raise ValueError('typed observation required')
            data = asdict(observation)
            for field in ('window_start', 'window_end', 'observed_at', 'fetched_at'):
                data[field] = serialize_timestamp(data[field])
            payload_hash = digest(data)
            previous = store.connection.execute(
                'SELECT measurement_observation_id,payload_hash FROM measurement_observations WHERE source_key=?',
                (data['source_key'],)).fetchone()
            if previous:
                if previous['payload_hash'] != payload_hash:
                    raise ValueError('source key already identifies a different observation')
                ids.append(previous[0])
                continue
            # A replay returns its immutable evidence even if publication state
            # has since changed. Only new observations require current binding.
            data, stream, evidence = _validated(store, observation)
            # Equal observation timestamps represent one snapshot, so divergent
            # values must explicitly correct its latest leaf rather than silently win.
            if data['supersedes_id'] is not None:
                parent = store.connection.execute('SELECT * FROM measurement_observations WHERE measurement_observation_id=?',
                                                  (data['supersedes_id'],)).fetchone()
                if (not parent or parent['stream_hash'] != stream or parent['observed_at'] > data['observed_at']
                        or parent['fetched_at'] > data['fetched_at']):
                    raise ValueError('correction must preserve stream and advance observation/fetch time')
            elif store.connection.execute(
                    'SELECT 1 FROM measurement_observations WHERE stream_hash=? AND observed_at=? LIMIT 1',
                    (stream, data['observed_at'])).fetchone():
                raise ValueError('same snapshot requires explicit supersession')
            fields = ('source_key', 'social_destination_id', 'post_record_id', 'definition_version', 'metric', 'unit',
                      'scope', 'provenance', 'value_status', 'value', 'window_start', 'window_end', 'observed_at',
                      'fetched_at', 'supersedes_id')
            columns = (*fields, 'evidence_json', 'stream_hash', 'payload_hash', 'created_at')
            cursor = store.connection.execute(
                f"INSERT INTO measurement_observations({','.join(columns)}) VALUES ({','.join('?' for _ in columns)})",
                (*[data[k] for k in fields], canonical(evidence), stream, payload_hash, utc_now()))
            ids.append(cursor.lastrowid)
    return ids


def latest_observations(store, destination_id, start, end, *, as_of=None):
    """Whole windows only; no sum, interpolation, prorating or insertion-time ordering."""
    rows = store.connection.execute(
        'SELECT * FROM measurement_observations WHERE social_destination_id=? '
        'AND window_start>=? AND window_end<=? AND fetched_at<=? '
        'ORDER BY observed_at DESC,fetched_at DESC,measurement_observation_id DESC',
        (destination_id, start, end, as_of or '9999-12-31T23:59:59')).fetchall()
    superseded = {r['supersedes_id'] for r in rows if r['supersedes_id'] is not None}
    seen, result = set(), []
    for row in rows:
        if row['measurement_observation_id'] in superseded or row['stream_hash'] in seen:
            continue
        seen.add(row['stream_hash'])
        item = dict(row)
        item['evidence'] = json.loads(item.pop('evidence_json'))
        result.append(item)
    return result
