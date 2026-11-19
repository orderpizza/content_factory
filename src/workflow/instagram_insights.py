"""Instagram Login Insights rehearsal. Only in-memory GET replies can enter this boundary."""
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from hashlib import sha256
import json
import re
from time import monotonic
from urllib.parse import urlencode

from common.timestamps import parse_timestamp, serialize_timestamp
from .instagram_http import HOST, HTTPReply, MAX_RESPONSE_BYTES
from .instagram_receipts import media_id
from .measurement import (INSIGHTS_API_VERSION, INSIGHTS_CONTRACT, INSTAGRAM_INSIGHTS, Observation,
                          destination, ingest_offline, publication)
from .offline import require_offline
from .store import digest


BASE = f'https://{HOST}/{INSIGHTS_API_VERSION}'
PAGE_SIZE = 10
MAX_ITEMS = 20
MAX_PAGES = 3
MAX_POSTS = 5
MAX_REQUESTS = 2 + MAX_PAGES + MAX_POSTS
REQUEST_SECONDS = 3
COLLECTION_SECONDS = 12
MEDIA_FIELDS = 'id,owner,media_type,media_product_type'


class CollectionError(ValueError):
    """Fixed category only. Provider messages, URLs and headers are sensitive."""


class FixtureTransport:
    """A finite URL-to-reply cassette. None models a client timeout without waiting."""

    def __init__(self, replies: dict[str, HTTPReply | None]):
        if type(replies) is not dict or len(replies) > MAX_REQUESTS:
            raise ValueError('invalid fixture request count')
        self._replies = replies.copy()

    def get(self, url, *, timeout):
        require_offline()
        if url not in self._replies:
            raise CollectionError('missing_fixture')
        reply = self._replies[url]
        if reply is None or timeout <= 0:
            raise CollectionError('deadline')
        return reply


@dataclass(frozen=True)
class Response:
    data: dict
    body_hash: str
    denied: bool = False


def _unique_fields(pairs):
    result = dict(pairs)
    if len(result) != len(pairs):
        raise ValueError('duplicate response field')
    return result


class _Session:
    def __init__(self, transport):
        if type(transport) is not FixtureTransport:
            raise ValueError('in-memory fixture transport required')
        self.transport = transport
        self.deadline = monotonic() + COLLECTION_SECONDS
        self.requests = 0

    def get(self, path, **params):
        remaining = self.deadline - monotonic()
        if remaining <= 0 or self.requests >= MAX_REQUESTS:
            raise CollectionError('collection_limit')
        self.requests += 1
        url = f'{BASE}/{path}?{urlencode(params)}'
        timeout = min(REQUEST_SECONDS, remaining)
        started = monotonic()
        reply = self.transport.get(url, timeout=timeout)
        finished = monotonic()
        if finished - started >= timeout or finished >= self.deadline:
            raise CollectionError('deadline')
        return _decode(reply, metric_request=path.endswith('/insights'))


def _decode(reply, *, metric_request):
    if (type(reply) is not HTTPReply or type(reply.body) is not bytes
            or len(reply.body) > MAX_RESPONSE_BYTES or type(reply.status) is not int
            or not 100 <= reply.status <= 599 or not isinstance(reply.headers, Mapping)
            or len(reply.headers) > 32):
        raise CollectionError('response_limit')
    headers = {}
    for key, value in reply.headers.items():
        if type(key) is not str or len(key) > 128 or type(value) is not str or len(value) > 4096:
            raise CollectionError('response_limit')
        headers[key.lower()] = value
    if len(headers) != len(reply.headers):
        raise CollectionError('ambiguous_headers')
    if 'location' in headers or 300 <= reply.status < 400:
        raise CollectionError('redirect')
    if reply.status == 429:
        raise CollectionError('rate_limit')
    if reply.status == 401:
        raise CollectionError('credentials')
    if reply.status >= 500:
        raise CollectionError('provider_failure')
    if headers.get('facebook-api-version') != INSIGHTS_API_VERSION:
        raise CollectionError('api_version')
    if (headers.get('content-type', '').split(';')[0] != 'application/json'
            or headers.get('content-encoding', 'identity') != 'identity'):
        raise CollectionError('response_type')
    try:
        data = json.loads(reply.body, object_pairs_hook=_unique_fields)
    except (ValueError, UnicodeError, RecursionError):
        raise CollectionError('malformed_response') from None
    if not isinstance(data, dict):
        raise CollectionError('malformed_response')
    code = data['error'].get('code') if isinstance(data.get('error'), dict) else None
    if code in (4, 17, 613, 80002):
        raise CollectionError('rate_limit')
    if code == 190:
        raise CollectionError('credentials')
    body_hash = sha256(reply.body).hexdigest()
    if reply.status == 403 or code in (10, 200):
        # Only an already identity-bound metric can record this null result.
        if metric_request:
            return Response({}, body_hash, denied=True)
        raise CollectionError('not_authorized')
    if reply.status != 200 or 'error' in data:
        raise CollectionError('provider_error')
    return Response(data, body_hash)


def _owned_albums(session, account, targets):
    """Find selected receipt IDs on the account media edge. Never follow a supplied URL."""
    found, cursors, seen = {}, set(), set()
    params = {'fields': MEDIA_FIELDS, 'limit': PAGE_SIZE}
    for _ in range(MAX_PAGES):
        response = session.get(f'{account}/media', **params)
        rows = response.data.get('data')
        if type(rows) is not list or len(rows) > PAGE_SIZE or len(seen) + len(rows) > MAX_ITEMS:
            raise CollectionError('media_item_limit')
        for row in rows:
            if not isinstance(row, dict):
                raise CollectionError('media_identity')
            identity = media_id(row.get('id'))
            if identity in seen:
                raise CollectionError('duplicate_media')
            seen.add(identity)
            if identity in targets:
                if (row.get('owner') != {'id': account} or row.get('media_type') != 'CAROUSEL_ALBUM'
                        or row.get('media_product_type') != 'FEED'):
                    raise CollectionError('media_identity')
                found[identity] = response.body_hash
        if found.keys() == targets.keys():
            return found
        paging = response.data.get('paging', {})
        if not isinstance(paging, dict):
            raise CollectionError('pagination')
        if 'next' not in paging:
            raise CollectionError('missing_media')
        if not isinstance(paging['next'], str) or not paging['next']:
            raise CollectionError('pagination')
        cursor = paging.get('cursors')
        after = cursor.get('after') if isinstance(cursor, dict) else None
        if not isinstance(after, str) or not re.fullmatch(r'[A-Za-z0-9_+=/-]{1,256}', after) or after in cursors:
            raise CollectionError('pagination')
        cursors.add(after)
        params['after'] = after
    raise CollectionError('page_limit')


def _metric(response, subject, definition):
    name, period = definition.provider_metric, definition.period
    if response.denied:
        return 'not_authorized', None
    rows = response.data.get('data')
    if rows == []:
        return 'unavailable', None
    if type(rows) is not list or len(rows) != 1 or not isinstance(rows[0], dict):
        raise CollectionError('metric_shape')
    row = rows[0]
    if (row.get('name') != name or row.get('period') != period
            or row.get('id') != f'{subject}/insights/{name}/{period}'):
        raise CollectionError('metric_identity')
    value_field = 'total_value' if period == 'day' else 'values'
    if row.keys() - {'id', 'name', 'period', 'title', 'description', value_field}:
        raise CollectionError('metric_shape')
    if period == 'day':
        counter = row.get('total_value')
    else:
        values = row.get('values')
        if values == []:
            return 'unavailable', None
        if type(values) is not list or len(values) != 1:
            raise CollectionError('metric_shape')
        counter = values[0]
    if not isinstance(counter, dict) or set(counter) != {'value'}:
        raise CollectionError('metric_shape')
    value = counter['value']
    if value is None:
        return 'unknown', None
    if type(value) is not int or not 0 <= value <= 2**63 - 1:
        raise CollectionError('metric_value')
    return 'known', value


def collect_offline(store, destination_id, *, transport: FixtureTransport, day: date, observed_at,
                    fetched_at, post_ids=(), supersedes=None):
    """Append one UTC day's account reach and selected parent lifetime save snapshots atomically.

    observed_at is the fixture capture time. fetched_at records availability for as-of reports.
    An explicit correction maps a post ID (or None for the account) to its previous row.
    """
    require_offline()
    session = _Session(transport)
    if (type(day) is not date or type(destination_id) is not int or destination_id <= 0
            or type(post_ids) not in (tuple, list) or len(post_ids) > MAX_POSTS
            or any(type(p) is not int or p <= 0 for p in post_ids) or len(set(post_ids)) != len(post_ids)):
        raise ValueError('invalid collection selection')
    supersedes = {} if supersedes is None else supersedes
    if (type(supersedes) is not dict or not supersedes.keys() <= {None, *post_ids}
            or any(type(v) is not int or v <= 0 for v in supersedes.values())):
        raise ValueError('invalid correction selection')
    start = datetime.combine(day, time(), tzinfo=timezone.utc)
    end = start + timedelta(days=1)
    observed, fetched = map(parse_timestamp, (observed_at, fetched_at))
    if not end <= observed <= fetched or observed - start > timedelta(days=90):
        raise ValueError('invalid account day or collection chronology')
    dest = destination(store, destination_id)
    account = media_id(dest['provider_account_id'])
    targets = {}
    for post_id in post_ids:
        post = publication(store, post_id)
        if (post['social_destination_id'] != destination_id or post['classification'] != 'synthetic_verified'
                or len(post['receipt_resource_ids']) != 1
                or not timedelta(0) < observed - parse_timestamp(post['published_at']) <= timedelta(days=30)):
            raise CollectionError('publication_binding')
        identity = media_id(post['external_post_id'])
        if identity in targets or identity == account:
            raise CollectionError('ambiguous_identity')
        targets[identity] = post
    identity = session.get(account, fields='id')
    if identity.data != {'id': account}:
        raise CollectionError('account_identity')
    owners = _owned_albums(session, account, targets) if targets else {}
    observations = []

    def record(response, subject, metric, window_start, window_end, post=None):
        definition = INSTAGRAM_INSIGHTS[metric]
        status, value = _metric(response, subject, definition)
        post_id = post['post_record_id'] if post else None
        parent = supersedes.get(post_id)
        evidence = digest([INSIGHTS_CONTRACT, destination_id, account, identity.body_hash, subject, owners.get(subject),
                           metric, serialize_timestamp(window_start), serialize_timestamp(window_end),
                           response.body_hash])
        observations.append(Observation(
            source_key='ig-fixture:' + digest([evidence, post_id, serialize_timestamp(observed),
                                              serialize_timestamp(fetched), parent]),
            social_destination_id=destination_id, account_key=dest['account_key'], provider_account_id=account,
            definition_version=INSIGHTS_CONTRACT, metric=metric, unit=definition.unit, scope=definition.scopes[0],
            provider=definition.provider, api_version=definition.api_version, login=definition.login,
            capability=definition.capability, provenance='synthetic', value_status=status, value=value,
            window_start=serialize_timestamp(window_start), window_end=serialize_timestamp(window_end),
            observed_at=serialize_timestamp(observed), fetched_at=serialize_timestamp(fetched),
            source_response_hash=response.body_hash, evidence_ref='ig-fixture:' + evidence,
            post_record_id=post_id, media_id=subject if post else None,
            receipt_resource_id=post['receipt_resource_ids'][0] if post else None, supersedes_id=parent))

    reach_metric = INSTAGRAM_INSIGHTS['reach']
    reach = session.get(f'{account}/insights', metric=reach_metric.provider_metric,
                        period=reach_metric.period, metric_type='total_value',
                        since=int(start.timestamp()), until=int(end.timestamp()) - 1)
    record(reach, account, 'reach', start, end)
    for media, post in targets.items():
        saved = session.get(f'{media}/insights', metric=INSTAGRAM_INSIGHTS['saves'].provider_metric)
        record(saved, media, 'saves', post['published_at'], observed, post)
    return ingest_offline(store, observations)
