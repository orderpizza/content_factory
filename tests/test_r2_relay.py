"""Preserved transient relay safety; all object storage and HTTPS calls are fake."""

from hashlib import sha256
from io import BytesIO
from pathlib import Path
from unittest.mock import MagicMock
from urllib.error import HTTPError, URLError
from workflow.delivery import DeliveryError, ExactMediaTransport, R2TransientRelay
import tempfile
import unittest


class R2RelayTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.data = b'exact-reviewed-jpeg-fixture'
        self.path = Path(self.directory.name) / 'slide.jpg'
        self.path.write_bytes(self.data)
        self.asset = {'path': str(self.path), 'bytes': len(self.data),
                      'sha256': sha256(self.data).hexdigest(), 'ordinal': 1}
        self.context = {'post_record_id': 5, 'attempt_number': 2}
        self.client = MagicMock()
        self.transport = MagicMock()
        self.transport.get_exact_bytes.return_value = self.data
        self.client.head_object.return_value = {
            'ContentLength': len(self.data), 'ContentType': 'image/jpeg',
            'Metadata': {'sha256': self.asset['sha256']},
        }
        self.relay = R2TransientRelay({'r2_bucket_name': 'fixture', 'r2_account_id': 'fixture',
                                      'r2_public_domain': 'https://media.example.com'},
                                     client=self.client, transport=self.transport)

    def test_stage_preserves_bytes_and_verifies_authenticated_and_public_hashes(self):
        key, url = self.relay.stage(self.context, self.asset)
        self.assertTrue(key.startswith('instagram-transient/5/2/1-'))
        self.assertEqual(url, 'https://media.example.com/' + key)
        upload = self.client.put_object.call_args.kwargs
        self.assertEqual(upload['Body'], self.data)
        self.assertEqual(upload['Metadata']['sha256'], self.asset['sha256'])
        self.assertEqual(upload['CacheControl'], 'no-store, max-age=0')
        second, _ = self.relay.stage(self.context, self.asset)
        self.assertNotEqual(key, second)

    def test_tampered_local_bytes_never_upload(self):
        self.path.write_bytes(b'tampered')
        with self.assertRaisesRegex(DeliveryError, 'reviewed asset changed'):
            self.relay.stage(self.context, self.asset)
        self.client.put_object.assert_not_called()

    def test_head_and_public_mismatches_refuse_staging(self):
        self.client.head_object.return_value['Metadata']['sha256'] = '0' * 64
        with self.assertRaisesRegex(DeliveryError, 'HEAD mismatch'):
            self.relay.stage(self.context, self.asset)
        self.transport.get_exact_bytes.assert_not_called()
        self.client.head_object.return_value['Metadata']['sha256'] = self.asset['sha256']
        self.transport.get_exact_bytes.return_value = b'x' * len(self.data)
        with self.assertRaisesRegex(DeliveryError, 'anonymous R2 bytes differ'):
            self.relay.stage(self.context, self.asset)

    def test_delete_requires_confirmed_absence(self):
        with self.assertRaisesRegex(DeliveryError, 'remained after delete'):
            self.relay.delete('fixture-key')
        missing = RuntimeError('fixture absence')
        missing.response = {'Error': {'Code': 'NoSuchKey'}, 'ResponseMetadata': {'HTTPStatusCode': 404}}
        self.client.head_object.side_effect = missing
        self.relay.delete('fixture-key')
        self.client.delete_object.assert_called_with(Bucket='fixture', Key='fixture-key')
        self.client.head_object.side_effect = RuntimeError('unknown outcome')
        with self.assertRaises(DeliveryError):
            self.relay.delete('fixture-key')


class ExactMediaTransportTests(unittest.TestCase):
    def test_bounded_probe_refuses_bad_length_status_and_redirect(self):
        for data, status, headers in [(b'abc', 200, {}), (b'abcd', 200, {}),
                                      (b'ab', 200, {}), (b'abc', 302, {}),
                                      (b'abc', 200, {'Location': 'https://elsewhere.example'})]:
            with self.subTest(data=data, status=status, headers=headers):
                response = BytesIO(data)
                response.status, response.headers = status, headers
                opener = MagicMock()
                opener.open.return_value = response
                transport = ExactMediaTransport(opener=opener)
                if data == b'abc' and status == 200 and not headers:
                    self.assertEqual(transport.get_exact_bytes('https://media.example.com/slide', expected_bytes=3, timeout=1, stage='probe'), data)
                else:
                    with self.assertRaises(DeliveryError):
                        transport.get_exact_bytes('https://media.example.com/slide', expected_bytes=3, timeout=1, stage='probe')
                self.assertTrue(response.closed)

    def test_non_https_and_transport_failure_do_not_leak_response(self):
        opener = MagicMock()
        transport = ExactMediaTransport(opener=opener)
        with self.assertRaises(DeliveryError):
            transport.get_exact_bytes('http://media.example.com', expected_bytes=3, timeout=1, stage='probe')
        opener.open.assert_not_called()
        opener.open.side_effect = URLError('private response')
        with self.assertRaises(DeliveryError) as error:
            transport.get_exact_bytes('https://media.example.com', expected_bytes=3, timeout=1, stage='probe')
        self.assertNotIn('private response', str(error.exception))

    def test_http_error_body_is_closed_and_not_disclosed(self):
        body = BytesIO(b'private response')
        opener = MagicMock()
        opener.open.side_effect = HTTPError('https://media.example.com', 302, 'redirect', {}, body)
        with self.assertRaises(DeliveryError) as error:
            ExactMediaTransport(opener=opener).get_exact_bytes('https://media.example.com', expected_bytes=3, timeout=1, stage='probe')
        self.assertTrue(body.closed)
        self.assertNotIn('private response', str(error.exception))
