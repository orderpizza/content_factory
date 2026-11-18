"""Single-attempt R2 exchanges with process-enforced wall deadlines.

Live R2 remains blocked until conditional writes/deletes and endpoint semantics
are reviewed. Secrets cross only memory/IPC, never argv, files or diagnostics.
"""
import multiprocessing
import os
import time

from .delivery import DeliveryConfigurationError, DeliveryError
from .offline import is_offline

VERIFIED_R2_CONTRACTS = frozenset()
CONTRACT = 'r2_conditional_objects_v1'


class ObjectAbsent(Exception):
    response = {'Error': {'Code': 'NoSuchKey'}, 'ResponseMetadata': {'HTTPStatusCode': 404}}


def sdk_config():
    from botocore.config import Config
    return Config(connect_timeout=5, read_timeout=10, retries={'total_max_attempts': 1, 'mode': 'standard'},
                  s3={'addressing_style': 'path'})


def single_send_guard(account_id):
    from urllib.parse import urlsplit
    sent = False
    def guard(request, **kwargs):
        nonlocal sent
        url = urlsplit(request.url)
        if sent or url.scheme != 'https' or url.netloc != f'{account_id}.r2.cloudflarestorage.com':
            raise RuntimeError('R2 redirect or SDK replay refused')
        sent = True
    return guard


def _worker(pipe, operation, config, credentials, values):
    import logging
    logging.disable(logging.CRITICAL)
    try:
        if operation == 'public_get':
            from .delivery import ExactMediaTransport
            result = ExactMediaTransport().get_exact_bytes(**values)
        else:
            import boto3
            client = boto3.client('s3', endpoint_url=f"https://{config['r2_account_id']}.r2.cloudflarestorage.com",
                aws_access_key_id=credentials[0], aws_secret_access_key=credentials[1], region_name='auto',
                verify=True, use_ssl=True, config=sdk_config())
            client.meta.events.register('before-send.s3', single_send_guard(config['r2_account_id']))
            try:
                reply = getattr(client, operation)(**values)
                result = {key: reply[key] for key in ('ETag', 'VersionId', 'ContentLength', 'ContentType', 'Metadata') if key in reply}
            finally:
                client.close()
        message = ('ok', result)
    except BaseException as error:
        response = getattr(error, 'response', {})
        status = response.get('ResponseMetadata', {}).get('HTTPStatusCode')
        code = str(response.get('Error', {}).get('Code', ''))
        kind = 'absent' if operation == 'head_object' and (status == 404 or code in {'NoSuchKey', 'NotFound', '404'}) else (
            'precondition' if status == 412 else 'unavailable')
        message = (kind, None)
    try:
        pipe.send(message)
    except (BrokenPipeError, OSError):
        pass
    finally:
        pipe.close()


def supervised(operation, config, credentials, values, *, timeout=20, worker=_worker):
    if type(timeout) not in {int, float} or not 0 < timeout <= 20:
        raise DeliveryConfigurationError('invalid R2 operation deadline')
    ctx = multiprocessing.get_context('spawn')
    parent, child = ctx.Pipe(duplex=False)
    process = ctx.Process(target=worker, args=(child, operation, config, credentials, values), daemon=True)
    deadline = time.monotonic() + timeout
    try:
        process.start()
        child.close()
        if not parent.poll(max(0, deadline - time.monotonic())):
            raise DeliveryError('r2_deadline', 'R2 operation outcome unavailable; no automatic SDK replay', False, 'r2')
        kind, result = parent.recv()
        if time.monotonic() >= deadline:
            raise DeliveryError('r2_deadline', 'R2 operation deadline exceeded', False, 'r2')
        if kind == 'absent':
            raise ObjectAbsent()
        if kind != 'ok':
            raise DeliveryError('r2_' + kind, 'R2 operation failed or is uncertain', False, 'r2')
        return result
    finally:
        parent.close()
        child.close()
        if process.pid is not None:
            if process.is_alive():
                process.kill()
            process.join()
        process.close()


def require_live_contract():
    if is_offline() or CONTRACT not in VERIFIED_R2_CONTRACTS:
        raise DeliveryConfigurationError('live R2 conditional-operation contract is disabled/unverified')


class BoundedR2Client:
    def __init__(self, config):
        require_live_contract()
        import re
        if not re.fullmatch(r'[a-f0-9]{32}', config['r2_account_id']):
            raise DeliveryConfigurationError('invalid pinned R2 account')
        self.config = dict(config)
        self.timeout = 20

    def _call(self, operation, values):
        require_live_contract()
        credentials = (os.getenv('R2_ACCESS_KEY_ID'), os.getenv('R2_SECRET_ACCESS_KEY'))
        if not all(credentials):
            raise DeliveryConfigurationError('R2 credentials are required')
        return supervised(operation, self.config, credentials, values, timeout=self.timeout)

    def put_object(self, **values): return self._call('put_object', values)
    def head_object(self, **values): return self._call('head_object', values)
    def delete_object(self, **values): return self._call('delete_object', values)


class BoundedMediaTransport:
    def get_exact_bytes(self, url, *, expected_bytes, timeout, stage):
        require_live_contract()
        if not 0 < expected_bytes <= 8 * 1024 * 1024:
            raise DeliveryConfigurationError('invalid public JPEG response bound')
        return supervised('public_get', {}, (), dict(url=url, expected_bytes=expected_bytes, timeout=timeout, stage=stage), timeout=timeout)
