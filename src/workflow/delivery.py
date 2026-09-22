"""Inactive generic delivery orchestration and transient R2 helpers.

The workflow runner does not construct these objects. Provider adapters are
unimplemented; offline boundary tests inject transports and fake adapters.
"""

from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
from time import monotonic, sleep
from typing import Any, Callable, Mapping
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode, urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener
import base64
import json
import os
import secrets

from common.diagnostics import safe_diagnostic

from .store import WorkflowStore


class DeliveryConfigurationError(RuntimeError):
    """Raised before provider work when a required local secret is absent."""


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


class JsonHttpTransport:
    """Bounded HTTPS JSON/form transport with no secret-bearing diagnostics."""

    def __init__(self, *, opener: Any | None = None):
        self.opener = opener or build_opener(_NoRedirect())

    def request_json(
        self,
        method: str,
        url: str,
        *,
        headers: Mapping[str, str] | None = None,
        json_body: Mapping[str, Any] | None = None,
        form: Mapping[str, Any] | None = None,
        timeout: float = 20,
        maximum_bytes: int = 1_000_000,
        stage: str,
    ) -> dict[str, Any]:
        if urlsplit(url).scheme != "https":
            raise DeliveryError("configuration", "provider URL is not HTTPS", False, stage)
        if json_body is not None and form is not None:
            raise ValueError("HTTP request cannot contain JSON and form bodies together")
        body = None
        request_headers = {"Accept": "application/json", "User-Agent": "content-factory/0.1"}
        request_headers.update(headers or {})
        if json_body is not None:
            body = json.dumps(json_body, separators=(",", ":")).encode("utf-8")
            request_headers["Content-Type"] = "application/json"
        elif form is not None:
            body = urlencode(form).encode("utf-8")
            request_headers["Content-Type"] = "application/x-www-form-urlencoded"
        request = Request(url, data=body, headers=request_headers, method=method)
        try:
            with self.opener.open(request, timeout=timeout) as response:
                status = int(getattr(response, "status", 200))
                raw = response.read(maximum_bytes + 1)
                if len(raw) > maximum_bytes:
                    raise DeliveryError("invalid_response", "provider response exceeded limit", False, stage)
        except HTTPError as error:
            raw = error.read(maximum_bytes + 1)
            detail = _provider_error_detail(raw)
            raise DeliveryError(
                _http_category(error.code), detail, error.code == 429 or error.code >= 500, stage
            ) from error
        except (TimeoutError, URLError, OSError) as error:
            raise DeliveryError("transport", type(error).__name__, True, stage) from error
        if status < 200 or status >= 300:
            raise DeliveryError(_http_category(status), f"HTTP {status}", status == 429 or status >= 500, stage)
        try:
            value = json.loads(raw)
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise DeliveryError("invalid_response", "provider returned invalid JSON", False, stage) from error
        if not isinstance(value, dict):
            raise DeliveryError("invalid_response", "provider JSON must be an object", False, stage)
        return value

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
        transport: JsonHttpTransport | None = None,
    ):
        self.config = dict(config)
        self.transport = transport or JsonHttpTransport()
        self.bucket = _required_setting(self.config, "r2_bucket_name")
        self.public_domain = _required_setting(self.config, "r2_public_domain").rstrip("/")
        account_id = _required_setting(self.config, "r2_account_id")
        if urlsplit(self.public_domain).scheme != "https" or urlsplit(self.public_domain).path not in {"", "/"}:
            raise DeliveryConfigurationError("R2 public domain must be an origin-only HTTPS URL")
        if client is None:
            access = os.getenv("R2_ACCESS_KEY_ID")
            secret = os.getenv("R2_SECRET_ACCESS_KEY")
            if not access or not secret:
                raise DeliveryConfigurationError("R2_ACCESS_KEY_ID and R2_SECRET_ACCESS_KEY are required")
            try:
                import boto3
            except ImportError as error:
                raise DeliveryConfigurationError("boto3 is required for R2 delivery") from error
            client = boto3.client(
                "s3",
                endpoint_url=f"https://{account_id}.r2.cloudflarestorage.com",
                aws_access_key_id=access,
                aws_secret_access_key=secret,
                region_name="auto",
            )
        self.client = client

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
        try:
            self.client.put_object(
                Bucket=self.bucket, Key=key, Body=data, ContentType="image/jpeg",
                CacheControl="no-store, max-age=0", Metadata=metadata,
            )
            head = self.client.head_object(Bucket=self.bucket, Key=key)
        except Exception as error:
            raise DeliveryError("r2", type(error).__name__, True, "r2_upload") from error
        returned_metadata = {str(k).casefold(): str(v) for k, v in dict(head.get("Metadata", {})).items()}
        if (
            int(head.get("ContentLength", -1)) != len(data)
            or str(head.get("ContentType", "")).casefold() != "image/jpeg"
            or returned_metadata.get("sha256") != asset["sha256"]
        ):
            raise DeliveryError("r2_verification", "authenticated R2 HEAD mismatch", False, "r2_head")
        public_url = self.public_domain + "/" + quote(key, safe="/")
        fetched = self.transport.get_exact_bytes(
            public_url, expected_bytes=len(data), timeout=20, stage="r2_public_probe"
        )
        if sha256(fetched).hexdigest() != asset["sha256"]:
            raise DeliveryError("r2_verification", "anonymous R2 bytes differ", False, "r2_public_probe")
        return key, public_url

    def delete(self, key: str) -> None:
        try:
            self.client.delete_object(Bucket=self.bucket, Key=key)
            try:
                self.client.head_object(Bucket=self.bucket, Key=key)
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

    def probe(self) -> dict[str, Any]:
        """Perform one explicitly authorized transient put/head/public-get/delete probe."""
        key = "capability-probe/" + secrets.token_hex(32) + ".txt"
        body = secrets.token_bytes(48)
        body_hash = sha256(body).hexdigest()
        try:
            self.client.put_object(
                Bucket=self.bucket, Key=key, Body=body, ContentType="text/plain",
                CacheControl="no-store, max-age=0", Metadata={"sha256": body_hash},
            )
            head = self.client.head_object(Bucket=self.bucket, Key=key)
            if int(head.get("ContentLength", -1)) != len(body):
                raise DeliveryError("r2_verification", "R2 probe HEAD length mismatch", False, "r2_probe")
            public_url = self.public_domain + "/" + quote(key, safe="/")
            fetched = self.transport.get_exact_bytes(
                public_url, expected_bytes=len(body), timeout=20, stage="r2_probe"
            )
            if fetched != body:
                raise DeliveryError("r2_verification", "R2 public probe bytes differ", False, "r2_probe")
            return {"put": True, "head": True, "public_get": True, "delete": True,
                    "probe_sha256": body_hash}
        finally:
            # Cleanup is part of readiness: a destination that cannot remove
            # its transient probe is not ready for unattended staging.
            self.delete(key)


ResourceRecorder = Callable[..., int]


class CredentialedPostingAgent:
    """Post exact reviewed packages; never generate or modify creative."""

    def __init__(
        self,
        store: WorkflowStore,
        *,
        adapters: Mapping[str, Any] | None = None,
        artifact_root: str | Path | None = None,
        instance_id: str = "posting-production",
    ):
        self.store = store
        self.adapters = dict(adapters or {})
        self.instance_id = instance_id
        self.artifact_root = None if artifact_root is None else Path(artifact_root).resolve()

    def run_once(self) -> int | None:
        record = self.store.claim("post_records", "post_record_id", self.instance_id)
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
                    int(resource_id), status=str(values.pop("status")),
                )
            return self.store.record_publication_resource(
                int(context["post_attempt_id"]), **values,
            )
        adapter = self.adapters[context["platform"]]
        try:
            staged = adapter.stage(context, record_resource)
            self.store.mark_attempt_ready(int(context["post_attempt_id"]))
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
            "SELECT d.config_json FROM delivery_cleanup_tasks t "
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
            self.relay_factory(json.loads(row["config_json"])).delete(task["object_key"])
            return self.store.complete_cleanup(task)
        except DeliveryError as error:
            return self.store.fail_cleanup(task, error.detail, retryable=error.retryable)
        except Exception as error:
            return self.store.fail_cleanup(task, type(error).__name__, retryable=False)


class PublicationReconciliationWorker:
    """Perform bounded read-only lookups; never publish or retry a post."""

    def __init__(
        self,
        store: WorkflowStore,
        *,
        transport: JsonHttpTransport | None = None,
        instance_id: str = "publication-reconciliation",
    ):
        self.store = store
        self.transport = transport or JsonHttpTransport()
        self.instance_id = instance_id

    def run_once(self) -> int | None:
        request = self.store.claim(
            "reconciliation_requests", "reconciliation_request_id", self.instance_id,
            lease_seconds=600,
        )
        if request is None:
            return None
        try:
            context = self._context(int(request["post_record_id"]))
            outcome, evidence = self._lookup(context)
        except (DeliveryConfigurationError, DeliveryError) as error:
            outcome = "provider_unavailable"
            evidence = {"category": (
                error.category if isinstance(error, DeliveryError) else "configuration"
            ), "detail": safe_diagnostic(error)}
        except Exception as error:
            outcome = "provider_unavailable"
            evidence = {"category": "unexpected", "detail": type(error).__name__}
        return self.store.record_reconciliation_check(
            request, outcome=outcome, query_version="publication_reconciliation_v1",
            evidence=evidence,
        )

    def _context(self, post_record_id: int) -> dict[str, Any]:
        row = self.store.connection.execute(
            "SELECT o.platform,p.package_json,d.provider_account_id,d.secret_ref,d.config_json,"
            "pr.external_post_id FROM post_records pr "
            "JOIN post_requests pq ON pq.post_request_id=pr.post_request_id "
            "JOIN content_packages p ON p.content_package_id=pq.content_package_id "
            "JOIN output_requests o ON o.output_request_id=p.output_request_id "
            "JOIN output_bindings b ON b.output_binding_id=o.output_binding_id "
            "JOIN social_destinations d ON d.social_destination_id=b.social_destination_id "
            "WHERE pr.post_record_id=? AND pr.status='publication_unknown'", (post_record_id,),
        ).fetchone()
        if row is None:
            raise DeliveryConfigurationError("uncertain publication lineage is missing")
        return {**dict(row), "package": json.loads(row["package_json"]),
                "config": json.loads(row["config_json"])}

    def _lookup(self, context: dict[str, Any]) -> tuple[str, dict[str, Any]]:
        raise DeliveryConfigurationError("posting provider reconciliation is not implemented")


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
        raise DeliveryConfigurationError(f"production setting {key} is required")
    return value


def _http_category(status: int) -> str:
    if status == 401:
        return "authentication"
    if status == 403:
        return "permission"
    if status == 429:
        return "rate_limit"
    if status >= 500:
        return "provider_transient"
    return "provider_rejected"


def _provider_error_detail(raw: bytes) -> str:
    try:
        value = json.loads(raw[:1_000_000])
    except Exception:
        return "provider returned an HTTP error"
    error = value.get("error") if isinstance(value, dict) else None
    if isinstance(error, dict):
        code = error.get("code")
        subcode = error.get("error_subcode")
        return f"provider error code={code!s} subcode={subcode!s}"
    errors = value.get("errors") if isinstance(value, dict) else None
    if isinstance(errors, list) and errors and isinstance(errors[0], dict):
        return f"provider error status={errors[0].get('status')!s} type={errors[0].get('type')!s}"
    return "provider returned an HTTP error"
