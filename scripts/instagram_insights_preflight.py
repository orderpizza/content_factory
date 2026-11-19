"""Owner-operated Instagram Login identity preflight. Running without flags only prints the plan."""
import argparse
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import hashlib
import hmac
import http.client
import json
import multiprocessing
import os
import re
import secrets
import ssl
import sys
import time

HOST = 'graph.instagram.com'
VERSION = 'v27.0'
LOGIN = 'instagram_login'
TARGET = f'/{VERSION}/me?fields=user_id,account_type'
SCOPES = ('instagram_business_basic', 'instagram_business_manage_insights')
CREDENTIAL_ENV = 'CONTENT_FACTORY_IG_PREFLIGHT_RECORD'
SOCKET_SECONDS = 3
TOTAL_SECONDS = 8
BODY_BYTES = 16 * 1024
HEADER_BYTES = 16 * 1024
CONFIRM_SECONDS = 120
GRANT_AGE_SECONDS = 3600


class Stop(Exception):
    """Only fixed local categories may cross the output boundary."""


class Parser(argparse.ArgumentParser):
    def error(self, message):
        # argparse's default echoes unknown arguments and invalid values.
        self.exit(2, 'Invalid preflight arguments. See --help.\n')


def unique_object(pairs):
    obj = dict(pairs)
    if len(obj) != len(pairs):
        raise ValueError('duplicate field')
    return obj


def plan_for(args):
    binding = {}
    for name in ('destination_id', 'account_id', 'app_id', 'credential_revision'):
        value = getattr(args, name)
        pattern = r'[0-9a-f]{32}' if name == 'credential_revision' else r'[1-9][0-9]{0,29}'
        if value is not None and not re.fullmatch(pattern, value):
            raise Stop('invalid_binding')
        binding[name] = value
    if args.max_gets not in (None, '1'):
        raise Stop('invalid_request_budget')
    return {
        'host': HOST, 'version': VERSION, 'login': LOGIN, 'binding': binding,
        'requests': [{'category': 'identity', 'method': 'GET', 'url': f'https://{HOST}{TARGET}'}],
        'authentication': 'TLS with Authorization bearer header', 'required_grants': SCOPES,
        'limits': {'max_gets': 1, 'connect_and_io_seconds': SOCKET_SECONDS,
                   'overall_seconds': TOTAL_SECONDS, 'body_bytes': BODY_BYTES, 'header_bytes': HEADER_BYTES,
                   'grant_record_max_age_seconds': GRANT_AGE_SECONDS, 'confirmation_seconds': CONFIRM_SECONDS},
        'excluded': ['token exchange or introspection', 'insights', 'media', 'pagination', 'retry',
                     'redirect', 'publishing', 'R2', 'Gemini', 'database access'],
    }


def record_token(binding):
    # Resolve exactly once after confirmation. Never consult dotenv, publishing or SDK credentials.
    raw = os.environ.pop(CREDENTIAL_ENV, '')
    if not 0 < len(raw) <= 8192:
        raise Stop('credential_record')
    try:
        record = json.loads(raw, object_pairs_hook=unique_object)
    except (ValueError, RecursionError):
        raise Stop('credential_record') from None
    if type(record) is not dict or record.keys() != {
        *binding, 'login', 'token_type', 'access_token', 'permissions', 'issued_at', 'expires_at'
    }:
        raise Stop('credential_record')
    if any(record[key] != expected for key, expected in binding.items()) or record['login'] != LOGIN:
        raise Stop('credential_binding')
    if record['token_type'] != 'bearer':
        raise Stop('credential_type')
    token = record['access_token']
    if type(token) is not str or not re.fullmatch(r'[a-zA-Z0-9._~+/-]{16,4096}={0,2}', token):
        raise Stop('credential_record')
    now = time.time()
    if type(record['expires_at']) is not int or record['expires_at'] <= now + TOTAL_SECONDS:
        raise Stop('credential_expired')
    if type(record['issued_at']) is not int or not 0 <= now - record['issued_at'] <= GRANT_AGE_SECONDS:
        raise Stop('stale_grant_record')
    grants = record['permissions']
    if (type(grants) is not list or len(grants) != len(SCOPES)
            or any(scope not in grants for scope in SCOPES)):
        raise Stop('credential_grants')
    return token


@dataclass
class Result:
    status: str = 'blocked'
    reason: str = 'current_grants_unverified'
    host: str = HOST
    request_version: str = VERSION
    login: str = LOGIN
    request_category: str = 'identity'
    attempted_gets: int = 0
    provisioning_record: str = 'unknown'
    account_binding: str = 'unknown'
    token_valid_for_identity: str = 'unknown'
    current_insights_permission: str = 'unknown'
    metric_support: str = 'not_requested'
    response_type: str = 'unknown'
    response_version: str = 'unknown'
    response_shape: str = 'unknown'
    response_sha256: str | None = None


class _LimitedStream:
    """Limit status/header/chunk lines before the standard HTTP parser can accumulate them."""
    def __init__(self, stream):
        self.stream = stream
        self.line_bytes = HEADER_BYTES
        self.total_bytes = HEADER_BYTES + BODY_BYTES
        self.close = stream.close
        self.flush = stream.flush

    def readline(self, size):
        raw = self.stream.readline(min(size, self.line_bytes + 1, self.total_bytes + 1))
        self.line_bytes -= len(raw)
        self.total_bytes -= len(raw)
        if self.line_bytes < 0 or self.total_bytes < 0:
            raise Stop('response_limit')
        return raw

    def read(self, size):
        raw = self.stream.read(min(size, self.total_bytes + 1))
        self.total_bytes -= len(raw)
        if self.total_bytes < 0:
            raise Stop('response_limit')
        return raw


class _BoundedResponse(http.client.HTTPResponse):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fp = _LimitedStream(self.fp)


def inspect_reply(response, expected_account, result):
    pairs = response.getheaders()
    if len(pairs) > 64 or sum(len(k) + len(v) + 4 for k, v in pairs) > HEADER_BYTES:
        raise Stop('response_limit')
    headers = {k.lower(): v for k, v in pairs}
    if len(headers) != len(pairs):
        raise Stop('ambiguous_headers')
    status = response.status
    if 'location' in headers or 300 <= status < 400:
        raise Stop('redirect')
    if status == 429:
        raise Stop('rate_limit')
    if status == 401:
        raise Stop('invalid_token')
    if status == 403:
        raise Stop('identity_denied')
    if status >= 500:
        raise Stop('provider_failure')
    if headers.get('content-encoding', 'identity') != 'identity':
        raise Stop('response_encoding')
    if headers.get('content-type', '').partition(';')[0].strip().lower() != 'application/json':
        raise Stop('response_type')
    result.response_type = 'application/json'
    length = headers.get('content-length')
    if length is not None and (not re.fullmatch('[0-9]{1,8}', length) or int(length) > BODY_BYTES):
        raise Stop('response_limit')
    if 'transfer-encoding' in headers and (length is not None or headers['transfer-encoding'].lower() != 'chunked'):
        raise Stop('response_framing')
    body = response.read(BODY_BYTES + 1)
    if len(body) > BODY_BYTES:
        raise Stop('response_limit')
    if length is not None and len(body) != int(length):
        raise Stop('response_framing')
    result.response_sha256 = hashlib.sha256(body).hexdigest()
    try:
        obj = json.loads(body.decode('utf-8'), object_pairs_hook=unique_object)
    except (ValueError, RecursionError):
        raise Stop('malformed_json') from None
    if type(obj) is not dict:
        raise Stop('response_shape')
    if 'error' in obj:
        code = obj['error'].get('code') if type(obj['error']) is dict else None
        if code == 190:
            raise Stop('invalid_token')
        if code in (4, 17, 32, 613, 80002):
            raise Stop('rate_limit')
        if code in (10, 200):
            raise Stop('identity_denied')
        raise Stop('provider_error')
    if status != 200:
        raise Stop('http_status')
    if headers.get('facebook-api-version') != VERSION:
        raise Stop('response_version')
    result.response_version = VERSION
    # Meta's Get Started example wraps one row in data. Accept a single node too.
    if obj.keys() == {'data'} and type(obj['data']) is list and len(obj['data']) == 1:
        row, shape = obj['data'][0], 'single_data_row'
    else:
        row, shape = obj, 'single_node'
    if (type(row) is not dict or not {'user_id', 'account_type'} <= row.keys()
            or row.keys() - {'user_id', 'account_type', 'id'}):
        raise Stop('response_shape')
    if 'id' in row and (type(row['id']) is not str or not re.fullmatch('[1-9][0-9]{0,29}', row['id'])):
        raise Stop('response_shape')
    result.response_shape = shape
    if row['user_id'] != expected_account:
        raise Stop('account_mismatch')
    if row['account_type'] not in ('BUSINESS', 'Business', 'MEDIA_CREATOR', 'Media_Creator'):
        raise Stop('not_professional')
    result.account_binding = 'pass'
    result.token_valid_for_identity = 'pass'


def _identity_worker(sender, connect, account, token):
    # Return only a small structured result over a private pipe. No raw response or credentials.
    result = Result(provisioning_record='pass', attempted_gets=1)
    try:
        # create_default_context() honors SSLKEYLOGFILE. Use verified system CAs without key logging.
        tls = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        tls.load_default_certs()
        connection = connect(HOST, context=tls, timeout=SOCKET_SECONDS)
        connection.response_class = _BoundedResponse
        connection.set_debuglevel(0)
        try:
            connection.request('GET', TARGET, headers={
                'Authorization': 'Bearer ' + token, 'Accept': 'application/json', 'Accept-Encoding': 'identity',
            })
            inspect_reply(connection.getresponse(), account, result)
        finally:
            connection.close()
        result.status = 'identity_candidate'
    except Stop as error:
        result.reason = str(error)
        if result.reason in ('account_mismatch', 'not_professional'):
            result.account_binding = 'fail'
        if result.reason == 'invalid_token':
            result.token_valid_for_identity = 'fail'
    except TimeoutError:
        result.reason = 'deadline'
    except BaseException:
        result.reason = 'execution_error'
    try:
        sender.send(result)
    except (BrokenPipeError, OSError):
        pass
    finally:
        sender.close()


def _verify_identity(binding, result):
    token = record_token(binding)
    result.provisioning_record = 'pass'
    # The parent can terminate even a resolver blocked in C or a peer trickling headers.
    # Spawn transfers the token in private IPC, never in process arguments.
    context = multiprocessing.get_context('spawn')
    receiver, sender = context.Pipe(duplex=False)
    worker = context.Process(target=_identity_worker, args=(
        sender, http.client.HTTPSConnection, binding['account_id'], token), daemon=True)
    deadline = time.monotonic() + TOTAL_SECONDS
    try:
        worker.start()
        sender.close()
        result.attempted_gets = 1
        if not receiver.poll(max(0, deadline - time.monotonic())):
            raise Stop('deadline')
        received = receiver.recv()
        if time.monotonic() >= deadline:
            raise Stop('deadline')
        return received
    finally:
        sender.close()
        receiver.close()
        if worker.pid is not None:
            if worker.is_alive():
                worker.kill()
            worker.join()
        worker.close()


def confirm_on_terminal(plan_digest):
    if not sys.stdin.isatty() or not sys.stdout.isatty():
        raise Stop('owner_terminal_required')
    challenge = f'ALLOW {plan_digest[:16]} {secrets.token_hex(8)}'
    expires = time.monotonic() + CONFIRM_SECONDS
    print(f'Owner authorization for this single GET. Type exactly: {challenge}', flush=True)
    # Never echo a mistyped secret through our output. Only compare in memory.
    answer = sys.stdin.readline(128).rstrip('\n')
    if time.monotonic() >= expires or answer != challenge:
        raise Stop('confirmation_refused')


def main(argv=None):
    parser = Parser(description=__doc__, allow_abbrev=False)
    for name in ('destination-id', 'account-id', 'app-id', 'credential-revision', 'max-gets'):
        parser.add_argument('--' + name)
    parser.add_argument('--execute', action='store_true', help='requires separate post-review owner authorization')
    parser.add_argument('--confirm-reviewed-plan', metavar='SHA256')
    args = parser.parse_args(argv)
    result = Result()
    binding = {}
    try:
        plan = plan_for(args)
        binding = plan['binding']
        digest = hashlib.sha256(json.dumps(plan, sort_keys=True).encode()).hexdigest()
        print(json.dumps({'mode': 'execution_plan' if args.execute else 'dry_run', 'plan': plan,
                          'plan_sha256': digest}, sort_keys=True), flush=True)
        if not args.execute:
            if args.confirm_reviewed_plan is not None:
                raise Stop('execution_opt_in_required')
            return 0
        if (not all(binding.values()) or args.max_gets != '1' or
                not re.fullmatch('[0-9a-f]{64}', args.confirm_reviewed_plan or '') or
                not hmac.compare_digest(args.confirm_reviewed_plan, digest)):
            raise Stop('reviewed_plan_required')
        confirm_on_terminal(digest)
        result = _verify_identity(binding, result)
    except Stop as error:
        result.reason = str(error)
        if result.reason in ('credential_grants', 'credential_expired', 'credential_binding',
                             'credential_type', 'credential_record', 'stale_grant_record'):
            result.provisioning_record = 'fail'
    except KeyboardInterrupt:
        result.reason = 'aborted'
    except Exception:
        # OS, TLS, HTTP and parser exceptions can contain secrets. No message, traceback or raw reply.
        result.reason = 'execution_error'
    print(json.dumps({**asdict(result), 'expected_binding': binding,
                      'evidence_utc': datetime.now(timezone.utc).isoformat(timespec='seconds')}, sort_keys=True))
    return 0 if result.status == 'identity_candidate' else 2


if __name__ == '__main__':
    sys.exit(main())
