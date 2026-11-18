"""Durable orphan evidence and exact-object release; never a publishing retry.

Provider source-independence semantics are fixture-only. Missing IDs, absence,
elapsed TTLs and a publication receipt alone cannot prove safe R2 release.
"""
import json
import re
import secrets
from datetime import timedelta

from common.timestamps import parse_timestamp, serialize_timestamp
from . import store as workflow_store
from .store import canonical, digest
from .offline import require_offline, is_offline

CONTRACT = 'instagram_source_independence_candidate_v1'
TERMINAL = {'failed', 'cancelled', 'expired', 'published', 'publication_unknown'}
CORE = {'r2_object', 'r2_staged', 'instagram_create_intent', 'external_media', 'instagram_run',
        'instagram_publish_acceptance', 'instagram_verified_receipt'}


def now(): return workflow_store.now()


def inventory(store, attempt_id):
    row = store.connection.execute(
        'SELECT a.*,p.status post_status,p.claim_version,p.row_version,p.claim_owner,q.package_hash,q.manifest_hash,q.destination_key, '
        'v.delivery_revision_id,d.provider_account_id,d.social_destination_id,d.config_json,r.manifest_json '
        'FROM post_attempts a JOIN post_records p USING(post_record_id) JOIN post_requests q USING(post_request_id) '
        'JOIN review_requests v USING(review_request_id) JOIN delivery_revisions r ON r.delivery_revision_id=v.delivery_revision_id '
        'JOIN content_packages cp ON cp.content_package_id=q.content_package_id JOIN output_requests o ON o.output_request_id=cp.output_request_id '
        'JOIN output_bindings b USING(output_binding_id) JOIN social_destinations d USING(social_destination_id) '
        'WHERE a.post_attempt_id=?', (attempt_id,)).fetchone()
    if row is None or json.loads(row['config_json']).get('adapter_version') != 'instagram_login_v1':
        raise ValueError('registered Instagram attempt required')
    row = dict(row)
    manifest = json.loads(row.pop('manifest_json'))
    row.pop('config_json')
    if digest(manifest) != row['manifest_hash']:
        raise ValueError('immutable manifest binding changed')
    resources = [dict(r) for r in store.connection.execute(
        'SELECT * FROM publication_resources WHERE post_attempt_id=? ORDER BY publication_resource_id', (attempt_id,))]
    for r in resources:
        r['facts'] = json.loads(r.pop('safe_metadata_json'))
    core = [{k: r[k] for k in ('publication_resource_id', 'resource_type', 'remote_id', 'asset_ordinal', 'facts')}
            for r in resources if r['resource_type'] in CORE]
    binding = digest({'attempt': row, 'resources': core})
    children = [r for r in resources if r['resource_type'] == 'external_media' and r['facts'].get('kind') == 'child']
    parents = [r for r in resources if r['resource_type'] == 'external_media' and r['facts'].get('kind') == 'parent']
    intents = [r for r in resources if r['resource_type'] == 'instagram_create_intent']
    unknown = []
    for intent in intents:
        matches = parents if intent['remote_id'] == 'parent' else [r for r in children if r['asset_ordinal'] == intent['asset_ordinal']]
        if len(matches) != 1:
            unknown.append(intent['remote_id'])
        if intent['remote_id'] != 'parent':
            objects = [r for r in resources if r['resource_type'] == 'r2_object' and r['publication_resource_id'] == intent['facts'].get('r2_resource_id')]
            if (len(objects) != 1 or objects[0]['remote_id'] != intent['facts'].get('object_key')
                    or objects[0]['asset_ordinal'] != intent['asset_ordinal']
                    or objects[0]['facts'].get('sha256') != intent['facts'].get('sha256')
                    or any(r['facts'].get('sha256') != intent['facts'].get('sha256') for r in matches)):
                unknown.append('unbound-source:' + intent['remote_id'])
    for child in children:
        if not any(r['remote_id'] == 'child:' + str(child['asset_ordinal']) for r in intents):
            unknown.append('unbound-child:' + child['remote_id'])
    if parents and (not any(r['remote_id'] == 'parent' for r in intents) or len(children) != len(manifest['assets'])):
        unknown.append('incomplete-parent-graph')
    checks = [r for r in resources if r['resource_type'] == 'instagram_orphan_check' and r['facts'].get('binding') == binding]
    check = checks[-1] if checks else None
    return {'attempt': row, 'binding': binding, 'manifest': manifest, 'resources': resources,
            'children': children, 'parents': parents, 'unknown_creates': unknown, 'check': check,
            'verified_publication': any(r['resource_type'] == 'instagram_verified_receipt' for r in resources),
            'final_outcome': row['post_status'], 'terminal': row['post_status'] in TERMINAL and row['status'] not in {'created', 'staging', 'ready_to_publish', 'final_request_sent'}}


def _identity(inv, resource):
    value = resource['facts'].get('identity')
    attempt = inv['attempt']
    if not isinstance(value, dict):
        raise ValueError('legacy object has no exact storage identity; retain for investigation')
    for key in ('post_record_id', 'post_attempt_id', 'attempt_number', 'package_hash', 'manifest_hash', 'destination_key', 'provider_account_id'):
        if value.get(key) != attempt[key]:
            raise ValueError('object identity differs from its authorized attempt')
    assets = [a for a in inv['manifest']['assets'] if a['ordinal'] == resource['asset_ordinal']]
    if (len(assets) != 1 or any(value.get(k) != assets[0][k] for k in ('sha256', 'bytes', 'ordinal'))
            or value.get('object_key') != resource['remote_id'] or value['ordinal'] != resource['asset_ordinal']
            or not re.fullmatch(r'instagram-transient/' + str(value['post_record_id']) + '/' + str(value['attempt_number'])
                                + '/' + str(value['ordinal']) + r'-[a-f0-9]{64}\.jpg', value['object_key'])):
        raise ValueError('object key or immutable bytes differ')
    if set(value) != {'post_record_id', 'post_attempt_id', 'attempt_number', 'package_hash', 'manifest_hash', 'destination_key',
                     'provider_account_id', 'bucket', 'r2_account_id', 'public_domain', 'object_key', 'sha256', 'bytes', 'ordinal'}:
        raise ValueError('object identity fields are not allowlisted')
    return value


def _eligibility(inv, resource, *, fresh=True):
    if not inv['terminal']:
        return 'retain', 'Attempt is active or its stale claim has not been recovered.'
    if resource['facts'].get('provenance') != 'offline' or not is_offline():
        return 'retain', 'No authenticated live staging-lifecycle contract is registered; offline objects remain offline.'
    try:
        identity = _identity(inv, resource)
    except ValueError as error:
        return 'retain', str(error)
    staged = [r for r in inv['resources'] if r['resource_type'] == 'r2_staged' and r['remote_id'] == resource['remote_id']
              and r['facts'].get('identity') == identity and r['facts'].get('completed_io') is True]
    if len(staged) != 1:
        return 'retain', 'Upload/probe completion is uncertain; an in-flight write cannot be ruled out.'
    intents = [r for r in inv['resources'] if r['resource_type'] == 'instagram_create_intent']
    referenced = (any(r['asset_ordinal'] == resource['asset_ordinal'] or r['remote_id'] == 'parent' for r in intents)
                  or any(r['asset_ordinal'] == resource['asset_ordinal'] for r in inv['children']) or bool(inv['parents']))
    if not referenced and not inv['attempt']['final_publication_request_sent_at']:
        return 'automatic', 'Completed staging was never exposed to a child/parent create request.'
    if inv['unknown_creates']:
        return 'retain', 'A create response is missing; every possible source dependency is not identified.'
    check = inv['check']
    if not check or check['facts'].get('provenance') != 'offline' or not is_offline():
        return 'retain', 'No trusted source-independence investigation for this exact attempt.'
    facts = check['facts']
    if fresh and not facts['observed_at'] <= now() < facts['valid_until']:
        return 'retain', 'Investigation evidence is stale; perform another read-only check.'
    known = [*inv['children'], *inv['parents']]
    statuses = facts.get('containers', [])
    if (not known or len(known) != len(statuses) or {r['remote_id'] for r in known} != {s['id'] for s in statuses}
            or len({r['remote_id'] for r in known}) != len(known)):
        return 'retain', 'Known container identities are incomplete or inconsistent.'
    if any(s['status'] not in {'FINISHED', 'PUBLISHED', 'EXPIRED'} for s in statuses):
        return 'retain', 'Ingestion is pending, unavailable or unresolved; keep source JPEGs.'
    if inv['verified_publication'] and all(s['status'] in {'FINISHED', 'PUBLISHED'} for s in statuses):
        return 'automatic', 'Verified publication plus complete positive source-independence evidence (offline contract only).'
    if all(s['status'] == 'EXPIRED' for s in statuses) and not inv['attempt']['final_publication_request_sent_at']:
        return 'automatic', 'Every known container positively expired before any final-send marker (offline contract only).'
    return 'operator', 'All known sources are independent/expired, but publication disposition needs separate owner release approval.'


def resource_report(store, attempt_id, *, fresh=True):
    inv = inventory(store, attempt_id)
    output = []
    for resource in inv['resources']:
        if resource['resource_type'] != 'r2_object':
            continue
        eligibility, reason = _eligibility(inv, resource, fresh=fresh)
        item = {'resource_id': resource['publication_resource_id'], 'state': resource['status'],
                'identity': resource['facts'].get('identity'), 'eligibility': eligibility, 'reason': reason,
                'attempt_binding': inv['binding'], 'investigation_id': inv['check']['publication_resource_id'] if inv['check'] else None}
        task = store.connection.execute('SELECT delivery_cleanup_task_id,status,claim_version,attempt_count,next_attempt_at,failure_reason FROM delivery_cleanup_tasks WHERE publication_resource_id=?',
                                        (resource['publication_resource_id'],)).fetchone()
        item['cleanup'] = dict(task) if task else None
        item['release_history'] = [{k: r['facts'][k] for k in ('command_id', 'actor', 'authorized_at', 'reason')}
            for r in inv['resources'] if r['resource_type'] == 'r2_release' and r['facts'].get('resource_id') == resource['publication_resource_id']]
        item['cleanup_events'] = [r['facts'] for r in inv['resources'] if r['resource_type'] == 'r2_cleanup_audit'
                                  and r['facts'].get('resource_id') == resource['publication_resource_id']]
        item['fingerprint'] = digest(item)
        output.append(item)
    return {'attempt_id': attempt_id, 'post_status': inv['final_outcome'], 'terminal': inv['terminal'],
            'unknown_create_outcomes': inv['unknown_creates'],
            'known_children': [r['remote_id'] for r in inv['children']], 'known_parents': [r['remote_id'] for r in inv['parents']],
            'verified_publication': inv['verified_publication'], 'investigation': inv['check']['facts'] if inv['check'] else None,
            'objects': output, 'note': 'No create/publish retry is authorized. Offline observations never prove live source independence.'}


def release(store, resource_id, *, identity, fingerprint, expected_state, command_id, confirm=False, automatic=False):
    if type(automatic) is not bool or not re.fullmatch(r'[A-Za-z0-9_-]{1,100}', command_id) or (not automatic and confirm is not True):
        raise ValueError('separate exact-object release confirmation required')
    payload = digest(dict(resource_id=resource_id, identity=identity, fingerprint=fingerprint, expected_state=expected_state, automatic=automatic))
    with store.transaction():
        prior = store.connection.execute('SELECT command_kind,payload_hash,result_record_id FROM human_command_receipts WHERE command_id=?', (command_id,)).fetchone()
        if prior:
            if prior['payload_hash'] != payload or prior['command_kind'] != 'release_r2_resource':
                raise ValueError('release command ID reused with different input')
            return prior['result_record_id']
        row = store.connection.execute("SELECT post_attempt_id FROM publication_resources WHERE publication_resource_id=? AND resource_type='r2_object'", (resource_id,)).fetchone()
        if row is None:
            raise ValueError('staged resource is missing')
        report = resource_report(store, row[0])
        item = next(x for x in report['objects'] if x['resource_id'] == resource_id)
        if item['identity'] != identity or item['fingerprint'] != fingerprint or item['state'] != expected_state:
            raise ValueError('stale release identity/state; inspect a fresh resource report')
        if item['eligibility'] == 'retain' or automatic and item['eligibility'] != 'automatic':
            raise ValueError('source dependence has not been safely resolved')
        task = store.connection.execute('SELECT * FROM delivery_cleanup_tasks WHERE publication_resource_id=?', (resource_id,)).fetchone()
        if item['state'] == 'cleaned' or task and task['status'] not in {'failed', 'cancelled'}:
            raise ValueError('resource already released or cleanup is active')
        event = {k: v for k, v in item.items() if k not in {'release_history', 'cleanup_events'}}
        event.update(command_id=command_id, actor='safe_release_policy' if automatic else 'local_owner', authorized_at=now())
        store.connection.execute(
            "INSERT INTO publication_resources(post_attempt_id,resource_type,remote_id,status,safe_metadata_json,created_at,updated_at) "
            "VALUES (?,'r2_release',?,'ready',?,?,?)", (row[0], command_id, canonical(event), now(), now()))
        store.connection.execute("UPDATE publication_resources SET status='cleanup_pending',updated_at=? WHERE publication_resource_id=?", (now(), resource_id))
        if task:
            store.connection.execute("UPDATE delivery_cleanup_tasks SET status='pending',attempt_count=0,claim_version=claim_version+1,claim_owner=NULL,lease_expires_at=NULL,next_attempt_at=NULL,completed_at=NULL WHERE delivery_cleanup_task_id=?", (task['delivery_cleanup_task_id'],))
            task_id = task['delivery_cleanup_task_id']
        else:
            task_id = store.connection.execute("INSERT INTO delivery_cleanup_tasks(publication_resource_id,object_key,status,attempt_limit,created_at) VALUES (?,?,'pending',5,?)", (resource_id, identity['object_key'], now())).lastrowid
        store.connection.execute("INSERT INTO human_command_receipts(command_id,command_kind,actor_id,payload_hash,result_record_id,created_at) VALUES (?,'release_r2_resource',?,?,?,?)",
                                 (command_id, event['actor'], payload, task_id, now()))
        return task_id


def schedule_safe(store, attempt_id):
    result = []
    for item in resource_report(store, attempt_id)['objects']:
        if item['eligibility'] == 'automatic' and item['state'] not in {'cleaned', 'cleanup_pending'}:
            result.append(release(store, item['resource_id'], identity=item['identity'], fingerprint=item['fingerprint'],
                expected_state=item['state'], command_id='auto-release-' + secrets.token_hex(16), automatic=True))
    return result


def cleanup_guard(store, task, *, event=None):
    """Fence every external cleanup request and its durable completion."""
    with store.transaction():
        return _cleanup_guard_locked(store, task, event=event)


def _cleanup_guard_locked(store, task, *, event=None):
    """Caller owns the SQLite write transaction, including final completion."""
    current = store.connection.execute("SELECT * FROM delivery_cleanup_tasks WHERE delivery_cleanup_task_id=? AND status='claimed' AND claim_owner=? AND claim_version=? AND lease_expires_at>?",
        (task['delivery_cleanup_task_id'], task['claim_owner'], task['claim_version'], now())).fetchone()
    if current is None or current['object_key'] != task['object_key'] or current['publication_resource_id'] != task['publication_resource_id']:
        raise RuntimeError('cleanup claim is stale or identity changed')
    resource = store.connection.execute('SELECT * FROM publication_resources WHERE publication_resource_id=?', (task['publication_resource_id'],)).fetchone()
    inv = inventory(store, resource['post_attempt_id'])
    if any(r['resource_type'] == 'instagram_orphan_run' and r['status'] == 'created'
           and r['facts']['lease_until'] > now() for r in inv['resources']):
        raise ValueError('source investigation is still in progress')
    releases = [r for r in inv['resources'] if r['resource_type'] == 'r2_release' and r['facts'].get('resource_id') == resource['publication_resource_id']]
    if not releases:
        raise ValueError('exact-object release authorization is missing')
    grant = releases[-1]['facts']
    item = next(x for x in resource_report(store, resource['post_attempt_id'], fresh=False)['objects'] if x['resource_id'] == resource['publication_resource_id'])
    if (item['state'] != 'cleanup_pending' or item['eligibility'] == 'retain' or item['identity'] != grant['identity']
            or item['attempt_binding'] != grant['attempt_binding'] or item['investigation_id'] != grant['investigation_id']
            or item['identity']['object_key'] != task['object_key']):
        raise ValueError('release evidence changed or source dependence is unresolved')
    if event:
        facts = {'task_id': task['delivery_cleanup_task_id'], 'claim_version': task['claim_version'],
                 'resource_id': item['resource_id'], 'identity_hash': digest(item['identity']), 'event': event, 'at': now()}
        store.connection.execute("INSERT INTO publication_resources(post_attempt_id,resource_type,remote_id,status,safe_metadata_json,created_at,updated_at) VALUES (?,'r2_cleanup_audit',?,'ready',?,?,?)",
            (resource['post_attempt_id'], secrets.token_hex(16), canonical(facts), now(), now()))
    return item['identity']


def investigate(composition, proof, attempt_id):
    """Durable leased read-only investigation; missing create IDs stay unknown."""
    from .instagram_http import InstagramHTTPTransport
    require_offline()
    c = composition
    with c.store.transaction():
        inv = inventory(c.store, attempt_id)
        c._check(proof)
        if not inv['terminal'] or inv['attempt']['social_destination_id'] != c.destination_id:
            raise ValueError('only this destination\'s terminal/recovered attempt can be investigated')
        if c.store.connection.execute(
                "SELECT 1 FROM delivery_cleanup_tasks t JOIN publication_resources r USING(publication_resource_id) "
                "WHERE r.post_attempt_id=? AND t.status='claimed' AND t.lease_expires_at>?", (attempt_id, now())).fetchone():
            raise RuntimeError('cleanup owns a live lease; investigation cannot race deletion')
        for r in inv['resources']:
            if r['resource_type'] == 'instagram_orphan_run' and r['status'] == 'created' and r['facts']['lease_until'] > now():
                raise RuntimeError('another orphan investigation owns the live lease')
        run = secrets.token_hex(16)
        run_facts = {'binding': inv['binding'], 'lease_until': serialize_timestamp(parse_timestamp(now()) + timedelta(seconds=180))}
        run_id = c.store.connection.execute("INSERT INTO publication_resources(post_attempt_id,resource_type,remote_id,status,safe_metadata_json,created_at,updated_at) VALUES (?,'instagram_orphan_run',?,'created',?,?,?)",
            (attempt_id, run, canonical(run_facts), now(), now())).lastrowid
    started = last = c.monotonic()
    def guard():
        nonlocal last
        current = c.monotonic()
        row = c.store.connection.execute('SELECT status FROM publication_resources WHERE publication_resource_id=?', (run_id,)).fetchone()
        if (row is None or row[0] != 'created' or now() >= run_facts['lease_until'] or current < last or current - started >= 180
                or inventory(c.store, attempt_id)['binding'] != inv['binding']):
            raise RuntimeError('orphan investigation lease or attempt snapshot changed')
        last = current
        c._check(proof)
    containers = []
    try:
        _, config = c._check(proof)
        client = InstagramHTTPTransport(config, c.credentials.resolve(config), verified_version=config.api_version, wire=c._wire)
        known = [*inv['children'], *inv['parents']]
        if len(known) > 7:
            raise ValueError('container investigation bound exceeded')
        for resource in known:
            guard()
            try:
                result = client.request('GET', '/' + resource['remote_id'], {'fields': 'status_code'})
                status = result.get('status_code')
                if status not in {'FINISHED', 'PUBLISHED', 'EXPIRED', 'ERROR', 'IN_PROGRESS'}:
                    status = 'UNAVAILABLE'
            except Exception:
                status = 'UNAVAILABLE'
            guard()
            containers.append({'id': resource['remote_id'], 'kind': resource['facts']['kind'], 'status': status})
        with c.store.transaction():
            guard()
            facts = {'binding': inv['binding'], 'contract': CONTRACT, 'provenance': 'offline', 'containers': containers,
                     'unknown_creates': inv['unknown_creates'], 'observed_at': now(),
                     'valid_until': serialize_timestamp(parse_timestamp(now()) + timedelta(minutes=5))}
            c.store.connection.execute("INSERT INTO publication_resources(post_attempt_id,resource_type,remote_id,status,safe_metadata_json,created_at,updated_at) VALUES (?,'instagram_orphan_check',?,'ready',?,?,?)",
                (attempt_id, run, canonical(facts), now(), now()))
            c.store.connection.execute("UPDATE publication_resources SET status='ready',updated_at=? WHERE publication_resource_id=?", (now(), run_id))
        return resource_report(c.store, attempt_id)
    except Exception:
        with c.store.transaction():
            c.store.connection.execute("UPDATE publication_resources SET status='failed',updated_at=? WHERE publication_resource_id=? AND status='created'", (now(), run_id))
        raise
