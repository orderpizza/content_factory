"""Offline protocol sequencing only; no credentials or network calls."""
from hashlib import sha256
from pathlib import Path

import pytest

from workflow.delivery import DeliveryError, R2TransientRelay
from workflow.instagram_protocol import OfflineInstagramProtocol
from workflow.offline import offline_only


@pytest.fixture(autouse=True)
def no_network():
    with offline_only():
        yield


class FakeObjects:
    def __init__(self):
        self.objects = {}

    def put_object(self, *, Bucket, Key, Body, ContentType, CacheControl, Metadata, IfNoneMatch=None):
        if IfNoneMatch == '*' and Key in self.objects:
            raise ValueError('object already exists')
        self.objects[Key] = (Body, ContentType, Metadata)

    def head_object(self, *, Bucket, Key):
        if Key not in self.objects:
            from workflow.r2_transport import ObjectAbsent
            raise ObjectAbsent()
        data, kind, metadata = self.objects[Key]
        return {"ContentLength": len(data), "ContentType": kind, "Metadata": metadata, 'ETag': sha256(data).hexdigest()}

    def delete_object(self, *, Bucket, Key, IfMatch=None):
        if Key in self.objects:
            if IfMatch != sha256(self.objects[Key][0]).hexdigest():
                raise ValueError('conditional delete mismatch')
            del self.objects[Key]

    def get_exact_bytes(self, url, *, expected_bytes, timeout, stage):
        return self.objects[url.removeprefix("https://example.invalid/")][0]


class FakeTransport:
    def __init__(self):
        self.calls = []
        self.next_id = 100
        self.status = "FINISHED"
        self.fail_at = None

    def request(self, method, path, body):
        self.calls.append((method, path, dict(body)))
        if self.fail_at == len(self.calls):
            raise TimeoutError("secret-token and https://secret.example")
        if method == "GET":
            return {"id": path[1:], "status_code": self.status}
        self.next_id += 1
        return {"id": str(self.next_id)}


def fixture(tmp_path, count):
    assets = []
    descriptions = [f"alt {n}" for n in range(1, count + 1)]
    for n, alt in enumerate(descriptions, 1):
        data = f"reviewed jpeg bytes {n}".encode()
        path = tmp_path / f"{n}.jpg"
        path.write_bytes(data)
        assets.append({"ordinal": n, "path": str(path), "bytes": len(data),
                       "sha256": sha256(data).hexdigest(), "alt_text": alt})
    context = {"platform": "instagram", "provider_account_id": "123", "delivery_revision_id": 1,
               "post_attempt_id": 1, "post_record_id": 2, "attempt_number": 1, "assets": assets,
               "package": {"is_ai_generated": True, "caption": "Exact caption", "image_alt_text": descriptions}}
    objects, transport = FakeObjects(), FakeTransport()
    relay = R2TransientRelay({"r2_bucket_name": "test", "r2_account_id": "test",
                              "r2_public_domain": "https://example.invalid"},
                             client=objects, transport=objects)
    calls = []
    def record(**kw):
        calls.append(kw)
        return len(calls)
    from instagram_fakes import FakeClock
    clock = FakeClock()
    return context, objects, transport, calls, record, OfflineInstagramProtocol(
        transport, relay, account_id="123", sleep=clock.sleep, monotonic=clock.monotonic)


@pytest.mark.parametrize("count", [4, 5, 6])
def test_order_exact_bytes_alt_and_receipt(tmp_path, count):
    context, objects, transport, records, record, protocol = fixture(tmp_path, count)
    staged = protocol.stage(context, record)
    receipt = protocol.publish(context, staged)
    creates = [body for method, path, body in transport.calls if method == "POST" and path.endswith("/media")]
    assert [c["alt_text"] for c in creates[:-1]] == context["package"]["image_alt_text"]
    assert creates[-1] == {"media_type": "CAROUSEL", "children": ",".join(str(i) for i in range(101, 101 + count)),
                           "caption": "Exact caption", "is_ai_generated": True}
    assert [objects.objects[c["image_url"].split("example.invalid/", 1)[1]][0] for c in creates[:-1]] == [
        Path(a["path"]).read_bytes() for a in context["assets"]]
    assert staged["parent"] == str(101 + count) and receipt == str(102 + count)
    assert sum(r.get("resource_type") == "instagram_create_intent" for r in records) == count + 1


def test_invalid_account_or_alt_stops_before_upload(tmp_path):
    context, objects, transport, _, record, protocol = fixture(tmp_path, 4)
    context["assets"][0]["alt_text"] = "changed"
    with pytest.raises(DeliveryError):
        protocol.stage(context, record)
    assert not objects.objects and not transport.calls


def test_changed_bytes_and_provider_failure_are_not_retried(tmp_path):
    context, objects, transport, records, record, protocol = fixture(tmp_path, 4)
    Path(context["assets"][0]["path"]).write_bytes(b"changed")
    with pytest.raises(DeliveryError):
        protocol.stage(context, record)
    assert not transport.calls and records[0]["resource_type"] == "r2_object"


def test_lost_child_response_records_intent_and_redacts(tmp_path):
    context, _, transport, records, record, protocol = fixture(tmp_path, 4)
    transport.fail_at = 1
    with pytest.raises(DeliveryError) as caught:
        protocol.stage(context, record)
    assert "secret" not in str(caught.value)
    assert records[-1]["resource_type"] == "instagram_create_intent"
    assert len(transport.calls) == 1


@pytest.mark.parametrize("status", ["IN_PROGRESS", "ERROR", "EXPIRED", "PUBLISHED", None])
def test_polling_is_bounded_and_fails_closed(tmp_path, status):
    context, _, transport, _, record, protocol = fixture(tmp_path, 4)
    transport.status = status
    with pytest.raises(DeliveryError):
        protocol.stage(context, record)
    assert len([call for call in transport.calls if call[0] == "GET"]) == (5 if status == "IN_PROGRESS" else 1)
    assert not any(call[1].endswith("media_publish") for call in transport.calls)


def test_readiness_admission_latency_cannot_compress_poll_intervals(tmp_path):
    from instagram_fakes import FakeClock
    _, _, transport, _, _, protocol = fixture(tmp_path, 4)
    clock = FakeClock()
    starts = []
    def request(method, path, body):
        if not starts:
            clock.advance(30)  # Read-only readiness refresh before first dispatch.
        starts.append(clock.monotonic())
        clock.advance(3)
        return {'id': path[1:], 'status_code': 'FINISHED' if len(starts) == 2 else 'IN_PROGRESS'}
    transport.request = request
    protocol.sleep, protocol.monotonic = clock.sleep, clock.monotonic
    protocol._ready('123')
    assert starts[1] - starts[0] >= 60


def test_public_byte_mismatch_fails_before_container_create(tmp_path):
    context, objects, transport, _, record, protocol = fixture(tmp_path, 4)
    original = objects.get_exact_bytes
    objects.get_exact_bytes = lambda *args, **kwargs: b"x" * len(original(*args, **kwargs))
    with pytest.raises(DeliveryError, match="anonymous R2 bytes differ"):
        protocol.stage(context, record)
    assert not transport.calls


def test_parent_response_loss_is_never_retried(tmp_path):
    context, _, transport, records, record, protocol = fixture(tmp_path, 4)
    transport.fail_at = 9  # four create/read pairs, then parent create
    with pytest.raises(DeliveryError):
        protocol.stage(context, record)
    assert records[-1] == {"resource_type": "instagram_create_intent", "remote_id": "parent",
                           "safe_metadata": {"kind": "parent"}}
    assert len(transport.calls) == 9
    assert not any(path.endswith("media_publish") for _, path, _ in transport.calls)


def test_lost_publish_reply_makes_one_request_and_redacts(tmp_path):
    context, _, transport, _, record, protocol = fixture(tmp_path, 4)
    staged = protocol.stage(context, record)
    transport.fail_at = len(transport.calls) + 1
    with pytest.raises(DeliveryError) as caught:
        protocol.publish(context, staged)
    assert "secret" not in str(caught.value)
    assert sum(path.endswith("media_publish") for _, path, _ in transport.calls) == 1


@pytest.mark.parametrize("value", [None, False, 1, "true"])
def test_unreviewed_disclosure_stops_before_any_side_effect(tmp_path, value):
    context, objects, transport, records, record, protocol = fixture(tmp_path, 4)
    if value is None:
        del context["package"]["is_ai_generated"]
    else:
        context["package"]["is_ai_generated"] = value
    with pytest.raises(DeliveryError):
        protocol.stage(context, record)
    assert not records and not objects.objects and not transport.calls


@pytest.mark.parametrize("duplicate_at", [2, 5])
def test_duplicate_container_identity_holds_last_create_intent(tmp_path, duplicate_at):
    context, _, transport, records, record, protocol = fixture(tmp_path, 4)
    original = transport.request

    def repeated_id(method, path, body):
        result = original(method, path, body)
        if method == "POST" and transport.next_id == 100 + duplicate_at:
            return {"id": "101"}
        return result

    transport.request = repeated_id
    with pytest.raises(DeliveryError, match="ambiguous"):
        protocol.stage(context, record)
    assert records[-1]["resource_type"] == "instagram_create_intent"
    assert all(not path.endswith("/media_publish") for _, path, _ in transport.calls)


@pytest.mark.parametrize("caption", ["x" * 2201, "#example " * 31, "@person " * 21])
def test_overlimit_caption_refused_without_truncation(tmp_path, caption):
    context, objects, transport, records, record, protocol = fixture(tmp_path, 4)
    context["package"]["caption"] = caption
    with pytest.raises(DeliveryError):
        protocol.stage(context, record)
    assert not records and not objects.objects and not transport.calls
