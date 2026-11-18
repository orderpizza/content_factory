"""Real registration/preflight contracts, with no external service access."""
from dataclasses import replace
from datetime import timedelta
from pathlib import Path
import json

import pytest

from common.timestamps import utc_datetime_now, serialize_timestamp
from database.current import initialize_database
from detection.configuration import load_manifest
from detection.store import DetectionStore
from workflow.delivery import DeliveryConfigurationError
from workflow.delivery_fixtures import production_configuration
from workflow.instagram_composition import (InstagramComposition, EnvironmentCredentials,
    registration, validate_registration, validate_persisted_readiness)
from workflow.offline import offline_only
from workflow.store import WorkflowStore
from instagram_fakes import composition

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def store(tmp_path):
    path = tmp_path / 'fixture.db'
    initialize_database(path)
    with DetectionStore(path) as detection:
        detection.apply_manifest(load_manifest(ROOT / 'config/releases/detection.json'))
    with WorkflowStore(path, catalog_kind='production') as store:
        config = production_configuration()
        config['destinations'][0]['config'] = registration(app_id='789')
        store.register_production_configuration(config)
        yield store


def test_registration_defaults_disabled_and_cannot_create_work(store):
    row = store.connection.execute('SELECT * FROM social_destinations').fetchone()
    assert json.loads(row['config_json'])['enabled'] is False
    assert store.connection.execute('SELECT status FROM capability_readiness').fetchone()[0] == 'unknown'
    for table in ('post_requests', 'post_records', 'post_attempts', 'publication_resources'):
        assert store.connection.execute(f'SELECT COUNT(*) FROM {table}').fetchone()[0] == 0
    with pytest.raises(DeliveryConfigurationError, match='unverified'):
        InstagramComposition(store, row['social_destination_id'])
    with offline_only():
        factory, objects, http = composition(store)
        assert not http.read_calls and not objects.objects
        proof = factory.preflight()
        assert len(http.read_calls) == 3 and not http.protocol.calls and not objects.objects
        with pytest.raises(DeliveryConfigurationError, match='disabled'):
            factory.activate(proof, post_record_id=1, command_id='run', confirm=True)


def test_fake_readiness_is_degraded_and_never_production_evidence(store):
    with offline_only():
        factory, _, _ = composition(store)
        proof = factory.preflight()
        assert store.connection.execute('SELECT status FROM capability_readiness').fetchone()[0] == 'degraded'
        validate_persisted_readiness(store, proof.destination_id)
        with pytest.raises(ValueError, match='issued'):
            store.record_destination_readiness(proof.destination_id, status='degraded',
                                              facts=proof.facts(), reasons=[])
        store.record_destination_readiness(proof.destination_id, status='blocked', reasons=['revoked'], facts={})
        with pytest.raises(DeliveryConfigurationError, match='new preflight'):
            store.record_destination_readiness(proof.destination_id, status='ready', reasons=[],
                                              facts=proof.facts(), preflight=proof)
        assert store.connection.execute('SELECT status FROM capability_readiness').fetchone()[0] == 'blocked'
        # A caller cannot copy, construct or mutate observations into issued evidence.
        for forged in (None, replace(proof), replace(proof, provenance='authenticated')):
            with pytest.raises(DeliveryConfigurationError):
                store.record_destination_readiness(proof.destination_id, status='ready', reasons=[],
                                                  facts=proof.facts(), preflight=forged)
    assert not any(o['ready'] for p in store.catalog() for o in p['outputs'])
    with pytest.raises(ValueError, match='authenticated'):
        validate_persisted_readiness(store, proof.destination_id)
    with pytest.raises(DeliveryConfigurationError, match='failed closed'):
        factory.preflight()  # Failed refresh must revoke the earlier evidence.


@pytest.mark.parametrize('fault', ['account', 'consumer', 'permissions', 'denied', 'duplicate', 'paging',
    'token', 'token_account', 'app', 'login', 'token_type', 'token_version', 'expiry',
    'quota_missing', 'quota_exhausted', 'quota_negative', 'quota_bool', 'window',
    'version', 'rate_limit', 'no_token', 'wrong_token', 'clock'])
def test_preflight_failures_revoke_previous_evidence_without_secrets(store, fault, caplog):
    with offline_only():
        environment = {'DELIVERY_TOKEN': 'fixture-secret'}
        clock = [utc_datetime_now()]
        factory, objects, http = composition(store, credentials=EnvironmentCredentials(environment), clock=lambda: clock[0])
        proof = factory.preflight()
        if fault == 'account': http.identity['user_id'] = '999'
        elif fault == 'consumer': http.identity['account_type'] = 'PERSONAL'
        elif fault == 'permissions': http.permissions['data'].pop()
        elif fault == 'denied': http.permissions['data'][0]['status'] = 'declined'
        elif fault == 'duplicate': http.permissions['data'].append({**http.permissions['data'][0], 'status': 'declined'})
        elif fault == 'paging': http.permissions['paging'] = {'next': 'https://example.invalid'}
        elif fault == 'token': http.validity['is_valid'] = False
        elif fault == 'token_account': http.validity['account_id'] = '999'
        elif fault == 'app': http.validity['app_id'] = '999'
        elif fault == 'login': http.validity['login_mode'] = 'facebook_login'
        elif fault == 'token_type': http.validity['token_type'] = 'page'
        elif fault == 'token_version': http.validity['api_version'] = 'v27.0'
        elif fault == 'expiry': http.validity['expires_at'] = '2000-01-01T00:00:00'
        elif fault == 'quota_missing': http.quota = {}
        elif fault == 'quota_exhausted': http.quota['data'][0]['quota_usage'] = 20
        elif fault == 'quota_negative': http.quota['data'][0]['quota_usage'] = -1
        elif fault == 'quota_bool': http.quota['data'][0]['quota_usage'] = False
        elif fault == 'window': http.quota['data'][0]['config']['quota_duration'] = 0
        elif fault == 'version': http.version = 'v27.0'
        elif fault == 'rate_limit': http.status = 429
        elif fault == 'no_token': environment.clear()
        elif fault == 'wrong_token': environment['DELIVERY_TOKEN'] = 'wrong-secret'
        else: http.after = lambda: clock.__setitem__(0, clock[0] + timedelta(minutes=1))
        with pytest.raises(DeliveryConfigurationError) as error:
            factory.preflight()
        assert store.connection.execute('SELECT status FROM capability_readiness').fetchone()[0] == 'blocked'
        assert not objects.objects and not http.protocol.calls
        persisted = '\n'.join(store.connection.iterdump())
        for secret in ('fixture-secret', 'wrong-secret'):
            assert secret not in persisted + caplog.text + str(error.value) + repr(proof)


@pytest.mark.parametrize('change', [{'api_version': 'latest'}, {'api_version': 'v27.0'},
    {'login_mode': 'facebook_login'}, {'enabled': 1}, {'credential_generation': 0},
    {'access_token': 'not-allowed'}, {'contract_ref': 'verified-by-caller'}, {'app_id': '0'}])
def test_registration_is_closed_and_never_infers_verified_version(change):
    with pytest.raises(ValueError):
        validate_registration({**registration(app_id='789'), **change})


@pytest.mark.parametrize('change', [
    {'containers_created': None}, {'containers_created': True}, {'containers_created': -1},
    {'containers_created': 400}, {'window_seconds': 3600}, {'account_id': '999'},
    {'observed_at': '2000-01-01T00:00:00'}, {'api_version': 'v27.0'},
    {'parent_ai_disclosure': False}, {'child_alt_text': None},
])
def test_creation_usage_and_parent_capability_are_independent_preflight_gates(store, change):
    with offline_only():
        factory, objects, http = composition(store)
        factory.preflight()
        http.carousel.update(change)
        with pytest.raises(DeliveryConfigurationError, match='failed closed'):
            factory.preflight()
        assert store.connection.execute('SELECT status FROM capability_readiness').fetchone()[0] == 'blocked'
        assert not objects.objects and not http.protocol.calls
