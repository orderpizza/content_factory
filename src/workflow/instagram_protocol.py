"""Offline Instagram Login protocol model; never registered with the live worker.

The injected transport and relay are deliberately required: this module supplies no
network implementation or production activation path. See the posting contract for
remaining account-specific verification and recovery work.
"""
from __future__ import annotations

from collections.abc import Callable, Mapping
import re
import time
from typing import Any, Protocol

from .delivery import DeliveryError, _r2_object_key


class Transport(Protocol):
    def request(self, method: str, path: str, body: Mapping[str, Any]) -> Mapping[str, Any]: ...



def _id(value: Any) -> str:
    if not isinstance(value, str) or not re.fullmatch(r"[0-9]{1,30}", value):
        raise DeliveryError("provider_response", "invalid provider identity", False, "instagram")
    return value


class OfflineInstagramProtocol:
    """Exercise request sequencing with injected fakes; not a production adapter."""

    def __init__(self, transport: Transport, relay: Any, *, account_id: str,
                 max_polls: int = 5, sleep: Callable[[float], None] = time.sleep,
                 monotonic: Callable[[], float] = time.monotonic):
        self.transport, self.relay = transport, relay
        self.account_id = _id(account_id)
        if self.account_id == "0" or type(max_polls) is not int or not 1 <= max_polls <= 5:
            raise ValueError("invalid offline account or polling bound")
        self.max_polls, self.sleep, self.monotonic = max_polls, sleep, monotonic

    def _request(self, method: str, path: str, body: Mapping[str, Any]) -> Mapping[str, Any]:
        try:
            response = self.transport.request(method, path, body)
        except DeliveryError as error:
            raise DeliveryError(error.category, "Instagram request refused", False, "instagram") from None
        except Exception as error:
            # Provider exceptions may include tokens, captions, or public media URLs.
            raise DeliveryError("provider_transport", type(error).__name__, False, "instagram") from None
        if not isinstance(response, Mapping) or "error" in response:
            raise DeliveryError("provider_response", "provider request failed", False, "instagram")
        return response

    def _ready(self, container: str) -> None:
        # Five reads, at least sixty seconds between request starts, and a hard
        # five-minute elapsed bound per container (including HTTP/waits).
        deadline = self.monotonic() + 300
        next_poll = self.monotonic()
        for attempt in range(self.max_polls):
            delay = next_poll - self.monotonic()
            if delay > 0:
                self.sleep(delay)
            started = self.monotonic()
            if started >= deadline or started < next_poll:
                raise DeliveryError("container_timeout", "container polling deadline reached", False, "instagram")
            response = self._request("GET", f"/{container}", {"fields": "status_code"})
            if self.monotonic() >= deadline:
                raise DeliveryError("container_timeout", "container polling deadline reached", False, "instagram")
            status = response.get("status_code")
            if status == "FINISHED":
                return
            if status != "IN_PROGRESS":
                raise DeliveryError("container_status", "container is not eligible", False, "instagram")
            # Wait from the completed response: request admission may itself
            # refresh readiness. Its latency must not shorten the interval
            # between actual provider requests.
            next_poll = self.monotonic() + 60
        raise DeliveryError("container_timeout", "container polling limit reached", False, "instagram")

    def stage(self, context: Mapping[str, Any], record: Callable[..., int]) -> dict[str, str]:
        if (context.get("provider_account_id") != self.account_id
                or context.get("platform") != "instagram"
                or context.get("delivery_revision_id") is None
                or context.get("package", {}).get("execution_mode") == "simulation"):
            raise DeliveryError("validation", "account or reviewed revision mismatch", False, "instagram")
        assets = context["assets"]
        package = context["package"]
        descriptions = package.get("image_alt_text")
        if (not 4 <= len(assets) <= 6 or [a["ordinal"] for a in assets] != list(range(1, len(assets) + 1))
                or not isinstance(descriptions, list) or len(descriptions) != len(assets)
                or any(not isinstance(x, str) or not x or len(x) > 1000 for x in descriptions)
                or any(a.get("alt_text") != alt for a, alt in zip(assets, descriptions))
                or not isinstance(package.get("caption"), str) or len(package["caption"]) > 2200):
            raise DeliveryError("validation", "invalid reviewed carousel inputs", False, "instagram")
        children = []
        for asset, alt in zip(assets, descriptions):
            key = _r2_object_key(context, asset)
            identity = self.relay.identity(context, asset, key) if context.get('destination_config', {}).get('adapter_version') == 'instagram_login_v1' else None
            resource = record(resource_type="r2_object", remote_id=key, asset_ordinal=asset["ordinal"],
                              safe_metadata={"sha256": asset["sha256"], "retention": "manual_ingestion_safety",
                                             **({'identity': identity, 'lifecycle': 'r2_lifecycle_v1', 'provenance': 'offline'} if identity else {})})
            _, url = self.relay.stage(context, asset, key=key)
            record(resource_id=resource, status="ready")
            if identity:
                record(resource_type='r2_staged', remote_id=key, asset_ordinal=asset['ordinal'],
                       safe_metadata={'identity': identity, 'completed_io': True})
            # This intent is evidence of a potentially accepted create, even if
            # the reply or subsequent persistence is lost. It is not a child ID.
            record(resource_type="instagram_create_intent", remote_id=f"child:{asset['ordinal']}",
                   asset_ordinal=asset["ordinal"], safe_metadata={"sha256": asset["sha256"],
                       **({'r2_resource_id': resource, 'object_key': key} if identity else {})})
            child = _id(self._request("POST", f"/{self.account_id}/media", {
                "image_url": url, "is_carousel_item": True, "alt_text": alt,
            }).get("id"))
            record(resource_type="external_media", remote_id=child, asset_ordinal=asset["ordinal"],
                   safe_metadata={"kind": "child", "sha256": asset["sha256"]})
            self._ready(child)
            children.append(child)
        record(resource_type="instagram_create_intent", remote_id="parent", safe_metadata={"kind": "parent"})
        parent = _id(self._request("POST", f"/{self.account_id}/media", {
            "media_type": "CAROUSEL", "children": ",".join(children), "caption": package["caption"],
        }).get("id"))
        record(resource_type="external_media", remote_id=parent, safe_metadata={"kind": "parent"})
        self._ready(parent)
        return {"parent": parent}

    def publish(self, context: Mapping[str, Any], staged: Mapping[str, str]) -> str:
        if context.get("provider_account_id") != self.account_id:
            raise DeliveryError("validation", "account mismatch", False, "instagram")
        parent = _id(staged["parent"])
        media = _id(self._request("POST", f"/{self.account_id}/media_publish", {
            "creation_id": parent,
        }).get("id"))
        return media
