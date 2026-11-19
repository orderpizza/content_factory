"""Phase 4B0. Only scripted GETs, local test databases and synthetic media."""
from datetime import date, timedelta
from hashlib import sha256
import json
from unittest.mock import patch
from pathlib import Path

import pytest

from common.timestamps import parse_timestamp
from database.current import initialize_database
from detection.configuration import load_manifest
from detection.store import DetectionStore
from instagram_fakes import composition
from test_delivery_revision import accept, command, prepared
from test_instagram_posting_integration import authorized, run_fake, source
from workflow.delivery_artifacts import read_review_source
from workflow.delivery_fixtures import production_configuration, seed_review
from workflow.instagram_http import HTTPReply
from workflow.instagram_insights import CollectionError, FixtureTransport, collect_offline
from workflow.measurement import ingest_authenticated, publication
from workflow.measurement_report import operator_report
from workflow.offline import offline_only
from workflow.store import WorkflowStore


DAY = date(2026, 11, 1)
CAPTURE = '2026-11-03T00:00:00'
START, END = '2000-01-01', '2099-01-01'
BASE = 'https://graph.instagram.com/v27.0'
ACCOUNT = '123456'
ID_URL = f'{BASE}/{ACCOUNT}?fields=id'
LIST_URL = f'{BASE}/{ACCOUNT}/media?fields=id%2Cowner%2Cmedia_type%2Cmedia_product_type&limit=10'
HEADERS = {'content-type': 'application/json', 'facebook-api-version': 'v27.0'}


@pytest.fixture(autouse=True)
def no_network():
    with offline_only():
        yield


@pytest.fixture
def store(tmp_path):
    path = tmp_path / 'measure.db'
    initialize_database(path)
    with DetectionStore(path) as detection:
        detection.apply_manifest(load_manifest(Path(__file__).resolve().parents[1] / 'config/releases/detection.json'))
    with WorkflowStore(path, catalog_kind='production') as store:
        store.register_production_configuration(production_configuration())
        yield store


def reply(data, status=200, **headers):
    return HTTPReply(status, HEADERS | headers, json.dumps(data).encode())


def metric(subject=ACCOUNT, name='reach', period='day', value=8):
    return {'id': f'{subject}/insights/{name}/{period}', 'name': name, 'period': period,
            **({'total_value': {'value': value}} if period == 'day' else {'values': [{'value': value}]})}


def reach_url(day):
    since = int(parse_timestamp(day.isoformat()).timestamp())
    return f'{BASE}/{ACCOUNT}/insights?metric=reach&period=day&metric_type=total_value&since={since}&until={since+86399}'


def cassette(day=DAY, result=None):
    return {ID_URL: reply({'id': ACCOUNT}),
            reach_url(day): reply({'data': [metric()]}) if result is None else result}


def collect(store, replies, *, day=DAY, observed=CAPTURE, fetched=None, **options):
    return collect_offline(store, 1, day=day, observed_at=observed, fetched_at=fetched or observed,
                           transport=FixtureTransport(replies), **options)


def report(store, as_of=END):
    return operator_report(store, 1, START, END, as_of=as_of)


def album(identity, **extra):
    return {'id': identity, 'owner': {'id': ACCOUNT}, 'media_type': 'CAROUSEL_ALBUM',
            'media_product_type': 'FEED', **extra}


@pytest.mark.parametrize(('result', 'status', 'expected'), [
    (reply({'data': []}), 'unavailable', None),
    (reply({'data': [metric(value=None)]}), 'unknown', None),
    (reply({'data': [metric(value=0)]}), 'known', 0),
    (reply({'error': {'code': 200, 'message': 'PRIVATE'}}, 400), 'not_authorized', None),
    (reply({'error': {'code': 10}}, 403), 'not_authorized', None),
])
def test_metric_status_evidence_and_no_promotion(store, result, status, expected):
    ids = collect(store, cassette(result=result))
    row, = report(store)['insights']
    assert (row['measurement_observation_id'], row['value_status'], row['value']) == (ids[0], status, expected)
    assert (row['metric'], row['unit'], row['scope'], row['provenance']) == ('reach', 'unique_accounts', 'account', 'synthetic')
    assert row['evidence']['source_response_hash'] == sha256(result.body).hexdigest()
    assert row['evidence']['period'] == 'day'
    assert row['evidence']['authenticated'] is False
    assert 'PRIVATE' not in json.dumps(row)
    with pytest.raises(ValueError, match='no authenticated'):
        ingest_authenticated(store, proof={**row['evidence'], 'authenticated': True})
    assert not store.connection.execute(
        "SELECT 1 FROM measurement_observations WHERE provenance='authenticated_platform'").fetchone()


@pytest.mark.parametrize(('result', 'category'), [
    (None, 'deadline'), (reply({}, 429), 'rate_limit'),
    (reply({'error': {'code': 80002}}, 400), 'rate_limit'),
    (reply({'error': {'code': 190}}, 400), 'credentials'), (reply({}, 401), 'credentials'),
    (reply({}, 500), 'provider_failure'), (reply({}, 302), 'redirect'),
    (reply({}, **{'facebook-api-version': 'v26.0'}), 'api_version'),
    (reply({}, **{'content-encoding': 'gzip'}), 'response_type'),
    (HTTPReply(200, HEADERS, b'{' * 65537), 'response_limit'),
    (HTTPReply(200, HEADERS, b'PRIVATE'), 'malformed_response'),
    (HTTPReply(200, HEADERS, b'{"data": [], "data": []}'), 'malformed_response'),
    (reply({'data': [dict(metric(), unit='currency')]}), 'metric_shape'),
    (reply({'error': {'code': 100, 'message': 'PRIVATE'}}, 400), 'provider_error'),
    (reply({'data': [metric('999')]}), 'metric_identity'),
    (reply({'data': [metric(name='impressions')]}), 'metric_identity'),
    (reply({'data': [metric(period='week')]}), 'metric_identity'),
    (reply({'data': [metric(), metric()]}), 'metric_shape'),
    (reply({'data': [dict(metric(), total_value={'value': 5, 'breakdowns': []})]}), 'metric_shape'),
    *[(reply({'data': [metric(value=v)]}), 'metric_value') for v in [-1, False, 2.5, '8', 2**63]],
])
def test_fail_closed_no_retry_or_persistence(store, result, category):
    replies = cassette()
    replies[reach_url(DAY)] = result
    with patch.object(FixtureTransport, 'get', autospec=True, side_effect=FixtureTransport.get) as get:
        with pytest.raises(CollectionError) as caught:
            collect(store, replies)
    assert str(caught.value) == category
    assert get.call_count == 2
    assert report(store)['insights'] == []
    assert report(store)['coverage'][0]['authenticated_status'] == 'not_collected'


def test_history_late_arrival_correction_and_idempotency(store):
    empty = cassette(result=reply({'data': []}))
    first, = collect(store, empty)
    assert collect(store, empty) == [first]
    fixed, = collect(store, cassette(), fetched='2026-11-04', supersedes={None: first})
    assert collect(store, cassette(), fetched='2026-11-04', supersedes={None: first}) == [fixed]
    collect(store, cassette(result=reply({'data': [metric(value=3)]})), observed='2026-11-02', fetched='2026-11-05')
    assert report(store, as_of=CAPTURE)['insights'][0]['value'] is None
    assert report(store)['insights'][0]['value'] == 8
    assert store.connection.execute('SELECT count(*) FROM measurement_observations').fetchone()[0] == 3


def test_identity_bounds_and_deadlines(store):
    with pytest.raises(CollectionError, match='account_identity'):
        collect(store, cassette() | {ID_URL: reply({'id': '999'})})
    with pytest.raises(CollectionError, match='not_authorized'):
        collect(store, cassette() | {ID_URL: reply({}, 403)})
    with pytest.raises(ValueError):
        collect(store, {}, observed='2026-10-31')
    with pytest.raises(ValueError):
        collect(store, {}, observed='2027-03-01')
    with patch('workflow.instagram_insights.monotonic', side_effect=[0, 0, 0, 3]):
        with pytest.raises(CollectionError, match='deadline'):
            collect(store, cassette())
    with patch('workflow.instagram_insights.monotonic', side_effect=[0, 0, 0, 0, 12]):
        with pytest.raises(CollectionError, match='collection_limit'):
            collect(store, cassette())
    with pytest.raises(ValueError, match='fixture transport'):
        collect_offline(store, 1, transport=None, day=DAY, observed_at=CAPTURE, fetched_at=CAPTURE)


def test_receipt_to_report_and_bounded_pages(source):
    path, root, png = source
    with WorkflowStore(path) as store:
        _, post = authorized(store, root, png)
        with pytest.raises(CollectionError, match='publication_binding'):
            collect(store, {}, post_ids=[post])
        factory, _, _ = composition(store)
        run_fake(store, root, factory, post)
        published = publication(store, post)
        media = published['external_post_id']
        observed = parse_timestamp(published['published_at']) + timedelta(days=1)
        day = observed.date() - timedelta(days=1)
        saved = f'{BASE}/{media}/insights?metric=saved'
        def page(items, after):
            return reply({'data': items, 'paging': {'next': 'https://private.invalid/?access_token=PRIVATE',
                                                     'cursors': {'after': after}}})
        replies = cassette(day) | {
            LIST_URL: page([album('900')], 'two'),
            LIST_URL + '&after=two': reply({'data': [album(media)]}),
            saved: reply({'data': [metric(media, 'saved', 'lifetime', 4)]})}
        def run(responses):
            return collect(store, responses, post_ids=[post], day=day, observed=observed)
        for changes, category in [
                ({LIST_URL: reply({'data': [album(media, owner={'id': '999'})]})}, 'media_identity'),
                ({LIST_URL: reply({'data': [album(media, media_type='IMAGE')]})}, 'media_identity'),
                ({LIST_URL: reply({'data': []})}, 'missing_media'),
                ({LIST_URL + '&after=two': page([], 'two')}, 'pagination'),
                ({LIST_URL: page([], 'one'), LIST_URL+'&after=one': page([], 'two'),
                  LIST_URL+'&after=two': page([], 'three')}, 'page_limit'),
                ({LIST_URL: page([album(str(910+i)) for i in range(10)], 'two'),
                  LIST_URL+'&after=two': page([album(str(920+i)) for i in range(10)], 'three'),
                  LIST_URL+'&after=three': reply({'data': [album(media)]})}, 'media_item_limit'),
                ({saved: reply({'data': [metric('999', 'saved', 'lifetime')]})}, 'metric_identity')]:
            with pytest.raises(CollectionError, match=category):
                run(replies | changes)
        assert report(store)['insights'] == []
        before = {table: list(store.connection.execute(f'SELECT * FROM {table}'))
                  for table in ('post_attempts', 'review_requests', 'publication_resources', 'model_invocations')}
        ids = run(replies)
        assert run(replies) == ids
        result = report(store)
        by_metric = {r['metric']: r for r in result['insights']}
        saves = by_metric['saves']
        assert saves['window_start'] == published['published_at']
        assert saves['window_end'] == saves['observed_at']
        assert saves['evidence']['period'] == 'lifetime'
        assert saves['evidence']['receipt_resource_id'] == published['receipt_resource_ids'][0]
        assert all(r['provenance'] == 'synthetic' for r in by_metric.values())
        assert result['real_account_performance_available'] is False
        assert result['funnel']['authenticated_published'] == 0
        assert 'PRIVATE' not in json.dumps(result)
        later = observed + timedelta(days=6)
        collect(store, replies | {saved: reply({'data': [metric(media, 'saved', 'lifetime', 9)]})},
                post_ids=[post], day=day, observed=later)
        snapshots = [r for r in report(store)['insights'] if r['metric'] == 'saves']
        assert [r['value'] for r in snapshots] == [9, 4]
        assert all(r['window_start'] == published['published_at'] for r in snapshots)
        for table in before:
            assert list(store.connection.execute(f'SELECT * FROM {table}')) == before[table]


def test_two_receipt_bound_posts_one_account(source):
    path, root, png = source
    with WorkflowStore(path) as store:
        _, first = authorized(store, root, png)
        factory, _, _ = composition(store)
        run_fake(store, root, factory, first)
        package, manifest, _ = read_review_source(store, png)
        second_png = seed_review(store, root, bundle={'package': package, 'manifest': manifest})
        review = prepared(store, root, second_png, output=root / 'second', command_id='prepare-second',
                          image_alt_text=[f'Description {i}' for i in range(len(manifest['assets']))])
        accept(store, review, command_id='approve-second')
        second = store.authorize_post_now(review, command_id='post-second', **command(store, review))
        grant = factory.activate(factory.preflight(), post_record_id=second, command_id='run-second', confirm=True)
        factory.agent(grant, artifact_root=root).run_once()
        posts = [publication(store, i) for i in (first, second)]
        ids = [p['external_post_id'] for p in posts]
        observed = parse_timestamp(posts[-1]['published_at']) + timedelta(days=1)
        day = observed.date() - timedelta(days=1)
        replies = cassette(day) | {LIST_URL: reply({'data': [album(i) for i in reversed(ids)]})}
        for i, media in enumerate(ids):
            replies[f'{BASE}/{media}/insights?metric=saved'] = reply({'data': [metric(media, 'saved', 'lifetime', i)]})
        assert len(collect(store, replies, post_ids=[first, second], observed=observed, day=day)) == 3
        results = report(store)['insights']
        assert {(r['post_record_id'], r['value']) for r in results if r['scope'] == 'post'} == {(first, 0), (second, 1)}


def test_missing_receipt_and_human_declaration_do_not_bind_media(source):
    from workflow.delivery import PublicationReconciliationWorker
    path, root, png = source
    with WorkflowStore(path) as store:
        _, post = authorized(store, root, png)
        factory, _, http = composition(store)
        http.receipt_response = {}
        run_fake(store, root, factory, post)
        assert publication(store, post)['classification'] == 'publication_unknown'
        with pytest.raises(CollectionError, match='publication_binding'):
            collect(store, {}, post_ids=[post])
        request = store.request_publication_reconciliation(post, command_id='human-lookup')
        check = PublicationReconciliationWorker(store).run_once()
        version = store.connection.execute('SELECT row_version FROM reconciliation_requests').fetchone()[0]
        store.resolve_publication_unknown(request, reconciliation_check_id=check, decision='published',
                                          note='Fixture evidence only', row_version=version, command_id='resolve')
        human = publication(store, post)
        assert human['classification'] == 'human_declared'
        observed = parse_timestamp(human['published_at']) + timedelta(days=1)
        with pytest.raises(CollectionError, match='publication_binding'):
            collect(store, {}, post_ids=[post], day=observed.date() - timedelta(days=1), observed=observed)
        assert report(store)['insights'] == []


def test_cross_destination_post_rejected_before_get(source):
    path, root, png = source
    with WorkflowStore(path) as store:
        _, post = authorized(store, root, png)
        run_fake(store, root, composition(store)[0], post)
        with store.transaction():
            other = store.connection.execute(
                "INSERT INTO social_destinations(configuration_release_id,destination_key,platform,account_key,"
                "provider_account_id,secret_ref,enabled,config_json,config_fingerprint,created_at) "
                "SELECT configuration_release_id,'instagram:other','instagram','other','999','NO_SECRET',0,"
                "config_json,config_fingerprint,created_at FROM social_destinations LIMIT 1").lastrowid
        observed = parse_timestamp(publication(store, post)['published_at']) + timedelta(days=1)
        with pytest.raises(CollectionError, match='publication_binding'):
            collect_offline(store, other, transport=FixtureTransport({}), post_ids=[post],
                            day=observed.date() - timedelta(days=1), observed_at=observed, fetched_at=observed)
        assert store.connection.execute('SELECT count(*) FROM measurement_observations').fetchone()[0] == 0
