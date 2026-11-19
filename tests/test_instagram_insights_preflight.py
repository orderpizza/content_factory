"""Drive the operator entrypoint, replacing the terminal, secret store and HTTPS connection only."""
from contextlib import redirect_stdout
from functools import partial
import hashlib
import io
import json
import multiprocessing
from pathlib import Path
import secrets
import socket
import sqlite3
import ssl
import sys
import time
from types import SimpleNamespace

from unittest.mock import patch

import pytest

from scripts import instagram_insights_preflight as cli


class Terminal(io.StringIO):
    def isatty(self):
        return True


class FakeHTTPS:
    """Picklable fake connection for the real spawned worker. Send scrubbed observations only."""

    def __init__(self, scenario, events, host, *, context, timeout):
        self.scenario = scenario
        self.events = events
        self.status = scenario.status
        events.send(('connect', (host, context.check_hostname, context.verify_mode,
                                 context.keylog_filename, timeout)))

    def set_debuglevel(self, level):
        assert level == 0

    def request(self, method, target, *, headers):
        assert headers == {'Authorization': 'Bearer ' + self.scenario.token,
                           'Accept': 'application/json', 'Accept-Encoding': 'identity'}
        self.events.send(('request', (method, target)))
        if self.scenario.error:
            raise self.scenario.error

    def getresponse(self):
        return self

    def getheaders(self):
        return self.scenario.headers

    def read(self, size):
        self.events.send(('read', size))
        if self.scenario.stall:
            time.sleep(60)
        return self.scenario.body[:size]

    def close(self):
        self.events.send(('close', 1))


class Harness:
    def __init__(self, monkeypatch):
        self.token = secrets.token_urlsafe(32)
        self.binding = dict(destination_id='7', app_id='101', account_id='202', credential_revision='a' * 32)
        self.args = [item for key, value in self.binding.items() for item in ('--' + key.replace('_', '-'), value)]
        self.args += ['--max-gets', '1']
        self.record = dict(self.binding, login=cli.LOGIN, token_type='bearer', access_token=self.token,
                           permissions=list(cli.SCOPES), issued_at=int(time.time()), expires_at=int(time.time()) + 3600)
        self.env = {}
        self.connections = []
        self.requests = []
        self.read_sizes = []
        self.headers = [('Facebook-API-Version', 'v27.0'), ('Content-Type', 'application/json')]
        self.status = 200
        self.row = {'user_id': '202', 'account_type': 'BUSINESS'}
        self.body = json.dumps({'data': [self.row]}).encode()
        self.output = Terminal()
        self.answer = None
        self.last_challenge = None
        self.error = None
        self.closed = 0
        self.stall = False
        self.terminal = Terminal()
        monkeypatch.setattr(self.terminal, 'readline', self.confirm)
        monkeypatch.setattr(cli, 'os', SimpleNamespace(environ=self.env))
        monkeypatch.setattr(cli.http.client, 'HTTPSConnection', self.unexpected)
        monkeypatch.setattr(socket, 'getaddrinfo', self.unexpected)
        monkeypatch.setattr(socket.socket, 'connect', self.unexpected)
        monkeypatch.setattr(sqlite3, 'connect', self.unexpected)

    def unexpected(self, *args, **kwargs):
        pytest.fail('unexpected real network, database or credential access')

    def confirm(self, size):
        challenge = self.output.getvalue().splitlines()[-1].split('Type exactly: ')[1]
        self.last_challenge = challenge
        answer = challenge if self.answer is None else self.answer
        return answer + '\n'

    def run(self, args):
        self.output.seek(0)
        self.output.truncate()
        receiver, sender = multiprocessing.Pipe(duplex=False)
        scenario = SimpleNamespace(token=self.token, status=self.status, headers=self.headers,
                                   body=self.body, error=self.error, stall=self.stall)
        try:
            with (redirect_stdout(self.output), patch.object(sys, 'stdin', self.terminal),
                  patch.object(cli.http.client, 'HTTPSConnection', partial(FakeHTTPS, scenario, sender))):
                code = cli.main(args)
            while receiver.poll():
                event, value = receiver.recv()
                if event == 'connect':
                    self.connections.append(value)
                elif event == 'request':
                    self.requests.append(value)
                elif event == 'read':
                    self.read_sizes.append(value)
                elif event == 'close':
                    self.closed += value
        finally:
            sender.close()
            receiver.close()
        text = self.output.getvalue()
        assert self.token not in text
        assert 'private-diagnostic' not in text
        return code, json.loads(text.splitlines()[-1])

    def live(self):
        code, preview = self.run(self.args)
        assert code == 0
        self.env[cli.CREDENTIAL_ENV] = json.dumps(self.record)
        return self.run(self.args + ['--execute', '--confirm-reviewed-plan', preview['plan_sha256']])


@pytest.fixture
def h(monkeypatch):
    return Harness(monkeypatch)


def test_unconfigured_and_bound_previews_are_pure(h, monkeypatch):
    monkeypatch.setattr(cli, 'record_token', h.unexpected)
    for args in ([], h.args):
        code, preview = h.run(args)
        assert code == 0 and preview['mode'] == 'dry_run'
        assert preview['plan']['requests'] == [{
            'category': 'identity', 'method': 'GET',
            'url': 'https://graph.instagram.com/v27.0/me?fields=user_id,account_type',
        }]
    assert not h.connections


def test_requires_reviewed_bound_plan_explicit_cap_and_live_terminal(h, monkeypatch):
    monkeypatch.setattr(cli, 'record_token', h.unexpected)
    digest = h.run(h.args)[1]['plan_sha256']
    confirm = ['--confirm-reviewed-plan', digest]
    for args in [h.args + confirm, h.args + ['--execute'], ['--execute'] + confirm,
                 h.args[:-2] + ['--execute'] + confirm, h.args + ['--max-gets', '2'],
                 h.args + ['--account-id', '203', '--execute'] + confirm,
                 h.args + ['--account-id', 'https://example.invalid'],
                 h.args + ['--execute', '--confirm-reviewed-plan', '0' * 64]]:
        assert h.run(args)[0] == 2
    monkeypatch.setattr(h.terminal, 'isatty', lambda: False)
    assert h.run(h.args + ['--execute'] + confirm)[1]['reason'] == 'owner_terminal_required'
    assert not h.connections


@pytest.mark.parametrize('field,value,reason', [
    ('destination_id', '1', 'credential_binding'), ('app_id', '303', 'credential_binding'),
    ('account_id', '303', 'credential_binding'), ('login', 'facebook_login', 'credential_binding'),
    ('credential_revision', 'b' * 32, 'credential_binding'), ('token_type', 'app', 'credential_type'),
    ('issued_at', 1, 'stale_grant_record'), ('issued_at', 9999999999, 'stale_grant_record'),
    ('expires_at', 1, 'credential_expired'), ('permissions', [], 'credential_grants'),
    ('permissions', [cli.SCOPES[0]] * 2, 'credential_grants'),
    ('permissions', [*cli.SCOPES, 'instagram_business_content_publish'], 'credential_grants'),
    ('permissions', [cli.SCOPES[0], {'scope': cli.SCOPES[1], 'status': 'declined'}], 'credential_grants'),
    ('access_token', 'invalid\r\nheader', 'credential_record'),
])
def test_refuses_ineligible_credential_before_http(h, field, value, reason):
    h.record[field] = value
    code, result = h.live()
    assert code == 2 and result['reason'] == reason
    assert result['provisioning_record'] == 'fail'
    assert not h.connections and result['attempted_gets'] == 0


@pytest.mark.parametrize('wrapped', [True, False])
def test_identity_uses_verified_tls_fixed_get_and_stops_with_unknown_current_grants(h, wrapped):
    h.row['account_type'] = 'Media_Creator'
    h.body = json.dumps({'data': [h.row]} if wrapped else h.row).encode()
    code, result = h.live()
    assert code == 0 and result['status'] == 'identity_candidate'
    assert result['expected_binding'] == h.binding and result['account_binding'] == 'pass'
    assert result['token_valid_for_identity'] == 'pass' and result['current_insights_permission'] == 'unknown'
    assert result['metric_support'] == 'not_requested' and result['reason'] == 'current_grants_unverified'
    assert result['response_version'] == 'v27.0' and result['response_type'] == 'application/json'
    assert result['response_sha256'] == hashlib.sha256(h.body).hexdigest()
    assert h.requests == [('GET', '/v27.0/me?fields=user_id,account_type')]
    [(host, check_hostname, verify_mode, keylog, timeout)] = h.connections
    assert host == 'graph.instagram.com' and timeout == cli.SOCKET_SECONDS
    assert check_hostname and verify_mode == ssl.CERT_REQUIRED and not keylog
    assert h.read_sizes == [cli.BODY_BYTES + 1] and h.closed == 1


def test_one_shot_confirmation_and_rotation(h):
    assert h.live()[0] == 0
    h.answer = h.last_challenge
    assert h.live()[1]['reason'] == 'confirmation_refused'
    assert h.last_challenge != h.answer and len(h.requests) == 1
    h.answer = None
    h.record['credential_revision'] = 'b' * 32
    assert h.live()[1]['reason'] == 'credential_binding'
    h.args[h.args.index('a' * 32)] = h.record['credential_revision']
    h.token = h.record['access_token'] = secrets.token_urlsafe(32)
    assert h.live()[0] == 0 and len(h.requests) == 2


def test_confirmation_expires_before_secret_resolution(h, monkeypatch):
    ticks = iter([0, cli.CONFIRM_SECONDS])
    monkeypatch.setattr(cli, 'time', SimpleNamespace(monotonic=lambda: next(ticks)))
    monkeypatch.setattr(cli, 'record_token', h.unexpected)
    assert h.live()[1]['reason'] == 'confirmation_refused'
    assert not h.connections


@pytest.mark.parametrize('status,reason', [(301, 'redirect'), (401, 'invalid_token'),
                                          (403, 'identity_denied'), (429, 'rate_limit'), (502, 'provider_failure')])
def test_http_refusals_never_retry_or_read_error_message(h, status, reason):
    h.status = status
    h.body = h.token.encode()
    code, result = h.live()
    assert code == 2 and result['reason'] == reason
    assert not h.read_sizes and len(h.requests) == h.closed == 1


@pytest.mark.parametrize('error_code,reason', [(190, 'invalid_token'), (80002, 'rate_limit'),
                                              (200, 'identity_denied'), (999, 'provider_error')])
def test_provider_errors_redacted(h, capfd, error_code, reason):
    h.status = 400
    h.body = json.dumps({'error': {'code': error_code, 'message': h.token}}).encode()
    assert h.live()[1]['reason'] == reason
    assert h.token not in capfd.readouterr().err and len(h.requests) == 1


@pytest.mark.parametrize('body,reason', [
    (b'{', 'malformed_json'), (b'{"id":"1","id":"2"}', 'malformed_json'),
    (b'{}', 'response_shape'), (b'{"data":[]}', 'response_shape'),
    (b'{"data":[{},{}]}', 'response_shape'),
    (b'{"data":[],"paging":{"next":"https://other.invalid"}}', 'response_shape'),
    (b'{"user_id":"203","account_type":"BUSINESS"}', 'account_mismatch'),
    (b'{"user_id":"202","account_type":"PERSONAL"}', 'not_professional'),
    pytest.param(b' ' * (cli.BODY_BYTES + 1), 'response_limit', id='oversized-body'),
])
def test_invalid_identity_response_stops(h, body, reason):
    h.body = body
    code, result = h.live()
    assert code == 2 and result['reason'] == reason
    assert len(h.requests) == 1 and h.read_sizes == [cli.BODY_BYTES + 1]


@pytest.mark.parametrize('key,value,reason', [
    ('Location', 'https://private-diagnostic.invalid/', 'redirect'),
    ('Content-Length', '9999999', 'response_limit'),
    ('Content-Length', '9', 'response_framing'),
    ('Content-Encoding', 'gzip', 'response_encoding'),
    ('Content-Type', 'text/html', 'response_type'),
    ('Facebook-API-Version', 'v26.0', 'response_version'),
    pytest.param('X-Private', 'x' * cli.HEADER_BYTES, 'response_limit', id='oversized-headers'),
])
def test_rejects_unsafe_headers(h, key, value, reason):
    h.headers = [pair for pair in h.headers if pair[0] != key] + [(key, value)]
    assert h.live()[1]['reason'] == reason
    assert len(h.requests) == h.closed == 1


def test_missing_and_duplicate_version(h):
    h.headers.append(('facebook-api-version', 'v27.0'))
    assert h.live()[1]['reason'] == 'ambiguous_headers'
    h.headers = [('Content-Type', 'application/json')]
    assert h.live()[1]['reason'] == 'response_version'


@pytest.mark.parametrize('exception,reason', [(TimeoutError, 'deadline'), (OSError, 'execution_error')])
def test_wire_exception_cannot_leak_secret(h, capfd, exception, reason):
    h.error = exception(h.token)
    assert h.live()[1]['reason'] == reason
    assert h.token not in capfd.readouterr().err and h.closed == 1


def test_wall_deadline_terminates_stalled_worker(h, monkeypatch):
    monkeypatch.setattr(cli, 'TOTAL_SECONDS', 2)
    h.stall = True
    started = time.monotonic()
    assert h.live()[1]['reason'] == 'deadline'
    assert 1.9 <= time.monotonic() - started < 5
    assert h.read_sizes == [cli.BODY_BYTES + 1]
    assert not multiprocessing.active_children()


def test_rejects_url_method_and_token_arguments_without_echo(h, capsys):
    for option in ('--url', '--method', '--token', '--host', '--version', '--login'):
        with pytest.raises(SystemExit):
            cli.main([option, h.token])
        assert capsys.readouterr().err == 'Invalid preflight arguments. See --help.\n'
    assert not h.connections


@pytest.mark.parametrize('raw,reason', [
    (b'HTTP/1.1 200 OK\r\nX: ' + b'x' * cli.HEADER_BYTES, 'response_limit'),
    ((b'HTTP/1.1 100 Continue\r\nX: ' + b'x' * 256 + b'\r\n\r\n') * 100, 'response_limit'),
    (b'HTTP/1.1 200 OK\r\nContent-Type: application/json\r\nFacebook-API-Version: v27.0\r\n'
     b'Transfer-Encoding: chunked\r\n\r\n1;ext=' + b'x' * cli.HEADER_BYTES, 'response_limit'),
    (b'HTTP/1.1 301 Moved\r\nLocation: https://other.invalid/\r\n\r\n', 'redirect'),
], ids=['long-line', 'interim-flood', 'chunk-framing', 'redirect'])
def test_real_http_parser_is_bounded_before_body_decoding(raw, reason):
    stream = io.BytesIO(raw)
    response = cli._BoundedResponse(SimpleNamespace(makefile=lambda _: stream), method='GET')
    with pytest.raises(cli.Stop, match=reason):
        response.begin()
        cli.inspect_reply(response, '202', cli.Result())
    assert stream.tell() <= cli.HEADER_BYTES + 1
    response.close()


def test_real_http_parser_reads_chunked_identity_document():
    body = b'{"user_id":"202","account_type":"Business"}'
    raw = (b'HTTP/1.1 200 OK\r\nContent-Type: application/json\r\nFacebook-API-Version: v27.0\r\n'
           b'Transfer-Encoding: chunked\r\n\r\n' + format(len(body), 'x').encode() + b'\r\n' + body + b'\r\n0\r\n\r\n')
    response = cli._BoundedResponse(SimpleNamespace(makefile=lambda _: io.BytesIO(raw)), method='GET')
    response.begin()
    result = cli.Result()
    cli.inspect_reply(response, '202', result)
    assert result.account_binding == 'pass' and result.response_sha256 == hashlib.sha256(body).hexdigest()
    response.close()


def test_identity_report_leaves_workspace_and_v20_history_intact(h, tmp_path, monkeypatch):
    schema = (Path(__file__).resolve().parents[1] / 'docs/contracts/application-schema.sql').read_text()
    data = tmp_path / 'data'
    data.mkdir()
    database = data / 'db_20260101000000.db'
    connection = sqlite3.Connection(database)
    try:
        connection.executescript(schema)
        assert connection.execute('PRAGMA user_version').fetchone() == (20,)
        assert connection.execute('SELECT COUNT(*) FROM measurement_observations').fetchone() == (0,)
    finally:
        connection.close()
    before = database.read_bytes()
    monkeypatch.chdir(tmp_path)
    assert h.live()[0] == 0
    assert set(tmp_path.rglob('*')) == {data, database}
    assert database.read_bytes() == before
