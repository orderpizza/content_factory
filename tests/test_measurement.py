"""Phase 4A: offline provenance, immutable snapshots, attribution and restart."""
from dataclasses import asdict, replace
import json
from pathlib import Path
import sqlite3
import subprocess
import sys

import pytest

from database.current import initialize_database, connect, validate_database, SCHEMA_NAME, V19_CHECKSUM, SchemaError
from database.migrate_measurement import migrate, v19_sql
from workflow.delivery_simulation import initialize_simulation, simulation_store, post_now, review_identity, run_once, DESTINATION
from workflow.measurement import Observation, ingest_offline, latest_observations, publication
from workflow.measurement_report import operator_report
from workflow.offline import offline_only
from workflow.store import WorkflowStore, digest, now

START, END = '2026-01-01T00:00:00', '2027-01-01T00:00:00'
ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(autouse=True)
def no_network():
    with offline_only():
        yield


@pytest.fixture
def workspace(tmp_path):
    return initialize_simulation(tmp_path / 'synthetic-measurement')


def observation(store, **changes):
    d = store.connection.execute('SELECT * FROM social_destinations ORDER BY social_destination_id LIMIT 1').fetchone()
    value = Observation(
        source_key='synthetic:reach:1', social_destination_id=d['social_destination_id'],
        account_key=d['account_key'], provider_account_id=d['provider_account_id'],
        definition_version='synthetic_insights_v1', metric='reach', unit='count', scope='account',
        provenance='synthetic', value_status='known', value=100,
        window_start='2026-11-01T00:00:00', window_end='2026-11-02T00:00:00',
        observed_at='2026-11-02T00:00:00', fetched_at='2026-11-02T01:00:00',
        provider='synthetic', api_version='fixture-v1', login='fixture', capability='synthetic_insights_v1',
        source_response_hash=digest({'synthetic': 100}), evidence_ref='synthetic-response-1')
    return replace(value, **changes)


def publish_synthetic(store, root, outcome='success'):
    row = store.connection.execute('SELECT * FROM review_requests').fetchone()
    post = post_now(store, review_id=row['review_request_id'], row_version=row['row_version'],
                    identity=review_identity(row), destination=DESTINATION, command_id='synthetic-post-now')
    run_once(store, root, outcome=outcome)
    return post


def test_replay_correction_late_arrival_and_restart(workspace):
    with simulation_store(workspace) as store:
        value = observation(store)
        first, = ingest_offline(store, [value])
        assert ingest_offline(store, [value, value]) == [first, first]
        with pytest.raises(ValueError, match='different observation'):
            ingest_offline(store, [replace(value, value=80)])
        with pytest.raises(ValueError, match='supersession'):
            ingest_offline(store, [replace(value, source_key='silent-correction', value=80)])
        correction = replace(value, source_key='explicit-correction', value=80, supersedes_id=first,
                             fetched_at='2026-11-03T00:00:00')
        second, = ingest_offline(store, [correction])
        # Late older observation in the same window must not roll the projection back.
        newer = replace(value, source_key='newer', observed_at='2026-11-04T00:00:00', fetched_at='2026-11-04T00:00:00', value=120)
        ingest_offline(store, [newer])
        late = replace(value, source_key='late', observed_at='2026-11-03T00:00:00', fetched_at='2026-11-05T00:00:00', value=90)
        ingest_offline(store, [late])
        older_window = replace(value, source_key='older-window', window_start='2026-10-01T00:00:00',
                               window_end='2026-10-02T00:00:00', observed_at='2026-10-02T00:00:00', fetched_at='2026-11-06T00:00:00')
        ingest_offline(store, [older_window])
        latest = latest_observations(store, 1, START, END)
        assert sorted(r['value'] for r in latest) == [100, 120]
        assert latest_observations(store, 1, START, END, as_of='2026-11-02T12:00:00')[0]['value'] == 100
        assert latest_observations(store, 1, START, END, as_of='2026-11-03T12:00:00')[0]['value'] == 80
        with pytest.raises(sqlite3.IntegrityError):
            ingest_offline(store, [replace(correction, source_key='fork')])
        with pytest.raises(sqlite3.IntegrityError):
            store.connection.execute('UPDATE measurement_observations SET value=0')
        with pytest.raises(sqlite3.IntegrityError):
            store.connection.execute('DELETE FROM measurement_observations')
        store.connection.rollback()
    with simulation_store(workspace) as store:
        assert ingest_offline(store, [value, correction]) == [first, second]
        assert store.connection.execute('SELECT count(*) FROM measurement_observations').fetchone()[0] == 5
        assert latest_observations(store, 1, START, END)[0]['value'] == 120


@pytest.mark.parametrize('changes', [
    {'provenance': 'authenticated_platform'}, {'provenance': 'human_estimate'},
    {'metric': 'made_up'}, {'api_version': 'v27.0'}, {'login': 'instagram_login'},
    {'capability': 'stale-token'}, {'provider_account_id': 'wrong'}, {'account_key': 'english'},
    {'unit': 'percent'}, {'metric': 'saves'}, {'scope': 'post'}, {'value': None},
    {'value': False}, {'value': -1}, {'value': 1.5}, {'value_status': 'unavailable'},
    {'window_end': '2026-12-01T00:00:00'}, {'fetched_at': '2026-10-01T00:00:00'},
    {'media_id': '123'}, {'receipt_resource_id': 1}, {'source_response_hash': 'not-a-hash'},
    {'evidence_ref': 'https://example.invalid/token=secret'}, {'post_record_id': True},
])
def test_invalid_or_forged_observations_refused(workspace, changes):
    with simulation_store(workspace) as store:
        with pytest.raises(ValueError):
            ingest_offline(store, [observation(store, **changes)])
        assert store.connection.execute('SELECT count(*) FROM measurement_observations').fetchone()[0] == 0


@pytest.mark.parametrize('status', ['unknown', 'unavailable', 'not_authorized', 'not_collected'])
def test_missing_is_not_zero_and_no_denominator_mixing(workspace, status):
    with simulation_store(workspace) as store:
        value = observation(store, value=None, value_status=status,
                            provenance='not_collected' if status == 'not_collected' else 'synthetic')
        ingest_offline(store, [value])
        result = operator_report(store, 1, START, END)
        assert result['insights'][0]['value'] is None
        assert result['insights'][0]['value_status'] == status
        assert all(r['authenticated_status'] == 'not_collected' for r in result['coverage'])
        assert result['kpis']['engagement_rate'] is None
        assert result['costs']['destination']['known_internal_micro_usd'] is None
        assert result['costs']['destination']['ledger_complete'] is False
        follows = next(r for r in result['coverage'] if r['metric'] == 'follows')
        assert follows['fixture_or_estimate_statuses'] == {'not_collected': 1}


def test_failed_batch_is_atomic_and_correction_cannot_change_window(workspace):
    with simulation_store(workspace) as store:
        value = observation(store)
        with pytest.raises(ValueError):
            ingest_offline(store, [value, replace(value, source_key='bad', provider_account_id='other')])
        assert store.connection.execute('SELECT count(*) FROM measurement_observations').fetchone()[0] == 0
        first, = ingest_offline(store, [value])
        with pytest.raises(ValueError, match='preserve stream'):
            ingest_offline(store, [replace(value, source_key='changed-window', supersedes_id=first,
                                          window_start='2026-10-01T00:00:00')])
        store.connection.execute("CREATE TEMP TRIGGER fail_measurement BEFORE INSERT ON measurement_observations "
                                 "WHEN NEW.metric='follows' BEGIN SELECT RAISE(ABORT,'disk failure'); END")
        with pytest.raises(sqlite3.IntegrityError):
            ingest_offline(store, [replace(value, source_key='later', observed_at='2026-11-03T00:00:00', fetched_at='2026-11-03T00:00:00'),
                                   replace(value, source_key='follows', metric='follows')])
        assert store.connection.execute('SELECT count(*) FROM measurement_observations').fetchone()[0] == 1


@pytest.mark.parametrize('count', [4, 5, 6])
def test_simulated_post_metrics_and_report_are_never_real(tmp_path, count):
    root = initialize_simulation(tmp_path / 'synthetic', slide_count=count)
    with simulation_store(root) as store:
        post = publish_synthetic(store, root)
        value = observation(store, scope='post', post_record_id=post, media_id=f'simulated:post:{post}')
        ingest_offline(store, [value, observation(store, source_key='account-reach')])
        result = operator_report(store, 1, START, END)
        assert result['funnel']['published_by_evidence'] == {'simulated': 1}
        assert result['funnel']['authenticated_published'] == 0
        assert result['real_account_performance_available'] is False
        assert len(result['insights']) == 2
        assert {r['scope'] for r in result['insights']} == {'post', 'account'}
        assert all(r['evidence']['authenticated'] is False for r in result['insights'])
        with pytest.raises(ValueError, match='media identity'):
            ingest_offline(store, [replace(value, source_key='wrong-id', media_id='999')])


def test_human_declared_unknown_and_estimated_costs(workspace):
    from workflow.delivery import PublicationReconciliationWorker
    with simulation_store(workspace) as store:
        post = publish_synthetic(store, workspace, outcome='unknown')
        assert publication(store, post)['classification'] == 'publication_unknown'
        ingest_offline(store, [observation(store, scope='post', post_record_id=post)])
        request = store.request_publication_reconciliation(post, command_id='investigate')
        check = PublicationReconciliationWorker(store).run_once()
        store.resolve_publication_unknown(request, reconciliation_check_id=check, decision='published',
                                          note='Synthetic human declaration only', row_version=2, command_id='human-decision')
        assert publication(store, post)['classification'] == 'human_declared'
        manual = observation(store, source_key='operator-time', definition_version='manual_operations_v1',
                             metric='operator_minutes', unit='minutes', scope='post', post_record_id=post,
                             provenance='human_estimate', value=7, provider='manual', api_version='not_applicable',
                             login='none', capability='manual_operations_v1')
        ingest_offline(store, [manual])
        result = operator_report(store, 1, START, END)
        assert result['funnel']['published_by_evidence'] == {'human_declared': 1}
        assert result['manual_operations'][0]['provenance'] == 'human_estimate'
        assert result['manual_operations'][0]['value'] == 7
        assert result['kpis']['cost_per_authenticated_published_micro_usd'] is None


def test_offline_receipt_binding_and_conflicting_ids(source):
    # The production factory's 4/5/6-slide fixtures exercise verified provider proof,
    # which remains offline even though its post state is published.
    from instagram_fakes import composition
    from test_instagram_posting_integration import authorized, run_fake
    path, root, png = source
    with WorkflowStore(path) as store:
        _, post = authorized(store, root, png)
        factory, _, _ = composition(store)
        run_fake(store, root, factory, post)
        evidence = publication(store, post)
        assert evidence['classification'] == 'synthetic_verified'
        value = observation(store, scope='post', post_record_id=post, media_id=evidence['external_post_id'],
                            receipt_resource_id=evidence['receipt_resource_ids'][0])
        observation_ids = ingest_offline(store, [value])
        assert operator_report(store, 1, START, END)['insights'][0]['evidence']['publication_binding'] == 'synthetic_verified'
        with pytest.raises(ValueError):
            ingest_offline(store, [replace(value, source_key='forged-real', provenance='authenticated_platform')])
        r = store.connection.execute("SELECT * FROM publication_resources WHERE resource_type='instagram_publish_acceptance'").fetchone()
        with store.transaction():
            store.connection.execute('INSERT INTO publication_resources(post_attempt_id,resource_type,remote_id,status,safe_metadata_json,created_at,updated_at) '
                                     'VALUES (?,?,?,?,?,?,?)', (r['post_attempt_id'], r['resource_type'], '999999', r['status'], r['safe_metadata_json'], now(), now()))
        assert publication(store, post)['classification'] == 'conflicting_identity'
        assert ingest_offline(store, [value]) == observation_ids  # unchanged replay retains original evidence
        with pytest.raises(ValueError, match='conflicts'):
            ingest_offline(store, [replace(value, source_key='conflict')])


# Reuse actual registered adapter/source fixtures; no external requests.
from test_instagram_posting_integration import source  # noqa: E402,F401


def test_costs_single_ledger_partial_usage_attribution_and_late_settlement(workspace):
    with simulation_store(workspace) as store:
        post = publish_synthetic(store, workspace)
        job = publication(store, post)['content_job_id']
        generation = store.connection.execute('SELECT generation_run_id FROM generation_runs').fetchone()[0]
        def invocation(entity='generation_run', entity_id=generation, usage=True, outcome='succeeded'):
            return store.connection.execute(
                'INSERT INTO model_invocations(phase,entity_type,entity_id,attempt_ordinal,request_version,prompt_version,schema_version,request_hash,outcome,started_at,input_tokens,output_tokens,estimated_cost_micro_usd) '
                "VALUES ('generation',?,?,1,'fixture','fixture','fixture',?,?,?, ?,?,999999)",
                (entity, entity_id, 'a'*64, outcome, '2026-11-03T00:00:00', 10 if usage else None, 5 if usage else None)).lastrowid
        with store.transaction():
            settled = invocation()
            uncertain = invocation(usage=False, outcome='ambiguous_outcome')
            missing = invocation(usage=False)
            overhead = invocation(entity='intake_request', entity_id=1)
            for inv, status, amount, attributed_job in [(settled, 'settled', 120, job), (uncertain, 'uncertain', None, job),
                                                        (overhead, 'settled', 30, None)]:
                store.connection.execute('INSERT INTO gemini_budget_reservations(accounting_day,model_invocation_id,content_job_id,phase,worst_case_micro_usd,settled_micro_usd,status,created_at) '
                                         "VALUES ('2026-11-03',?,?,'generation',500,?,?,?)", (inv, attributed_job, amount, status, '2026-11-03T00:00:00'))
        result = operator_report(store, 1, START, END)['costs']
        assert result['destination']['known_internal_micro_usd'] == 120  # not 999999 + 500 + 120
        assert result['destination']['outstanding_reservation_estimate_micro_usd'] == 500
        assert result['destination']['incomplete_entries'] == 2
        assert result['shared_or_unattributed_excluded'][0]['internal_cost_micro_usd'] == 30
        assert next(r for r in result['entries'] if r['invocation_id'] == missing)['internal_cost_micro_usd'] is None
        assert {r['post_record_id'] for r in result['entries']} == {post}
        with store.transaction():
            store.connection.execute('UPDATE model_invocations SET input_tokens=10,output_tokens=5 WHERE model_invocation_id=?', (uncertain,))
            store.connection.execute("UPDATE gemini_budget_reservations SET status='settled',settled_micro_usd=200,settled_at=? WHERE model_invocation_id=?", (now(), uncertain))
    with simulation_store(workspace) as store:
        result = operator_report(store, 1, START, END)['costs']
        assert result['destination']['known_internal_micro_usd'] == 320
        assert result['destination']['incomplete_entries'] == 1
        assert result['destination']['invoice_cost_micro_usd'] is None


def test_migration_backup_rollback_idempotence_and_tamper(tmp_path, monkeypatch):
    import database.migrate_measurement as migration
    path = tmp_path / 'v19.db'
    with sqlite3.connect(path) as db:
        db.executescript(v19_sql())
        db.execute('INSERT INTO schema_migrations VALUES (1,19,?,?,?)', (SCHEMA_NAME, V19_CHECKSUM, now()))
        db.execute("INSERT INTO content_threads(origin,status,created_at,updated_at) VALUES ('human','open',?,?)", (now(), now()))
        before = list(db.iterdump())
    with pytest.raises(SchemaError): initialize_database(path)
    assert migrate(path) == 'dry_run_ok'
    with sqlite3.connect(path) as db: assert before == list(db.iterdump())
    with pytest.raises(FileExistsError): migrate(path, apply=True, backup=path)
    original = migration._apply
    def fail(db):
        original(db)
        raise RuntimeError('before commit')
    monkeypatch.setattr(migration, '_apply', fail)
    with pytest.raises(RuntimeError): migrate(path, apply=True, backup=tmp_path / 'failed.db')
    with sqlite3.connect(path) as db: assert before == list(db.iterdump())
    monkeypatch.setattr(migration, '_apply', original)
    backup = tmp_path / 'backup.db'
    assert migrate(path, apply=True, backup=backup) == 'migrated'
    with sqlite3.connect(backup) as db: assert before == list(db.iterdump())
    with connect(path) as db:
        validate_database(db)
        assert [r[0] for r in db.execute('SELECT version FROM schema_migrations')] == [19, 20]
        assert db.execute('SELECT count(*) FROM content_threads').fetchone()[0] == 1
    assert migrate(path, apply=True, backup=backup) == 'already_current'
    assert initialize_database(path) is False
    with sqlite3.connect(backup) as db: db.execute('DROP TRIGGER package_visual_lineage_immutable')
    with pytest.raises(SchemaError, match='executable schema'): migrate(backup)


def test_cli_default_isolated_demo_replay_read_only_report(tmp_path):
    def cli(*args):
        result = subprocess.run([sys.executable, str(ROOT / 'scripts/measure_offline.py'), *map(str, args)], capture_output=True, text=True)
        assert result.returncode == 0, result.stderr
        return json.loads(result.stdout)
    result = cli('synthetic-demo', '--workspace', tmp_path / 'synthetic-demo', '--slides', 4)
    path = Path(result['database'])
    with WorkflowStore(path, read_only=True) as store:
        before = list(store.connection.iterdump())
    cli('ingest', '--database', path, '--observations', path.parent / 'synthetic-observations.json', '--append-offline-observations')
    report = cli('report', '--database', path, '--destination-id', 1, '--start', START, '--end', END)
    assert report['insights'][0]['value'] == 123
    assert report['insights'][0]['provenance'] == 'synthetic'
    assert report['funnel']['post_now'] == 0
    with WorkflowStore(path, read_only=True) as store:
        assert list(store.connection.iterdump()) == before


def test_accounts_are_isolated_and_cross_account_post_refused(workspace):
    with simulation_store(workspace) as store:
        post = publish_synthetic(store, workspace)
        original = observation(store)
        with store.transaction():
            other = store.connection.execute(
                "INSERT INTO social_destinations(configuration_release_id,destination_key,platform,account_key,provider_account_id,secret_ref,enabled,config_json,config_fingerprint,created_at) "
                "SELECT configuration_release_id,'instagram:other','instagram','other','999','NO_SECRET',0,config_json,config_fingerprint,created_at FROM social_destinations LIMIT 1").lastrowid
        other_value = replace(original, source_key='other-account', social_destination_id=other, account_key='other', provider_account_id='999')
        ingest_offline(store, [original, other_value])
        with pytest.raises(ValueError, match='post destination'):
            ingest_offline(store, [replace(other_value, source_key='wrong-post', scope='post', post_record_id=post)])
        assert len(operator_report(store, 1, START, END)['insights']) == 1
        other_report = operator_report(store, other, START, END)
        assert len(other_report['insights']) == 1
        assert other_report['publication_evidence'] == []


def test_ingest_requires_offline_boundary_and_closed_typed_fields(workspace):
    from workflow.offline import _OFFLINE
    with simulation_store(workspace) as store:
        value = observation(store)
        token = _OFFLINE.set(False)
        try:
            with pytest.raises(RuntimeError, match='network-refusal'):
                ingest_offline(store, [value])
        finally:
            _OFFLINE.reset(token)
        payload = asdict(value)
        payload.pop('value')
        with pytest.raises(TypeError): Observation(**payload)
        payload['value'] = None
        payload['raw_provider_response'] = {'secret': 'must-not-persist'}
        with pytest.raises(TypeError): Observation(**payload)
        assert store.connection.execute('SELECT count(*) FROM measurement_observations').fetchone()[0] == 0


def test_manual_storage_delivery_zero_and_overlapping_window_selection(workspace):
    with simulation_store(workspace) as store:
        manual = observation(store, source_key='storage-cost', definition_version='manual_operations_v1',
                             metric='storage_cost', unit='micro_usd', provenance='human_estimate', value=0,
                             provider='manual', api_version='not_applicable', login='none', capability='manual_operations_v1')
        ingest_offline(store, [manual, replace(manual, source_key='delivery-cost', metric='delivery_cost', value=30)])
        result = operator_report(store, 1, START, END)
        assert sorted(r['value'] for r in result['manual_operations']) == [0, 30]
        assert all(r['provenance'] == 'human_estimate' for r in result['manual_operations'])
        assert operator_report(store, 1, '2026-11-01T12:00:00', END)['manual_operations'] == []
        assert result['costs']['destination']['known_internal_micro_usd'] is None  # no mixing into model ledger
        assert next(r for r in result['manual_coverage'] if r['metric'] == 'operator_minutes')['status'] == 'not_collected'


def test_usage_without_pricing_does_not_turn_legacy_default_into_free_work(workspace):
    with simulation_store(workspace) as store:
        post = publish_synthetic(store, workspace)
        generation = store.connection.execute('SELECT generation_run_id FROM generation_runs').fetchone()[0]
        with store.transaction():
            store.connection.execute(
                'INSERT INTO model_invocations(phase,entity_type,entity_id,attempt_ordinal,request_version,prompt_version,schema_version,request_hash,outcome,started_at,input_tokens,output_tokens) '
                "VALUES ('generation','generation_run',?,1,'fixture','fixture','fixture',?,'succeeded',?,10,5)",
                (generation, 'a'*64, '2026-11-03T00:00:00'))
        result = operator_report(store, 1, START, END)['costs']
        assert result['entries'][0]['usage_observed'] is True
        assert result['entries'][0]['post_record_id'] == post
        assert result['entries'][0]['internal_cost_micro_usd'] is None
        assert result['destination']['known_internal_micro_usd'] is None
        assert result['destination']['ledger_complete'] is False
