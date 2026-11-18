"""Generic delivery orchestration and transient R2 helpers.

The live workflow runner does not construct these objects. The offline rehearsal
and boundary tests inject local transports and fake adapters.
"""

from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
from typing import Any, Callable, Mapping
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener
import json
import os
import secrets
import time

from common.diagnostics import safe_diagnostic

from .store import WorkflowStore


class DeliveryConfigurationError(RuntimeError):
    """Raised before provider work when its local configuration is incomplete."""


@dataclass(frozen=True)
class DeliveryError(RuntimeError):
    category: str
    detail: str
    retryable: bool
    stage: str

    def __str__(self) -> str:
        return f"{self.stage}: {self.category}: {self.detail}"


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: ANN001
        return None


class ExactMediaTransport:
    """Bounded HTTPS fetch for byte-exact R2 verification; redirects are refused."""

    def __init__(self, *, opener: Any | None = None):
        self.opener = opener or build_opener(_NoRedirect())

    def get_exact_bytes(self, url: str, *, expected_bytes: int, timeout: float, stage: str) -> bytes:
        if urlsplit(url).scheme != "https":
            raise DeliveryError("configuration", "public media URL is not HTTPS", False, stage)
        request = Request(url, headers={"User-Agent": "content-factory/0.1"}, method="GET")
        try:
            with self.opener.open(request, timeout=timeout) as response:
                if int(getattr(response, "status", 200)) != 200:
                    raise DeliveryError("media_probe", "public media probe was not HTTP 200", True, stage)
                if response.headers.get("Location"):
                    raise DeliveryError("media_probe", "public media probe redirected", False, stage)
                value = response.read(expected_bytes + 1)
        except HTTPError as error:
            error.close()
            raise DeliveryError("media_probe", f"public media HTTP {error.code}", True, stage) from error
        except (TimeoutError, URLError, OSError) as error:
            raise DeliveryError("transport", type(error).__name__, True, stage) from error
        if len(value) != expected_bytes:
            raise DeliveryError("media_probe", "public media byte length differs", True, stage)
        return value


class R2TransientRelay:
    """Upload and verify exact reviewed JPEG bytes for external public fetch."""

    def __init__(
        self,
        config: Mapping[str, Any],
        *,
        client: Any | None = None,
        transport: ExactMediaTransport | None = None,
        before_io: Callable[[], None] | None = None,
        io_timeout: Callable[[], float] | None = None,
        monotonic=time.monotonic,
    ):
        self.config = dict(config)
        self.before_io = before_io or (lambda: None)
        self.io_timeout, self.monotonic = io_timeout or (lambda: 20), monotonic
        from .r2_transport import BoundedMediaTransport, BoundedR2Client
        self.transport = transport or BoundedMediaTransport()
        self.bucket = _required_setting(self.config, "r2_bucket_name")
        self.public_domain = _required_setting(self.config, "r2_public_domain").rstrip("/")
        account_id = _required_setting(self.config, "r2_account_id")
        origin = urlsplit(self.public_domain)
        if (origin.scheme != "https" or origin.path not in {"", "/"} or not origin.hostname
                or origin.username or origin.password or origin.query or origin.fragment or origin.port not in {None, 443}):
            raise DeliveryConfigurationError("R2 public domain must be an origin-only HTTPS URL")
        if client is None:
            client = BoundedR2Client(self.config)
        self.client = client

    def _io(self, function, **values):
        self.before_io()
        budget = min(20, self.io_timeout())
        if budget <= 0:
            raise DeliveryError('r2_deadline', 'R2 execution budget exhausted', False, 'r2')
        from .r2_transport import BoundedR2Client
        if isinstance(self.client, BoundedR2Client):
            self.client.timeout = budget
        if 'timeout' in values:
            values['timeout'] = budget
        started = self.monotonic()
        result = function(**values)
        if not 0 <= self.monotonic() - started < budget:
            raise DeliveryError('r2_deadline', 'R2 reply arrived outside its execution budget', False, 'r2')
        self.before_io()
        return result

    def identity(self, context, asset, key):
        return {**{k: context[k] for k in ('post_record_id', 'post_attempt_id', 'attempt_number',
                    'package_hash', 'manifest_hash', 'destination_key', 'provider_account_id')},
                'bucket': self.bucket, 'r2_account_id': self.config['r2_account_id'], 'public_domain': self.public_domain,
                'object_key': key, 'sha256': asset['sha256'], 'bytes': asset['bytes'], 'ordinal': asset['ordinal']}

    @staticmethod
    def object_metadata(identity):
        from .store import digest
        return {'sha256': identity['sha256'], 'post-record-id': str(identity['post_record_id']),
                'attempt-number': str(identity['attempt_number']), 'asset-ordinal': str(identity['ordinal']),
                'identity-sha256': digest(identity)}

    def stage(
        self,
        context: Mapping[str, Any],
        asset: Mapping[str, Any],
        *,
        key: str | None = None,
    ) -> tuple[str, str]:
        path = Path(str(asset["path"]))
        data = path.read_bytes()
        if len(data) != int(asset["bytes"]) or sha256(data).hexdigest() != asset["sha256"]:
            raise DeliveryError("validation", "reviewed asset changed before R2 upload", False, "r2_upload")
        key = key or _r2_object_key(context, asset)
        metadata = {
            "sha256": str(asset["sha256"]),
            "post-record-id": str(context["post_record_id"]),
            "attempt-number": str(context["attempt_number"]),
            "asset-ordinal": str(asset["ordinal"]),
        }
        owned = context.get('destination_config', {}).get('adapter_version') == 'instagram_login_v1'
        if owned:
            metadata = self.object_metadata(self.identity(context, asset, key))
        try:
            self._io(self.client.put_object,
                Bucket=self.bucket, Key=key, Body=data, ContentType="image/jpeg",
                CacheControl="no-store, max-age=0", Metadata=metadata,
                **({'IfNoneMatch': '*'} if owned else {}),
            )
            head = self._io(self.client.head_object, Bucket=self.bucket, Key=key)
        except (DeliveryError, DeliveryConfigurationError):
            raise
        except Exception as error:
            raise DeliveryError("r2", type(error).__name__, True, "r2_upload") from error
        returned_metadata = {str(k).casefold(): str(v) for k, v in dict(head.get("Metadata", {})).items()}
        if (
            int(head.get("ContentLength", -1)) != len(data)
            or str(head.get("ContentType", "")).casefold() != "image/jpeg"
            or returned_metadata.get("sha256") != asset["sha256"]
            or (owned and any(returned_metadata.get(k) != v for k, v in metadata.items()))
        ):
            raise DeliveryError("r2_verification", "authenticated R2 HEAD mismatch", False, "r2_head")
        public_url = self.public_domain + "/" + quote(key, safe="/")
        fetched = self._io(self.transport.get_exact_bytes,
            url=public_url, expected_bytes=len(data), timeout=20, stage="r2_public_probe"
        )
        if sha256(fetched).hexdigest() != asset["sha256"]:
            raise DeliveryError("r2_verification", "anonymous R2 bytes differ", False, "r2_public_probe")
        return key, public_url

    def delete_owned(self, identity, *, record_event=lambda event: None):
        """Exact identity HEAD, conditional DELETE, then confirmed absence."""
        if (identity['bucket'] != self.bucket or identity['r2_account_id'] != self.config['r2_account_id']
                or identity['public_domain'] != self.public_domain):
            raise DeliveryConfigurationError('cleanup R2 destination mismatch')
        values = {'Bucket': self.bucket, 'Key': identity['object_key']}
        try:
            head = self._io(self.client.head_object, **values)
        except Exception as error:
            if _object_absent(error):
                self.before_io()
                return
            raise
        metadata = {str(k).casefold(): str(v) for k, v in head.get('Metadata', {}).items()}
        etag = head.get('ETag')
        if (head.get('ContentLength') != identity['bytes'] or head.get('ContentType') != 'image/jpeg'
                or any(metadata.get(k) != v for k, v in self.object_metadata(identity).items())
                or not isinstance(etag, str) or not etag or len(etag) > 200):
            raise DeliveryError('r2_identity', 'stored object identity differs; deletion refused', False, 'r2_delete')
        record_event('delete_intent')
        self._io(self.client.delete_object, **values, IfMatch=etag)
        record_event('delete_returned')
        try:
            self._io(self.client.head_object, **values)
        except Exception as error:
            if _object_absent(error):
                self.before_io()
                return
            raise
        raise DeliveryError('r2_cleanup', 'object absence is not confirmed', True, 'r2_delete')

    def delete(self, key: str) -> None:
        try:
            self._io(self.client.delete_object, Bucket=self.bucket, Key=key)
            try:
                self._io(self.client.head_object, Bucket=self.bucket, Key=key)
            except Exception as error:
                response = getattr(error, "response", {})
                code = str(response.get("Error", {}).get("Code", ""))
                status = response.get("ResponseMetadata", {}).get("HTTPStatusCode")
                if code in {"404", "NoSuchKey", "NotFound"} or status == 404:
                    return
                raise
        except DeliveryError:
            raise
        except Exception as error:
            raise DeliveryError("r2_cleanup", type(error).__name__, True, "r2_delete") from error
        raise DeliveryError("r2_cleanup", "R2 object remained after delete", True, "r2_delete")


def _object_absent(error):
    response = getattr(error, 'response', {})
    return (str(response.get('Error', {}).get('Code', '')) in {'404', 'NoSuchKey', 'NotFound'}
            or response.get('ResponseMetadata', {}).get('HTTPStatusCode') == 404)


class CredentialedPostingAgent:
    """Post exact reviewed packages; never generate or modify creative."""

    def __init__(
        self,
        store: WorkflowStore,
        *,
        adapters: Mapping[str, Any] | None = None,
        artifact_root: str | Path | None = None,
        instance_id: str = "delivery",
        post_record_id: int | None = None,
        start_guard: Callable[[], bool] | None = None,
    ):
        self.store = store
        self.adapters = dict(adapters or {})
        self.post_record_id = post_record_id
        self.start_guard = start_guard
        self.instance_id = instance_id
        self.artifact_root = None if artifact_root is None else Path(artifact_root).resolve()

    def run_once(self) -> int | None:
        if self.start_guard is not None and not self.start_guard():
            return None
        record = self.store.claim("post_records", "post_record_id", self.instance_id, record_id=self.post_record_id)
        if record is None:
            return None
        try:
            context = self.store.prepare_post_attempt(record)
        except Exception as error:
            self.store.defer_post_claim(record, safe_diagnostic(error))
            return int(record["post_record_id"])
        context["attempt_number"] = int(record["attempt_count"])
        if self.artifact_root is not None and any(
            not Path(asset["path"]).resolve().is_relative_to(self.artifact_root)
            for asset in context["assets"]
        ):
            return self.store.fail_post_attempt(
                context, category="validation",
                detail="delivery asset is outside the configured artifact root",
                retryable=False, after_final_marker=False,
            )
        def record_resource(**values: Any) -> int:
            resource_id = values.pop("resource_id", None)
            if resource_id is not None:
                return self.store.update_publication_resource(
                    int(resource_id), status=str(values.pop("status")), context=context,
                )
            return self.store.record_publication_resource(
                int(context["post_attempt_id"]), context=context, **values,
            )
        try:
            if (context.get("delivery_revision_id") is not None
                    and context["destination_config"].get("adapter_version") == "unimplemented"):
                raise DeliveryConfigurationError("production delivery revision has no configured provider")
            adapter = self.adapters.get(context["platform"])
            if adapter is None:
                raise DeliveryConfigurationError("no delivery adapter is configured")
            if context["destination_config"].get("adapter_version") == "instagram_login_v1":
                from .instagram_composition import is_registered_adapter
                if not is_registered_adapter(adapter):
                    raise DeliveryConfigurationError("registered Instagram composition and run activation required")
            simulated = context["package"].get("execution_mode") == "simulation"
            if simulated != (getattr(adapter, "execution_mode", None) == "simulation"):
                raise DeliveryConfigurationError("simulation package and adapter modes must match")
            staged = adapter.stage(context, record_resource)
            self.store.mark_attempt_ready(int(context["post_attempt_id"]))
            if hasattr(adapter, "check_before_final"):
                adapter.check_before_final(context, staged)
        except DeliveryConfigurationError as error:
            self.store.fail_post_attempt(
                context, category="configuration", detail=str(error), retryable=False,
                after_final_marker=False,
            )
            return int(record["post_record_id"])
        except DeliveryError as error:
            self.store.fail_post_attempt(
                context, category=error.category, detail=error.detail, retryable=error.retryable,
                after_final_marker=False,
            )
            return int(record["post_record_id"])
        except Exception as error:
            self.store.fail_post_attempt(
                context, category="adapter_internal", detail=type(error).__name__, retryable=False,
                after_final_marker=False,
            )
            return int(record["post_record_id"])
        try:
            self.store.mark_final_publication_request(context)
        except RuntimeError:
            # Cancellation or expiry may have won the fenced transaction. Those
            # commands already finalized the attempt and cleanup handoff.
            current = self.store.connection.execute(
                "SELECT status FROM post_records WHERE post_record_id=?", (record["post_record_id"],),
            ).fetchone()
            if current is not None and current["status"] in {"cancelled", "expired"}:
                return int(record["post_record_id"])
            self.store.fail_post_attempt(
                context, category="final_marker", detail="final request marker was refused",
                retryable=False, after_final_marker=False,
            )
            return int(record["post_record_id"])
        try:
            external_id = adapter.publish(context, staged)
            if context['destination_config'].get('adapter_version') == 'instagram_login_v1':
                # The response ID is useful even if readback, lease or final
                # persistence subsequently fails. It is not verified publication.
                self.store.record_publish_acceptance(context, external_id)
                receipt = adapter.verify_publication(context, external_id)
                return self.store.complete_publication(context, external_id, receipt=receipt)
            return self.store.complete_publication(context, external_id)
        except Exception as error:
            return self.store.fail_post_attempt(
                context, category=(error.category if isinstance(error, DeliveryError) else "outcome_unknown"),
                detail=(error.detail if isinstance(error, DeliveryError) else type(error).__name__),
                retryable=False, after_final_marker=True,
            )


class R2CleanupWorker:
    def __init__(
        self,
        store: WorkflowStore,
        *,
        relay_factory: Callable[[Mapping[str, Any]], R2TransientRelay] | None = None,
        instance_id: str = "cleanup-r2",
    ):
        self.store = store
        self.relay_factory = relay_factory or (lambda config: R2TransientRelay(config))
        self.instance_id = instance_id

    def run_once(self) -> int | None:
        task = self.store.claim(
            "delivery_cleanup_tasks", "delivery_cleanup_task_id", self.instance_id,
            lease_seconds=600,
        )
        if task is None:
            return None
        row = self.store.connection.execute(
            "SELECT d.config_json,r.safe_metadata_json,r.post_attempt_id FROM delivery_cleanup_tasks t "
            "JOIN publication_resources r ON r.publication_resource_id=t.publication_resource_id "
            "JOIN post_attempts a ON a.post_attempt_id=r.post_attempt_id "
            "JOIN post_records pr ON pr.post_record_id=a.post_record_id "
            "JOIN post_requests pq ON pq.post_request_id=pr.post_request_id "
            "JOIN content_packages cp ON cp.content_package_id=pq.content_package_id "
            "JOIN output_requests o ON o.output_request_id=cp.output_request_id "
            "JOIN output_bindings b ON b.output_binding_id=o.output_binding_id "
            "JOIN social_destinations d ON d.social_destination_id=b.social_destination_id "
            "WHERE t.delivery_cleanup_task_id=?", (task["delivery_cleanup_task_id"],),
        ).fetchone()
        if row is None:
            self.store.fail_cleanup(task, "cleanup configuration is missing", retryable=False)
            return int(task["delivery_cleanup_task_id"])
        try:
            config = json.loads(row['config_json'])
            owned = (config.get('adapter_version') == 'instagram_login_v1'
                     or json.loads(row['safe_metadata_json']).get('lifecycle') == 'r2_lifecycle_v1')
            if owned:
                from .resource_lifecycle import cleanup_guard
                identity = cleanup_guard(self.store, task, event='cleanup_started')
                relay_config = {'r2_bucket_name': identity['bucket'], 'r2_account_id': identity['r2_account_id'],
                                'r2_public_domain': identity['public_domain'], 'provider_account_id': identity['provider_account_id'],
                                'destination_key': identity['destination_key']}
                relay = self.relay_factory(relay_config)
                relay.before_io = lambda: cleanup_guard(self.store, task)
                relay.delete_owned(identity, record_event=lambda event: cleanup_guard(self.store, task, event=event))
                cleanup_guard(self.store, task, event='absence_confirmed')
            else:
                self.store.check_cleanup_claim(task)
                relay = self.relay_factory(config)
                relay.before_io = lambda: self.store.check_cleanup_claim(task)
                relay.delete(task['object_key'])
            return self.store.complete_cleanup(task)
        except DeliveryError as error:
            retryable = error.retryable or (owned and error.category in {'r2_deadline', 'r2_unavailable'})
            if owned:
                try:
                    cleanup_guard(self.store, task, event='cleanup_failed')
                except (ValueError, RuntimeError):
                    pass
            try:
                return self.store.fail_cleanup(task, error.detail, retryable=retryable)
            except RuntimeError:
                return int(task['delivery_cleanup_task_id'])
        except Exception as error:
            if (json.loads(row['config_json']).get('adapter_version') == 'instagram_login_v1'
                    or json.loads(row['safe_metadata_json']).get('lifecycle') == 'r2_lifecycle_v1'):
                try:
                    from .resource_lifecycle import cleanup_guard
                    cleanup_guard(self.store, task, event='cleanup_failed')
                except (ValueError, RuntimeError):
                    pass
            try:
                return self.store.fail_cleanup(task, type(error).__name__, retryable=isinstance(error, (OSError, TimeoutError)))
            except RuntimeError:
                return int(task['delivery_cleanup_task_id'])


class PublicationReconciliationWorker:
    """Read-only evidence investigation; never creates a new publishing attempt."""

    def __init__(self, store: WorkflowStore, *, instance_id: str = "publication-reconciliation", reconciler=None):
        self.store = store
        self.instance_id = instance_id
        self.reconciler = reconciler

    def run_once(self) -> int | None:
        request = self.store.claim(
            "reconciliation_requests", "reconciliation_request_id", self.instance_id,
            lease_seconds=600,
        )
        if request is None:
            return None
        if self.reconciler is not None:
            from .instagram_composition import _ReceiptReconciler
            if type(self.reconciler) is not _ReceiptReconciler or self.reconciler.composition.store is not self.store:
                raise DeliveryConfigurationError('registered read-only reconciliation composition required')
            outcome, evidence, receipt = self.reconciler.investigate(request)
            return self.store.record_reconciliation_check(
                request, outcome=outcome, query_version='instagram_receipt_candidate_v1', evidence=evidence, receipt=receipt)
        return self.store.record_reconciliation_check(
            request, outcome="provider_unavailable", query_version="publication_reconciliation_v1",
            evidence={"category": "configuration", "detail": "posting provider reconciliation is not implemented"},
        )



def _r2_object_key(context: Mapping[str, Any], asset: Mapping[str, Any]) -> str:
    post_record_id = int(context["post_record_id"])
    attempt_number = int(context["attempt_number"])
    ordinal = int(asset["ordinal"])
    if post_record_id < 1 or attempt_number < 1 or ordinal < 1:
        raise DeliveryError("validation", "invalid R2 staging identity", False, "r2_upload")
    return (
        f"instagram-transient/{post_record_id}/{attempt_number}/"
        f"{ordinal}-{secrets.token_hex(32)}.jpg"
    )


def _required_setting(config: Mapping[str, Any], key: str) -> str:
    value = config.get(key)
    if not isinstance(value, str) or not value:
        raise DeliveryConfigurationError(f"R2 setting {key} is required")
    return value
