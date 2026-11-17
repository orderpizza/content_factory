"""Fail-closed, non-network Instagram Login configuration primitives.

Legacy observation helpers remain untrusted and offline-only. Registered adapter
composition and authenticated HTTP live in instagram_composition/instagram_http.
"""
from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from datetime import datetime, timezone
import re
from typing import Any

from common.timestamps import parse_timestamp
from .delivery import DeliveryConfigurationError, DeliveryError
from .offline import require_offline

VERSION = "v26.0"
PERMISSIONS = frozenset({"instagram_business_basic", "instagram_business_content_publish"})


@dataclass(frozen=True)
class InstagramLoginConfiguration:
    account_id: str
    destination_key: str
    token_ref: str
    login_mode: str = "instagram_login"
    api_version: str = VERSION
    schema_version: str = "instagram_login_config_v1"
    enabled: bool = False

    def validate(self) -> None:
        if (self.schema_version != "instagram_login_config_v1" or self.login_mode != "instagram_login"
                or self.api_version != VERSION or not re.fullmatch(r"[1-9][0-9]{0,29}", self.account_id)
                or not re.fullmatch(r"instagram:[A-Za-z0-9_-]{1,64}", self.destination_key)
                or self.token_ref != "DELIVERY_TOKEN" or type(self.enabled) is not bool):
            raise DeliveryConfigurationError("invalid Instagram Login configuration")


@dataclass(frozen=True)
class CapabilityObservation:
    """Untrusted caller observations. Never accepted by registered composition."""
    account_id: str
    login_mode: str
    api_version: str
    account_type: str
    permissions: frozenset[str]
    observed_at: str
    valid_until: str
    token_valid_until: str
    quota_used: int
    quota_total: int
    quota_window_seconds: int
    carousel_alt_verified: bool
    ai_label_verified: bool

    def validate(self, config: InstagramLoginConfiguration, *, moment: datetime) -> None:
        config.validate()
        if not isinstance(moment, datetime) or moment.tzinfo is None:
            raise DeliveryConfigurationError("readiness clock must include a timezone")
        try:
            observed, expires, token_expires = map(parse_timestamp,
                (self.observed_at, self.valid_until, self.token_valid_until))
        except (TypeError, ValueError) as error:
            raise DeliveryConfigurationError("invalid readiness timestamps") from error
        if (self.account_id != config.account_id or self.login_mode != config.login_mode
                or self.api_version != config.api_version or self.account_type not in {"BUSINESS", "CREATOR"}
                or self.permissions != PERMISSIONS or observed > moment or expires <= moment
                or token_expires <= moment or expires <= observed
                or type(self.quota_used) is not int or type(self.quota_total) is not int
                or type(self.quota_window_seconds) is not int or self.quota_used < 0
                or self.quota_total <= self.quota_used or self.quota_window_seconds <= 0
                or self.carousel_alt_verified is not True or self.ai_label_verified is not True):
            raise DeliveryConfigurationError("Instagram capability evidence is missing, mismatched, stale or exhausted")


@dataclass(frozen=True)
class ScopedToken:
    value: str = field(repr=False)

    def __post_init__(self):
        if not isinstance(self.value, str) or not re.fullmatch(r"[A-Za-z0-9_.|~-]{1,4096}", self.value):
            raise DeliveryConfigurationError("Instagram token is unavailable")

    @classmethod
    def resolve(cls, config: InstagramLoginConfiguration, secrets: Mapping[str, str]) -> "ScopedToken":
        config.validate()
        token = secrets.get(config.token_ref)
        if not isinstance(token, str) or not re.fullmatch(r"[A-Za-z0-9_.|~-]{1,4096}", token):
            raise DeliveryConfigurationError("Instagram token is unavailable")
        return cls(token)


class FixedHostInstagramExchange:
    """Legacy offline exchange fixture; never accepted by registered composition.

    The actual bounded client lives in instagram_http.InstagramHTTPTransport.
    """
    def __init__(self, config: InstagramLoginConfiguration, token: ScopedToken,
                 exchange: Callable[..., Mapping[str, Any]], *, run_approved: bool = False):
        require_offline()
        config.validate()
        self.config, self._token, self._exchange = config, token, exchange
        self._run_approved = run_approved

    def request(self, method: str, path: str, body: Mapping[str, Any]) -> Mapping[str, Any]:
        require_offline()
        if self.config.enabled is not True or self._run_approved is not True:
            raise DeliveryConfigurationError("Instagram exchange is disabled")
        if method not in {"GET", "POST"} or not re.fullmatch(r"/[1-9][0-9]{0,29}(?:/(?:media|media_publish|content_publishing_limit))?", path):
            raise DeliveryConfigurationError("Instagram request path is not allowed")
        target = path.split("/")[1]
        if "/" in path[1:] and target != self.config.account_id:
            raise DeliveryConfigurationError("Instagram account mismatch")
        try:
            response = self._exchange(method=method, url=f"https://graph.instagram.com/{self.config.api_version}{path}",
                                      headers={"Authorization": "Bearer " + self._token.value},
                                      parameters=dict(body), timeout=20)
        except Exception as error:
            raise DeliveryError("provider_transport", type(error).__name__, False, "instagram") from None
        if not isinstance(response, Mapping):
            raise DeliveryError("provider_response", "invalid provider response", False, "instagram")
        return response


class OfflineReadinessGate:
    """Gate fake provider journeys; observations are not real preflight evidence."""
    def __init__(self, adapter: Any, config: InstagramLoginConfiguration,
                 observation: CapabilityObservation, token: ScopedToken,
                 *, run_approved: bool = False, clock: Callable[[], datetime] | None = None):
        require_offline()
        self.adapter, self.config, self.observation = adapter, config, observation
        self._token, self.run_approved = token, run_approved
        self.clock = clock or (lambda: datetime.now(timezone.utc))

    def _check(self, context: Mapping[str, Any]) -> None:
        require_offline()
        if (self.config.enabled is not True or self.run_approved is not True
                or not isinstance(self._token, ScopedToken) or not self._token.value
                or context.get("provider_account_id") != self.config.account_id
                or context.get("destination_key") != self.config.destination_key):
            raise DeliveryConfigurationError("offline delivery gate is disabled or account mismatched")
        self.observation.validate(self.config, moment=self.clock())

    def stage(self, context: Mapping[str, Any], record: Callable[..., int]) -> Any:
        self._check(context)
        return self.adapter.stage(context, record)

    def check_before_final(self, context: Mapping[str, Any], staged: Any) -> None:
        self._check(context)

    def publish(self, context: Mapping[str, Any], staged: Any) -> str:
        self._check(context)
        return self.adapter.publish(context, staged)
