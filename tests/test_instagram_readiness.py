from dataclasses import replace
from datetime import datetime, timezone

import pytest

from workflow.delivery import DeliveryConfigurationError, DeliveryError
from workflow.instagram_readiness import (CapabilityObservation, FixedHostInstagramExchange,
    InstagramLoginConfiguration, PERMISSIONS, ScopedToken)
from workflow.offline import offline_only


@pytest.fixture(autouse=True)
def no_network():
    with offline_only():
        yield


@pytest.fixture
def configuration():
    return InstagramLoginConfiguration("123", "instagram:brand", "DELIVERY_TOKEN")


@pytest.fixture
def observation():
    return CapabilityObservation("123", "instagram_login", "v26.0", "BUSINESS", PERMISSIONS,
        "2026-11-17T09:00:00", "2026-11-17T11:00:00", "2026-12-17T00:00:00", 3, 20, 86400, True, True)


def test_capability_must_be_current_and_scoped(configuration, observation):
    moment = datetime(2026, 11, 17, 10, tzinfo=timezone.utc)
    observation.validate(configuration, moment=moment)
    for change in ({"account_id": "124"}, {"login_mode": "facebook"}, {"api_version": "v27.0"},
                   {"permissions": frozenset()}, {"valid_until": "2026-11-17T09:59:59"},
                   {"quota_used": 20}, {"carousel_alt_verified": False}, {"ai_label_verified": False}):
        with pytest.raises(DeliveryConfigurationError):
            replace(observation, **change).validate(configuration, moment=moment)


def test_token_is_scoped_and_redacted(configuration):
    with pytest.raises(DeliveryConfigurationError):
        ScopedToken.resolve(configuration, {})
    with pytest.raises(DeliveryConfigurationError):
        ScopedToken.resolve(configuration, {"DELIVERY_TOKEN": "bad\nheader"})
    token = ScopedToken.resolve(configuration, {"DELIVERY_TOKEN": "secret-test-token"})
    assert "secret-test-token" not in repr(token)
    with pytest.raises(DeliveryConfigurationError):
        ScopedToken.resolve(replace(configuration, token_ref="OTHER"), {"OTHER": "x"})


def test_fixed_host_version_and_diagnostic_redaction(configuration):
    sent = []
    token = ScopedToken.resolve(configuration, {"DELIVERY_TOKEN": "secret-test-token"})
    def exchange(**request):
        sent.append(request)
        return {"id": "42"}
    client = FixedHostInstagramExchange(configuration, token, exchange)
    with pytest.raises(DeliveryConfigurationError):
        client.request("GET", "/123", {})
    client = FixedHostInstagramExchange(replace(configuration, enabled=True), token, exchange, run_approved=True)
    assert client.request("POST", "/123/media", {"caption": "reviewed"}) == {"id": "42"}
    assert sent[0]["url"] == "https://graph.instagram.com/v26.0/123/media"
    for path in ("/999/media", "//evil.test", "/123/media?access_token=x", "/123/other"):
        with pytest.raises(DeliveryConfigurationError):
            client.request("POST", path, {})
    client = FixedHostInstagramExchange(replace(configuration, enabled=True), token,
        lambda **kwargs: (_ for _ in ()).throw(TimeoutError("secret-test-token https://secret.example")),
        run_approved=True)
    with pytest.raises(DeliveryError) as error:
        client.request("GET", "/123", {})
    assert "secret" not in str(error.value)


def test_offline_gate_requires_two_opt_ins_and_rechecks_expiry(configuration, observation):
    from workflow.instagram_readiness import OfflineReadinessGate
    class Adapter:
        def stage(self, context, record):
            return "staged"
        def publish(self, context, staged):
            return "42"
    context = {"provider_account_id": "123", "destination_key": "instagram:brand"}
    token = ScopedToken.resolve(configuration, {"DELIVERY_TOKEN": "test-token"})
    clock = lambda: datetime(2026, 11, 17, 10, tzinfo=timezone.utc)
    gate = OfflineReadinessGate(Adapter(), configuration, observation, token, run_approved=True, clock=clock)
    with pytest.raises(DeliveryConfigurationError):
        gate.stage(context, lambda **kw: None)
    gate = OfflineReadinessGate(Adapter(), replace(configuration, enabled=True), observation,
                                token, run_approved=False, clock=clock)
    with pytest.raises(DeliveryConfigurationError):
        gate.stage(context, lambda **kw: None)
    gate.run_approved = True
    assert gate.stage(context, lambda **kw: None) == "staged"
    gate.clock = lambda: datetime(2026, 11, 17, 12, tzinfo=timezone.utc)
    with pytest.raises(DeliveryConfigurationError):
        gate.check_before_final(context, "staged")
