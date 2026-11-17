"""Only test code supplies unverified token introspection and HTTP observations."""
import json
from datetime import timedelta
from urllib.parse import parse_qs, urlsplit

from common.timestamps import serialize_timestamp, utc_datetime_now
from workflow.instagram_composition import InstagramComposition, EnvironmentCredentials
from workflow.instagram_http import HTTPReply
from workflow.instagram_readiness import PERMISSIONS, VERSION
from test_instagram_protocol import FakeObjects, FakeTransport


class FakeHTTP:
    def __init__(self):
        self.protocol = FakeTransport()
        self.identity = {'user_id': '123456', 'account_type': 'BUSINESS'}
        self.permissions = {'data': [{'permission': p, 'status': 'granted'} for p in sorted(PERMISSIONS)]}
        self.quota = {'data': [{'quota_usage': 0, 'config': {'quota_total': 20, 'quota_duration': 86400}}]}
        self.validity = {'is_valid': True, 'account_id': '123456', 'app_id': '789',
            'login_mode': 'instagram_login', 'token_type': 'instagram_user', 'api_version': VERSION,
            'expires_at': serialize_timestamp(utc_datetime_now() + timedelta(days=1))}
        self.version = VERSION
        self.status = 200
        self.read_calls = []
        self.after = lambda: None
        self.accepted_token = 'fixture-secret'

    def token_validity(self, token):
        if token.value != self.accepted_token:
            return {**self.validity, 'is_valid': False}
        return self.validity

    def __call__(self, method, target, headers, body, timeout, limit):
        assert timeout <= 20 and limit <= 65536
        assert headers['Authorization'] == 'Bearer ' + self.accepted_token
        assert self.accepted_token not in target
        parsed = urlsplit(target)
        path = parsed.path.removeprefix('/' + VERSION)
        params = {k: v[0] for k, v in parse_qs(parsed.query if body is None else body.decode()).items()}
        if path in {'/me', '/me/permissions', '/123456/content_publishing_limit'}:
            assert method == 'GET'
            self.read_calls.append(path)  # Never capture authorization headers.
            data = {'/me': self.identity, '/me/permissions': self.permissions,
                    '/123456/content_publishing_limit': self.quota}[path]
        else:
            data = self.protocol.request(method, path, params)
        self.after()
        return HTTPReply(self.status, {'facebook-api-version': self.version, 'content-type': 'application/json'}, json.dumps(data).encode())


def composition(store, *, http=None, credentials=None, clock=utc_datetime_now, **timing):
    http = http or FakeHTTP()
    objects = FakeObjects()
    destination_id = store.connection.execute('SELECT social_destination_id FROM social_destinations').fetchone()[0]
    factory = InstagramComposition(store, destination_id, wire=http, token_validity=http.token_validity,
        credentials=EnvironmentCredentials({'DELIVERY_TOKEN': 'fixture-secret'}) if credentials is None else credentials,
        objects=objects, media_transport=objects,
        relay_config={'r2_bucket_name': 'test', 'r2_account_id': 'test', 'r2_public_domain': 'https://example.invalid'},
        clock=clock, **timing)
    return factory, objects, http


class FakeClock:
    def __init__(self):
        self.origin = utc_datetime_now()
        self.elapsed = 0.0
        self.wall_elapsed = 0.0
        self.on_sleep = lambda: None

    def now(self):
        return self.origin + timedelta(seconds=self.wall_elapsed)

    def timestamp(self):
        return serialize_timestamp(self.now())

    def monotonic(self):
        return self.elapsed

    def advance(self, seconds):
        self.elapsed += seconds
        self.wall_elapsed += seconds

    def sleep(self, seconds):
        self.advance(seconds)
        self.on_sleep()
