from dataclasses import replace
import json
import ssl
import time

import pytest

from workflow.delivery import DeliveryConfigurationError, DeliveryError
from workflow.instagram_http import InstagramHTTPTransport, HTTPReply, _https_once, bounded_https, _supervised_https
from workflow.instagram_readiness import InstagramLoginConfiguration, ScopedToken, VERSION
from workflow.offline import offline_only


@pytest.fixture
def config():
    return InstagramLoginConfiguration('123456', 'instagram:brand', 'DELIVERY_TOKEN')


def response(**changes):
    return replace(HTTPReply(200, {'facebook-api-version': VERSION, 'content-type': 'application/json'}, b'{"id":"42"}'), **changes)


def test_authenticated_request_redaction_and_single_attempt(config, caplog):
    with offline_only():
        calls = []
        def wire(*args):
            calls.append(args)
            raise TimeoutError('fixture-secret https://example.invalid/token')
        client = InstagramHTTPTransport(config, ScopedToken('fixture-secret'), verified_version=VERSION, wire=wire)
        with pytest.raises(DeliveryError) as error:
            client.request('POST', '/123456/media_publish', {'creation_id': '123'})
        assert len(calls) == 1 and calls[0][0] == 'POST'
        assert calls[0][1] == f'/{VERSION}/123456/media_publish'
        assert calls[0][2]['Authorization'] == 'Bearer fixture-secret'
        assert 'fixture-secret' not in str(error.value) + caplog.text
        assert error.value.retryable is False


@pytest.mark.parametrize('reply,category', [
    (response(status=302), 'redirect'),
    (response(headers={'location': 'https://evil.invalid'}), 'redirect'),
    (response(status=401), 'credentials'), (response(status=403), 'credentials'),
    (response(status=429), 'rate_limit'), (response(status=500), 'http_status'),
    (response(body=b'x' * 65537), 'response_limit'),
    (response(headers={'facebook-api-version': 'v27.0'}), 'api_version'),
    (response(headers={'content-type': 'application/json'}), 'api_version'),
    (response(headers={'facebook-api-version': VERSION, 'content-encoding': 'gzip'}), 'response_encoding'),
    (response(body=b'[]'), 'provider_response'), (response(body=b'{'), 'provider_response'),
    (response(body=b'{"error":{"message":"fixture-secret"}}'), 'provider_response'),
    (response(body=b'{"id":"fixture-secret"}'), 'provider_response'),
])
def test_response_bounds_versions_and_errors(config, reply, category):
    with offline_only():
        calls = []
        def wire(*args):
            calls.append(args[0])
            return reply
        client = InstagramHTTPTransport(config, ScopedToken('fixture-secret'), verified_version=VERSION, wire=wire)
        with pytest.raises(DeliveryError) as error:
            client.request('POST', '/123456/media', {'caption': 'exact caption'})
        assert error.value.category == category and error.value.retryable is False
        assert calls == ['POST']


@pytest.mark.parametrize('method,path,body', [
    ('POST', '/999/media', {}), ('GET', '//evil.invalid', {}), ('GET', '/me?access_token=x', {}),
    ('GET', 'https://evil.invalid/me', {}), ('PUT', '/123456/media', {}), ('POST', '/me', {}),
    ('GET', '/123456/media', {}), ('GET', '/me', {'access_token': 'secret'}),
    ('POST', '/123456/media', {'caption': 'x' * 40000}),
    ('GET', '/me', {'fields': 'fixture-secret'}),
])
def test_invalid_requests_never_reach_http(config, method, path, body):
    with offline_only():
        client = InstagramHTTPTransport(config, ScopedToken('fixture-secret'), verified_version=VERSION,
            wire=lambda *args: pytest.fail('invalid request reached HTTP'))
        with pytest.raises(DeliveryConfigurationError): client.request(method, path, body)


def test_fake_wire_cannot_escape_offline_and_live_is_unverified(config):
    with offline_only():
        client = InstagramHTTPTransport(config, ScopedToken('fixture-secret'), verified_version=VERSION,
                                        wire=lambda *args: response())
        assert client.request('GET', '/me', {}) == {'id': '42'}
    with pytest.raises(RuntimeError, match='offline'): client.request('GET', '/me', {})
    with pytest.raises(DeliveryConfigurationError, match='externally verified'):
        InstagramHTTPTransport(config, ScopedToken('fixture-secret'), verified_version=VERSION)
    with pytest.raises(DeliveryConfigurationError, match='version'):
        InstagramHTTPTransport(config, ScopedToken('fixture-secret'), verified_version='v27.0')


def test_tls_pinned_host_response_read_limit_and_no_redirect_following(monkeypatch):
    seen = []
    class Connection:
        def __init__(self, host, *, timeout, context):
            assert host == 'graph.instagram.com' and context.check_hostname
            assert context.verify_mode == ssl.CERT_REQUIRED
            seen.append(('connect', host))
        def set_debuglevel(self, level): assert level == 0
        def request(self, method, target, body, headers): seen.append(('request', target))
        def getresponse(self): return self
        status = 302
        def getheaders(self): return [('Location', 'https://evil.invalid')]
        def read(self, size):
            assert size == 1025
            return b'x' * size
        def close(self): seen.append(('close',))
    monkeypatch.setattr('workflow.instagram_http.http.client.HTTPSConnection', Connection)
    reply = _https_once('GET', '/v26.0/me', {}, None, 1, 1024)
    assert reply.status == 302 and len(reply.body) == 1025
    assert len(seen) == 3


def slow_child(pipe, args):
    time.sleep(5)  # killed by the parent; never opens a socket


def test_hard_deadline_kills_stalled_dns_tls_or_body_worker(monkeypatch):
    monkeypatch.setattr('workflow.instagram_http._child', slow_child)
    start = time.monotonic()
    with pytest.raises(DeliveryError, match='deadline'):
        _supervised_https('POST', '/v26.0/123456/media', {}, b'', .1, 1024)
    assert time.monotonic() - start < 2


def test_real_process_transport_cannot_be_injected_as_an_offline_wire(config):
    with offline_only():
        with pytest.raises(DeliveryConfigurationError, match='offline'):
            bounded_https('GET', '/v26.0/me', {}, None, 1, 1024)
        client = InstagramHTTPTransport(config, ScopedToken('fixture-secret'), verified_version=VERSION,
                                        wire=bounded_https)
        with pytest.raises(DeliveryError):
            client.request('GET', '/me', {})
    with pytest.raises(DeliveryConfigurationError, match='unverified'):
        bounded_https('GET', '/v26.0/me', {}, None, 1, 1024)
