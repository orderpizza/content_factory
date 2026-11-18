"""No real sockets: SDK policy, request admission and hard process deadlines."""
import time
from types import SimpleNamespace

import pytest

from workflow.delivery import DeliveryConfigurationError, DeliveryError
from workflow.offline import offline_only
from workflow.r2_transport import BoundedR2Client, BoundedMediaTransport, sdk_config, single_send_guard, supervised


def stalled(pipe, operation, config, credentials, values):
    time.sleep(10)  # Parent terminates this process without any network call.


@pytest.mark.parametrize('operation', ['put_object', 'head_object', 'delete_object', 'public_get'])
def test_whole_operation_deadline_terminates_stalled_sdk_or_body(operation):
    start = time.monotonic()
    with pytest.raises(DeliveryError, match='deadline|outcome unavailable') as error:
        supervised(operation, {}, ('private-key', 'private-secret'), {}, timeout=.1, worker=stalled)
    assert time.monotonic() - start < 2
    assert 'private' not in str(error.value)


def test_sdk_retries_redirects_and_endpoint_changes_are_refused():
    config = sdk_config()
    assert config.connect_timeout == 5 and config.read_timeout == 10
    assert config.retries['total_max_attempts'] == 1 and config.s3['addressing_style'] == 'path'
    guard = single_send_guard('a' * 32)
    request = SimpleNamespace(url='https://' + 'a' * 32 + '.r2.cloudflarestorage.com/bucket/key')
    guard(request)
    with pytest.raises(RuntimeError, match='replay'): guard(request)
    with pytest.raises(RuntimeError, match='redirect'):
        single_send_guard('a' * 32)(SimpleNamespace(url='https://wrong.example/bucket/key'))


def test_live_r2_remains_blocked_even_with_credentials(monkeypatch):
    monkeypatch.setenv('R2_ACCESS_KEY_ID', 'private-key')
    monkeypatch.setenv('R2_SECRET_ACCESS_KEY', 'private-secret')
    with pytest.raises(DeliveryConfigurationError, match='disabled/unverified'):
        BoundedR2Client({'r2_account_id': 'a' * 32})
    with offline_only(), pytest.raises(DeliveryConfigurationError, match='disabled/unverified'):
        BoundedMediaTransport().get_exact_bytes('https://example.invalid/a', expected_bytes=100, timeout=20, stage='probe')
