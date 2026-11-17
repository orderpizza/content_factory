"""Disabled-by-default Instagram registration, preflight and one-post composition.

The trust boundary is local application code/OS ownership, not protection against
arbitrary Python or direct SQLite writes. Caller observations and injected I/O are
never authenticated evidence. No live contract is verified in this checkpoint.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import timedelta
from hashlib import sha256
import hmac
import json
import os
import re
import secrets
import time
from typing import Any, Mapping, Protocol
from weakref import WeakSet

from common.timestamps import parse_timestamp, serialize_timestamp, utc_datetime_now
from .delivery import CredentialedPostingAgent, DeliveryConfigurationError, DeliveryError, R2TransientRelay
from .instagram_http import InstagramHTTPTransport
from .instagram_protocol import OfflineInstagramProtocol
from .instagram_readiness import InstagramLoginConfiguration, PERMISSIONS, ScopedToken, VERSION
from .offline import require_offline, is_offline
from .store import canonical, digest, now

MAX_EXECUTION_SECONDS = 45 * 60
HEARTBEAT_SECONDS = 30

ADAPTER_VERSION = "instagram_login_v1"
CONTRACT_REF = "instagram_login_candidate_v1"
# Deliberately empty: v26 is a candidate fixture contract, not verified Meta support.
# A reviewed code change must supply official endpoint/token/version evidence before
# introducing a live contract. Configuration JSON cannot add entries to this registry.
VERIFIED_LIVE_CONTRACTS: frozenset[str] = frozenset()
_PROOFS: WeakSet = WeakSet()
_ACTIVATIONS: WeakSet = WeakSet()
_CREDENTIAL_KEY = secrets.token_bytes(32)


def registration(*, enabled: bool = False, credential_generation: int = 1, app_id: str) -> dict:
    return {"adapter_version": ADAPTER_VERSION, "login_mode": "instagram_login",
            "api_version": VERSION, "contract_ref": CONTRACT_REF, "enabled": enabled,
            "credential_generation": credential_generation, "app_id": app_id}


def validate_registration(value: dict) -> None:
    if (not isinstance(value, dict) or set(value) != set(registration(app_id="1"))
            or value["adapter_version"] != ADAPTER_VERSION or value["login_mode"] != "instagram_login"
            or value["api_version"] != VERSION or value["contract_ref"] != CONTRACT_REF
            or type(value["enabled"]) is not bool or type(value["credential_generation"]) is not int
            or value["credential_generation"] < 1 or not isinstance(value["app_id"], str)
            or not re.fullmatch(r"[1-9][0-9]{0,29}", value["app_id"])):
        raise ValueError("invalid closed Instagram adapter registration")


def _destination(store, destination_id):
    row = store.connection.execute(
        "SELECT d.* FROM social_destinations d JOIN configuration_activations a "
        "ON a.configuration_release_id=d.configuration_release_id "
        "AND a.scope_key='global' AND a.status='active' WHERE d.social_destination_id=?",
        (destination_id,)).fetchone()
    if row is None:
        raise DeliveryConfigurationError("active destination is missing")
    row = dict(row)
    row['config'] = json.loads(row['config_json'])
    validate_registration(row['config'])
    config = InstagramLoginConfiguration(row['provider_account_id'], row['destination_key'],
        row['secret_ref'], api_version=row['config']['api_version'], enabled=row['config']['enabled'])
    config.validate()
    return row, config


class EnvironmentCredentials:
    """Read an OS-injected secret on each check; no dotenv, files, CLI or DB tokens.

    Rotation replaces DELIVERY_TOKEN in the worker environment (restart for an OS
    environment change), then requires a fresh preflight and run activation. An
    immutable new configuration release can also advance credential_generation.
    """
    def __init__(self, environment: Mapping[str, str] | None = None):
        if environment is not None:
            require_offline()
        self._environment = environment

    def resolve(self, config):
        if self._environment is not None:
            require_offline()
        return ScopedToken.resolve(config, os.environ if self._environment is None else self._environment)


def _token_binding(token):
    return hmac.new(_CREDENTIAL_KEY, token.value.encode(), sha256).digest()


class TokenValidityReader(Protocol):
    """Selected-login token introspection interface. Must not persist raw replies.

    No live implementation is registered until the credential introspection endpoint,
    app binding and safe authentication flow have been externally verified. Offline
    contract tests inject this reader alongside fake HTTP and storage.
    """
    def __call__(self, token: ScopedToken) -> Mapping[str, Any]: ...


@dataclass(frozen=True, eq=False)
class PreflightResult:
    destination_id: int
    configuration_hash: str
    account_id: str
    app_id: str
    login_mode: str
    api_version: str
    account_type: str
    permissions: tuple[str, ...]
    observed_at: str
    valid_until: str
    token_valid_until: str
    quota_used: int
    quota_total: int
    quota_window_seconds: int
    credential_generation: int
    provenance: str
    evidence_id: str
    _token_binding: bytes = field(repr=False)

    def facts(self):
        value = asdict(self)
        del value['_token_binding']
        return value


def validate_proof(proof, row, *, moment=None, allow_expired=False):
    if type(proof) is not PreflightResult or proof not in _PROOFS:
        raise DeliveryConfigurationError("readiness requires an issued preflight result")
    if proof.provenance == 'offline':
        require_offline()
    else:
        raise DeliveryConfigurationError("no authenticated live preflight contract is registered")
    current = moment or utc_datetime_now()
    if (proof.destination_id != row['social_destination_id']
            or proof.configuration_hash != digest(dict(row))
            or current < parse_timestamp(proof.observed_at)
            or (not allow_expired and current >= parse_timestamp(proof.valid_until))
            or current >= parse_timestamp(proof.token_valid_until)):
        raise DeliveryConfigurationError("preflight evidence is stale or configuration mismatched")


class InstagramComposition:
    """The single factory for registered production catalogs and offline I/O tests.

    Construction/configuration cannot send. preflight() is explicitly read-only;
    activate() records one-post intent but cannot send; agent() returns a scoped
    agent which still requires its explicit run_once(). Live construction is blocked.
    """
    def __init__(self, store, destination_id: int, *, credentials=None, wire=None,
                 token_validity: TokenValidityReader | None = None,
                 objects=None, media_transport=None, relay_config=None, clock=utc_datetime_now,
                 monotonic=time.monotonic, sleep=time.sleep):
        self.store, self.destination_id, self.clock = store, destination_id, clock
        self.monotonic, self.sleep = monotonic, sleep
        row, self.config = _destination(store, destination_id)
        self._offline = any(x is not None for x in (wire, token_validity, objects, media_transport))
        if self._offline:
            require_offline()
            if any(x is None for x in (wire, token_validity, objects, media_transport)):
                raise DeliveryConfigurationError("offline composition requires all HTTP/token/storage fakes")
        elif row['config']['contract_ref'] not in VERIFIED_LIVE_CONTRACTS:
            raise DeliveryConfigurationError("live Instagram contract/version/token preflight is unverified")
        self.credentials = credentials or EnvironmentCredentials()
        self._wire, self._token_validity = wire, token_validity
        self._objects, self._media_transport, self._relay_config = objects, media_transport, relay_config

    def preflight(self, *, before_request=None) -> PreflightResult:
        """Read identity, grants, token validity and dynamic quota; whitelist evidence."""
        row, config = _destination(self.store, self.destination_id)
        try:
            if self._offline:
                require_offline()
            token = self.credentials.resolve(config)
            client = InstagramHTTPTransport(config, token, verified_version=config.api_version, wire=self._wire)
            started = self.clock()
            check = before_request or (lambda: None)
            check()
            validity = self._token_validity(token)
            check()
            identity = client.request('GET', '/me', {'fields': 'user_id,account_type'})
            check()
            grants = client.request('GET', '/me/permissions', {})
            check()
            quota = client.request('GET', f'/{config.account_id}/content_publishing_limit',
                                   {'fields': 'quota_usage,config'})
            entries = grants['data']
            if (not isinstance(entries, list) or not 1 <= len(entries) <= 100
                    or any(not isinstance(item, dict) or not isinstance(item.get('permission'), str)
                           or item.get('status') not in {'granted', 'declined', 'expired'} for item in entries)
                    or len({item['permission'] for item in entries}) != len(entries)):
                raise ValueError()
            permissions = frozenset(item['permission'] for item in entries if item['status'] == 'granted')
            # Partial/paginated grants cannot establish completeness.
            if grants.get('paging'):
                raise ValueError()
            quota_data, = quota['data']
            used, total, window = quota_data['quota_usage'], quota_data['config']['quota_total'], quota_data['config']['quota_duration']
            token_until = parse_timestamp(validity['expires_at'])
            current = self.clock()
            if (validity['is_valid'] is not True or validity['account_id'] != config.account_id
                    or validity['login_mode'] != config.login_mode or validity['app_id'] != row['config']['app_id']
                    or validity['token_type'] != 'instagram_user' or validity['api_version'] != config.api_version
                    or identity['user_id'] != config.account_id or identity['account_type'] not in {'BUSINESS', 'CREATOR'}
                    or permissions != PERMISSIONS or token_until <= current
                    or any(type(x) is not int for x in (used, total, window))
                    or used < 0 or total <= used or not 1 <= window <= 86400
                    or not started <= current <= started + timedelta(seconds=60)):
                raise ValueError()
            expires = min(started + timedelta(minutes=5), token_until)
            proof = PreflightResult(self.destination_id, digest(row), config.account_id, row['config']['app_id'],
                config.login_mode, config.api_version, identity['account_type'], tuple(sorted(permissions)),
                serialize_timestamp(started), serialize_timestamp(expires), serialize_timestamp(token_until),
                used, total, window, row['config']['credential_generation'],
                'offline' if self._offline else 'authenticated', secrets.token_hex(16), _token_binding(token))
            check()
            _PROOFS.add(proof)
            self.store.record_destination_readiness(self.destination_id, status='ready', reasons=[],
                facts=proof.facts(), valid_for=expires - utc_datetime_now(), preflight=proof)
            return proof
        except Exception:
            # A failed refresh revokes old readiness; never retain exception/provider text.
            self.store.record_destination_readiness(self.destination_id, status='blocked',
                reasons=['Instagram preflight failed closed'], facts={'kind': 'preflight_failure'})
            raise DeliveryConfigurationError("Instagram preflight failed closed") from None

    def _check(self, proof, *, allow_expired=False):
        row, config = _destination(self.store, self.destination_id)
        validate_proof(proof, row, moment=self.clock(), allow_expired=allow_expired)
        if row['enabled'] != 1 or config.enabled is not True:
            raise DeliveryConfigurationError("persistent Instagram delivery configuration is disabled")
        if not hmac.compare_digest(_token_binding(self.credentials.resolve(config)), proof._token_binding):
            raise DeliveryConfigurationError("credential changed; fresh preflight and activation required")
        ready = self.store.connection.execute(
            'SELECT status,facts_json,valid_until FROM capability_readiness WHERE social_destination_id=?',
            (self.destination_id,)).fetchone()
        if (ready['status'] != ('degraded' if self._offline else 'ready') or json.loads(ready['facts_json']) != json.loads(canonical(proof.facts()))
                or (not allow_expired and parse_timestamp(ready['valid_until']) <= self.clock())):
            raise DeliveryConfigurationError("preflight evidence was revoked or replaced")
        return row, config

    def activate(self, proof, *, post_record_id: int, command_id: str, confirm: bool = False):
        """Reserve quota and authorize one exact pending post, never start it."""
        if confirm is not True or not re.fullmatch(r'[A-Za-z0-9_-]{1,100}', command_id):
            raise DeliveryConfigurationError("separate explicit run approval is required")
        with self.store.transaction():
            row, _ = self._check(proof)
            context = self.store._post_delivery_context(post_record_id, moment=now())
            if (context['social_destination_id'] != self.destination_id or context['post_status'] != 'pending'
                    or context['delivery_revision_id'] is None):
                raise DeliveryConfigurationError("run activation requires this destination's exact pending JPEG post")
            # Reservations are conservative and survive crashes/restarts. No automatic
            # release or reuse; count the whole provider window, including newer snapshots.
            since = serialize_timestamp(self.clock() - timedelta(seconds=proof.quota_window_seconds))
            reserved = self.store.connection.execute(
                "SELECT COUNT(*) FROM human_command_receipts h JOIN post_records p ON p.post_record_id=h.result_record_id "
                "JOIN post_requests q ON q.post_request_id=p.post_request_id WHERE h.command_kind='instagram_run_activate' "
                "AND q.destination_key=? AND h.created_at>=?", (context['destination_key'], since)).fetchone()[0]
            if proof.quota_used + reserved >= proof.quota_total:
                raise DeliveryConfigurationError("Instagram quota is exhausted or reserved")
            if self.store.connection.execute(
                    "SELECT 1 FROM human_command_receipts WHERE command_kind='instagram_run_activate' AND result_record_id=?",
                    (post_record_id,)).fetchone():
                raise DeliveryConfigurationError("post already has a run activation; automatic reactivation refused")
            expiry = min(parse_timestamp(proof.valid_until), self.clock() + timedelta(minutes=2))
            binding = digest({'proof': proof.facts(), 'post': post_record_id,
                              'package': context['package_hash'], 'manifest': context['manifest_hash'],
                              'expires_at': serialize_timestamp(expiry)})
            self.store.connection.execute(
                "INSERT INTO human_command_receipts(command_id,command_kind,actor_id,payload_hash,result_record_id,created_at) "
                "VALUES (?,'instagram_run_activate','local_owner',?,?,?)", (command_id, binding, post_record_id, now()))
        activation = RunActivation(command_id, post_record_id, binding, serialize_timestamp(expiry),
                                   self.monotonic() + 120, proof, self)
        _ACTIVATIONS.add(activation)
        return activation

    def agent(self, activation, *, artifact_root):
        if type(activation) is not RunActivation or activation not in _ACTIVATIONS or activation._composition is not self:
            raise DeliveryConfigurationError("issued single-post run activation required")
        self._check(activation.proof)
        gate = _ActivatedAdapter(self, activation)
        return CredentialedPostingAgent(self.store, artifact_root=artifact_root, adapters={'instagram': gate},
                                        post_record_id=activation.post_record_id, start_guard=gate.check_start)


@dataclass(frozen=True, eq=False)
class RunActivation:
    command_id: str
    post_record_id: int
    binding: str
    expires_at: str
    start_deadline_monotonic: float
    proof: PreflightResult
    _composition: Any = field(repr=False)


class _ActivatedAdapter:
    def __init__(self, composition, activation):
        self.composition, self.activation = composition, activation
        self._attempt_id = None
        self._protocol = None
        self._publish_started = False
        self._context = None
        self._client = None
        self._proof = activation.proof
        self._started_monotonic = None
        self._last_wall = None
        self._last_monotonic = None
        self._deadline_at = None

    def check_start(self):
        c, a = self.composition, self.activation
        row = c.store.connection.execute('SELECT status FROM post_records WHERE post_record_id=?',
                                         (a.post_record_id,)).fetchone()
        if row is None or row['status'] not in {'pending', 'retry_wait'}:
            return False
        self._check_start_window()
        return True

    def _check_start_window(self):
        c, a = self.composition, self.activation
        c._check(a.proof)
        if c.clock() >= parse_timestamp(a.expires_at) or c.monotonic() >= a.start_deadline_monotonic:
            raise DeliveryConfigurationError("authorization-to-start expired; no new attempt may start")

    def _execution_guard(self):
        """Local checks also guard each read-only readiness refresh request."""
        c, a = self.composition, self.activation
        wall, elapsed = c.clock(), c.monotonic()
        if (elapsed < self._last_monotonic or wall < self._last_wall
                or elapsed - self._started_monotonic >= MAX_EXECUTION_SECONDS
                or wall >= parse_timestamp(self._deadline_at)):
            raise DeliveryError('stage_expired', 'bounded delivery execution expired; investigation required', False, 'instagram')
        self._last_wall, self._last_monotonic = wall, elapsed
        try:
            grant = c.store.renew_post_execution(self._context, require_fresh_readiness=False)
        except (RuntimeError, ValueError, OSError):
            raise DeliveryError('execution_fence', 'claim, approval or execution grant is no longer valid', False, 'instagram') from None
        if grant['activation_binding'] != a.binding or grant['deadline_at'] != self._deadline_at:
            raise DeliveryConfigurationError('durable execution grant changed')
        # Expiry may trigger authenticated refresh; revocation, replacement and
        # token/account/configuration changes never do.
        c._check(self._proof, allow_expired=True)

    def _guard(self):
        self._execution_guard()
        c = self.composition
        if parse_timestamp(self._proof.valid_until) <= c.clock() + timedelta(seconds=90):
            proof = c.preflight(before_request=self._execution_guard)
            if (proof.configuration_hash != self.activation.proof.configuration_hash
                    or not hmac.compare_digest(proof._token_binding, self.activation.proof._token_binding)):
                raise DeliveryConfigurationError('readiness refresh changed the authorized identity')
            self._proof = proof
        c._check(self._proof)
        c.store.renew_post_execution(self._context)

    def stage(self, context, record):
        c, a = self.composition, self.activation
        with c.store.transaction():
            self._check_start_window()
            row, config = c._check(a.proof)
            if (context['post_record_id'] != a.post_record_id or context['social_destination_id'] != c.destination_id
                    or context['provider_account_id'] != config.account_id
                    or context['destination_key'] != config.destination_key or context['destination_config'] != row['config']):
                raise DeliveryConfigurationError('run activation scope mismatch')
            c.store._check_post_resource_fence(context, context['post_attempt_id'], now())
            receipt = c.store.connection.execute(
                "SELECT * FROM human_command_receipts WHERE command_id=? AND command_kind='instagram_run_activate'",
                (a.command_id,)).fetchone()
            if receipt is None or receipt['payload_hash'] != a.binding or receipt['result_record_id'] != a.post_record_id:
                raise DeliveryConfigurationError('run activation audit is missing')
            started = c.clock()
            deadline = min(started + timedelta(seconds=MAX_EXECUTION_SECONDS),
                           parse_timestamp(a.proof.token_valid_until), parse_timestamp(context['expires_at']),
                           parse_timestamp(context['review_expires_at']))
            grant = {key: context[key] for key in ('post_record_id', 'claim_owner', 'claim_version',
                     'package_hash', 'manifest_hash', 'delivery_revision_id', 'provider_account_id', 'destination_key')}
            grant.update(activation_binding=a.binding, activation_command_id=a.command_id,
                         started_at=serialize_timestamp(started), deadline_at=serialize_timestamp(deadline),
                         configuration_hash=a.proof.configuration_hash, initial_evidence_id=a.proof.evidence_id)
            c.store.connection.execute(
                "INSERT INTO human_command_receipts(command_id,command_kind,actor_id,payload_hash,result_record_id,created_at) "
                "VALUES (?,'instagram_run_consume','local_owner',?,?,?)",
                (a.command_id + ':consume', a.binding, a.post_record_id, now()))
            c.store.connection.execute(
                "INSERT INTO publication_resources(post_attempt_id,resource_type,remote_id,status,safe_metadata_json,created_at,updated_at) "
                "VALUES (?,'instagram_run',?,'created',?,?,?)",
                (context['post_attempt_id'], a.command_id, canonical(grant), now(), now()))
        self._attempt_id, self._context = context['post_attempt_id'], context
        self._deadline_at = grant['deadline_at']
        self._started_monotonic = self._last_monotonic = c.monotonic()
        self._last_wall = started
        token = c.credentials.resolve(config)
        if not hmac.compare_digest(_token_binding(token), a.proof._token_binding):
            raise DeliveryConfigurationError('credential changed during composition; fresh preflight required')
        self._client = InstagramHTTPTransport(config, token, verified_version=config.api_version, wire=c._wire)
        relay = R2TransientRelay(c._relay_config, client=c._objects, transport=c._media_transport, before_io=self._guard)
        self._protocol = OfflineInstagramProtocol(self, relay, account_id=config.account_id,
                                                  sleep=self._wait, monotonic=c.monotonic)
        def guarded_record(**values):
            self._guard()
            return record(**values)
        return self._protocol.stage(context, guarded_record)

    def _wait(self, seconds):
        c = self.composition
        until = c.monotonic() + seconds
        while c.monotonic() < until:
            self._guard()
            before = c.monotonic()
            c.sleep(min(HEARTBEAT_SECONDS, until - before))
            if c.monotonic() <= before:
                raise DeliveryConfigurationError('polling clock did not advance')
        self._guard()

    def request(self, method, path, body):
        self._guard()
        return self._client.request(method, path, body)

    def check_before_final(self, context, staged):
        if context['post_attempt_id'] != self._attempt_id:
            raise DeliveryConfigurationError('run activation attempt mismatch')
        self._guard()

    def publish(self, context, staged):
        self.check_before_final(context, staged)
        row = self.composition.store.connection.execute(
            "SELECT status,final_publication_request_sent_at FROM post_attempts WHERE post_attempt_id=?",
            (self._attempt_id,)).fetchone()
        if self._publish_started or row is None or row['status'] != 'final_request_sent' or not row['final_publication_request_sent_at']:
            raise DeliveryConfigurationError('durable single final-send marker required')
        self._publish_started = True
        return self._protocol.publish(context, staged)


def validate_persisted_readiness(store, destination_id):
    """Used at review, Post now, attempt and final-marker boundaries."""
    row = store.connection.execute(
        'SELECT d.config_json,r.facts_json FROM social_destinations d JOIN capability_readiness r '
        'ON r.social_destination_id=d.social_destination_id WHERE d.social_destination_id=?',
        (destination_id,)).fetchone()
    if row is None or json.loads(row['config_json']).get('adapter_version') != ADAPTER_VERSION:
        return  # Preserved unimplemented/isolated simulation paths cannot compose a live adapter.
    facts = json.loads(row['facts_json'])
    if facts.get('provenance') == 'offline' and is_offline():
        return
    raise ValueError('trusted authenticated Instagram readiness is unavailable')


def is_registered_adapter(adapter):
    return type(adapter) is _ActivatedAdapter
