"""Single-attempt authenticated Instagram HTTPS, with a hard wall-clock deadline.

No environment switches enable networking. Composition supplies a verified version;
this checkpoint has no verified live contract. Injected wires are offline-only.
"""
from __future__ import annotations

from dataclasses import dataclass, field
import http.client
import json
import multiprocessing
import ssl
import time
from typing import Any, Mapping
from urllib.parse import urlencode

from .delivery import DeliveryConfigurationError, DeliveryError
from .instagram_readiness import InstagramLoginConfiguration, ScopedToken
from .offline import require_offline, is_offline

HOST = "graph.instagram.com"
MAX_RESPONSE_BYTES = 64 * 1024
MAX_REQUEST_BYTES = 32 * 1024


@dataclass(frozen=True)
class HTTPReply:
    status: int
    headers: Mapping[str, str] = field(repr=False)
    body: bytes = field(repr=False)


def _https_once(method, target, headers, body, timeout, limit):
    """TLS verifies the pinned host; http.client neither redirects nor retries."""
    connection = http.client.HTTPSConnection(HOST, timeout=timeout,
                                             context=ssl.create_default_context())
    connection.set_debuglevel(0)
    try:
        connection.request(method, target, body=body, headers=headers)
        response = connection.getresponse()
        # Header count/line size are bounded by http.client; body is explicitly bounded.
        return HTTPReply(response.status, dict(response.getheaders()), response.read(limit + 1))
    finally:
        connection.close()


def _child(pipe, args):
    try:
        reply = _https_once(*args)
    except BaseException:
        # Never forward exception text, request headers, URLs or response bodies.
        reply = None
    try:
        pipe.send(reply)
    except (BrokenPipeError, OSError):
        # The deadline supervisor may already have closed its end; do not print
        # a child-process exception/response traceback to stderr.
        pass
    finally:
        pipe.close()


def bounded_https(method, target, headers, body, timeout, limit):
    # A caller must not smuggle the real process transport into an offline wire
    # slot: spawned processes do not inherit the parent's socket monkeypatches.
    if is_offline():
        raise DeliveryConfigurationError("live HTTPS is forbidden during offline integration")
    from .instagram_composition import VERIFIED_LIVE_CONTRACTS, CONTRACT_REF
    if CONTRACT_REF not in VERIFIED_LIVE_CONTRACTS:
        raise DeliveryConfigurationError("live HTTPS contract is unverified")
    return _supervised_https(method, target, headers, body, timeout, limit)


def _supervised_https(method, target, headers, body, timeout, limit):
    """Process isolation bounds DNS, TLS, headers and slow-body reads together.

    Socket inactivity timeouts alone do not enforce an overall deadline. On deadline
    the child is terminated; a POST is still potentially accepted and never replayed.
    Credentials travel only in memory/IPC, never command arguments or temp files.
    """
    context = multiprocessing.get_context("spawn")
    parent, child = context.Pipe(duplex=False)
    process = context.Process(target=_child, args=(child, (method, target, headers, body, timeout, limit)),
                              daemon=True)
    deadline = time.monotonic() + timeout
    try:
        process.start()
        child.close()
        if not parent.poll(max(0, deadline - time.monotonic())):
            raise DeliveryError("deadline", "Instagram request deadline exceeded", False, "instagram")
        reply = parent.recv()
        if reply is None or time.monotonic() > deadline:
            raise DeliveryError("transport", "Instagram request outcome unavailable", False, "instagram")
        return reply
    except DeliveryError:
        raise
    except Exception:
        raise DeliveryError("transport", "Instagram request outcome unavailable", False, "instagram") from None
    finally:
        parent.close()
        child.close()
        if process.pid is not None:
            if process.is_alive():
                process.kill()
            process.join()
        process.close()


class InstagramHTTPTransport:
    def __init__(self, config: InstagramLoginConfiguration, token: ScopedToken, *,
                 verified_version: str, wire=None, timeout: float = 20, response_limit: int = MAX_RESPONSE_BYTES):
        config.validate()
        if verified_version != config.api_version:
            raise DeliveryConfigurationError("API version has not been verified for this contract")
        if (type(timeout) not in {int, float} or not 0 < timeout <= 20
                or type(response_limit) is not int or not 0 < response_limit <= MAX_RESPONSE_BYTES):
            raise DeliveryConfigurationError("invalid HTTP bounds")
        if wire is not None:
            require_offline()
        else:
            from .instagram_composition import VERIFIED_LIVE_CONTRACTS, CONTRACT_REF
            if CONTRACT_REF not in VERIFIED_LIVE_CONTRACTS:
                raise DeliveryConfigurationError("live API version/contract has not been externally verified")
        self.config, self._token = config, token
        self._wire, self.timeout, self.response_limit = wire, timeout, response_limit

    def request(self, method: str, path: str, body: Mapping[str, Any]) -> Mapping[str, Any]:
        import re
        if self._wire is not None:
            require_offline()
        if (method not in {"GET", "POST"} or not re.fullmatch(
                r"/(?:me(?:/permissions)?|[1-9][0-9]{0,29}(?:/(?:media|media_publish|content_publishing_limit))?)", path)):
            raise DeliveryConfigurationError("Instagram method/path is not allowed")
        if path.endswith(("/media", "/media_publish", "/content_publishing_limit")) and path.split('/')[1] != self.config.account_id:
            raise DeliveryConfigurationError("Instagram account mismatch")
        if ((method == "POST") != path.endswith(("/media", "/media_publish"))):
            raise DeliveryConfigurationError("Instagram method/path mismatch")
        if (not isinstance(body, Mapping) or any(not isinstance(k, str) or
                k.casefold() in {"access_token", "input_token", "authorization", "appsecret_proof"} for k in body)
                or any(type(v) not in {str, int, bool} for v in body.values())):
            raise DeliveryConfigurationError("invalid Instagram request parameters")
        if any(self._token.value in str(value) for pair in body.items() for value in pair):
            raise DeliveryConfigurationError("credential is forbidden in request parameters")
        encoded = urlencode({k: str(v).lower() if type(v) is bool else v for k, v in body.items()}).encode()
        if len(encoded) > MAX_REQUEST_BYTES or self._token.value.encode() in encoded:
            raise DeliveryConfigurationError("invalid Instagram request size or credential location")
        target = f"/{self.config.api_version}{path}"
        payload = encoded if method == "POST" else None
        if method == "GET" and encoded:
            target += "?" + encoded.decode("ascii")
        headers = {"Authorization": "Bearer " + self._token.value,
                   "Content-Type": "application/x-www-form-urlencoded", "Accept": "application/json",
                   "Accept-Encoding": "identity", "User-Agent": "content-factory/instagram-checkpoint-1"}
        try:
            reply = (self._wire or bounded_https)(method, target, headers, payload,
                                                  self.timeout, self.response_limit)
        except DeliveryError as error:
            category = error.category if error.category in {"deadline", "transport"} else "transport"
            raise DeliveryError(category, "Instagram request outcome unavailable", False, "instagram") from None
        except Exception:
            raise DeliveryError("transport", "Instagram request outcome unavailable", False, "instagram") from None
        lower = {k.lower(): v for k, v in reply.headers.items()}
        category = None
        if 300 <= reply.status < 400 or "location" in lower:
            category = "redirect"
        elif reply.status in {401, 403}:
            category = "credentials"
        elif reply.status == 429:
            category = "rate_limit"
        elif reply.status != 200:
            category = "http_status"
        elif len(reply.body) > self.response_limit:
            category = "response_limit"
        elif lower.get("content-encoding", "identity") != "identity":
            category = "response_encoding"
        elif lower.get("facebook-api-version") != self.config.api_version:
            category = "api_version"
        elif lower.get("content-type", "").split(";", 1)[0] != "application/json":
            category = "response_type"
        if category:
            raise DeliveryError(category, "Instagram response refused", False, "instagram")
        try:
            value = json.loads(reply.body)
            if not isinstance(value, dict) or "error" in value or self._token.value in reply.body.decode():
                raise ValueError()
        except (ValueError, UnicodeError):
            raise DeliveryError("provider_response", "Instagram response refused", False, "instagram") from None
        return value
