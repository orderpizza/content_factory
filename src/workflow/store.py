"""Transactional repository for the current SQLite workflow handoffs."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from contextlib import contextmanager
from hashlib import sha256
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
import json
import re
from PIL import Image, UnidentifiedImageError
from common.diagnostics import safe_diagnostic
from common.operation_log import human_command, emit
from common.gemini import estimated_cost_usd
from common.timestamps import parse_timestamp, serialize_timestamp, utc_now
from .model_budget import ModelBudgetExceeded
from .catalog import DOMAIN_REMITS, WORKFLOW_PIPELINES

from database.current import SchemaError, connect, validate_database

CLAIM_KEYS = {
    "editorial_plan_runs": "editorial_plan_run_id",
    "intake_requests": "intake_request_id", "determination_requests": "determination_request_id",
    "generation_runs": "generation_run_id", "adaptation_runs": "adaptation_run_id",
    "visual_plan_runs": "visual_plan_run_id",
    "storyboard_plan_runs": "storyboard_plan_run_id",
    "render_runs": "render_run_id", "post_records": "post_record_id",
    "delivery_cleanup_tasks": "delivery_cleanup_task_id",
    "reconciliation_requests": "reconciliation_request_id",
}


def now() -> str:
    return utc_now()


def canonical(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def digest(value: Any) -> str:
    return sha256(canonical(value).encode("utf-8")).hexdigest()


def coverage(kind: str, target: str) -> str:
    normalized = " ".join(target.casefold().strip().split())
    return f"coverage:coverage_normalization_v2:{kind.casefold().strip()}:{normalized}"


class WorkflowStore:
    def __init__(
        self,
        path: str | Path,
        *,
        read_only: bool = False,
        catalog_kind: str = "fixture",
        model_budget_policy: Any | None = None,
        enforce_storage: bool = False,
    ):
        if catalog_kind not in {"fixture", "production"}:
            raise ValueError("catalog_kind must be fixture or production")
        self.path = Path(path).resolve()
        if not self.path.is_file():
            raise SchemaError(f"Database does not exist: {self.path}")
        self.connection = connect(self.path, read_only=read_only)
        try:
            validate_database(self.connection)
        except Exception:
            self.connection.close()
            raise
        self.read_only = read_only
        self.catalog_kind = catalog_kind
        self.model_budget_policy = model_budget_policy
        self.enforce_storage = enforce_storage

    def close(self) -> None:
        self.connection.close()

    @contextmanager
    def transaction(self):
        """Serialize command checks and writes, including receipt lookups."""
        if self.read_only:
            raise RuntimeError("read-only dashboard connection")
        self.connection.execute("BEGIN IMMEDIATE")
        with self.connection:
            yield

    def __enter__(self) -> "WorkflowStore":
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    def heartbeat(
        self,
        worker_type: str,
        instance_id: str,
        state: str,
        summary: str,
        *,
        claim_type: str | None = None,
        claim_id: int | None = None,
    ) -> None:
        """Persist one bounded runtime-health row without creating poll history."""
        if self.read_only:
            raise RuntimeError("read-only workflow connection")
        values = (worker_type, instance_id, state)
        if any(not isinstance(value, str) or not value.strip() for value in values):
            raise ValueError("worker heartbeat identifiers and state are required")
        if any(len(value) > 120 for value in values):
            raise ValueError("worker heartbeat identifiers and state are too long")
        if claim_type is not None and (
            not isinstance(claim_type, str) or not claim_type.strip() or len(claim_type) > 120
        ):
            raise ValueError("worker heartbeat claim type is invalid")
        if claim_id is not None and (type(claim_id) is not int or claim_id < 1):
            raise ValueError("worker heartbeat claim ID must be positive")
        moment = now()
        with self.transaction():
            self.connection.execute(
                "INSERT INTO worker_heartbeats "
                "(worker_type,instance_id,started_at,last_seen_at,state,claim_type,claim_id,"
                "build_version,safe_summary,created_at,updated_at) "
                "VALUES (?,?,?,?,?,?,?,'workflow_runtime_v1',?,?,?) "
                "ON CONFLICT(worker_type,instance_id) DO UPDATE SET "
                "last_seen_at=excluded.last_seen_at,state=excluded.state,"
                "claim_type=excluded.claim_type,claim_id=excluded.claim_id,"
                "build_version=excluded.build_version,safe_summary=excluded.safe_summary,"
                "updated_at=excluded.updated_at",
                (
                    worker_type.strip(), instance_id.strip(), moment, moment, state.strip(),
                    claim_type.strip() if claim_type is not None else None, claim_id,
                    safe_diagnostic(summary), moment, moment,
                ),
            )

    def record_worker_result(
        self,
        worker_type: str,
        instance_id: str,
        result_type: str,
        result_id: int,
        *,
        started_at: str,
        summary: str,
        status: str = "completed",
    ) -> int:
        """Append an audit row only when a poll produced a substantive result."""
        if self.read_only:
            raise RuntimeError("read-only workflow connection")
        if any(
            not isinstance(value, str) or not value.strip() or len(value) > 120
            for value in (worker_type, instance_id, result_type)
        ):
            raise ValueError("worker result identifiers are invalid")
        if type(result_id) is not int or result_id < 1:
            raise ValueError("worker result ID must be positive")
        try:
            parsed = parse_timestamp(started_at)
        except (TypeError, ValueError) as error:
            raise ValueError("worker result start time must be ISO-8601") from error
        moment = now()
        with self.transaction():
            return int(self.connection.execute(
                "INSERT INTO worker_runs(worker_type,instance_id,claim_type,claim_id,started_at,"
                "completed_at,status,safe_summary,created_at) "
                "VALUES (?,?,?,?,?,?,?,?,?)",
                (
                    worker_type.strip(), instance_id.strip(), result_type.strip(), result_id,
                    serialize_timestamp(parsed), moment, status, safe_diagnostic(summary), moment,
                ),
            ).lastrowid)

    @human_command('new_idea')
    def create_human_idea(self, body: str, *, command_id: str) -> int:
        if self.read_only:
            raise RuntimeError("read-only dashboard connection")
        body = body.strip()
        if not body or len(body) > 8000:
            raise ValueError("idea must contain 1-8,000 characters")
        moment = now()
        payload_hash = digest({"kind": "new_idea", "body": body})
        with self.transaction():
            receipt = self._command_receipt(command_id)
            if receipt:
                if receipt["payload_hash"] != payload_hash:
                    raise ValueError("command ID was reused with different input")
                return int(receipt["result_record_id"])
            thread = self.connection.execute(
                "INSERT INTO content_threads(origin,status,created_at,updated_at) VALUES ('human','open',?,?)",
                (moment, moment),
            )
            thread_id = int(thread.lastrowid)
            message = self.connection.execute(
                "INSERT INTO thread_messages(thread_id,sequence_number,author_kind,body,created_at) VALUES (?,?, 'human',?,?)",
                (thread_id, 1, body, moment),
            )
            context = {"kind": "human_conversation", "thread_id": thread_id, "message_id": int(message.lastrowid)}
            request = self.connection.execute(
                "INSERT INTO intake_requests(thread_id,context_json,context_version,status,attempt_limit,created_at) VALUES (?,?,'intake_context_v2','pending',3,?)",
                (thread_id, canonical(context), moment),
            )
            self.connection.execute(
                "INSERT INTO human_command_receipts(command_id,command_kind,actor_id,payload_hash,result_record_id,created_at) VALUES (?, 'new_idea','local_owner',?,?,?)",
                (command_id, payload_hash, int(request.lastrowid), moment),
            )
            return int(request.lastrowid)

    @human_command('continue_thread')
    def continue_human_thread(
        self, thread_id: int, body: str, *, command_id: str, expected_row_version: int | None = None
    ) -> int:
        """Append a human reply/revision request and persist the next Intake handoff.

        This is the dashboard's conversational command boundary: it writes only
        a message and an IntakeRequest. It never calls the Intake worker,
        Determination, Gemini, or a content pipeline directly.
        """
        if self.read_only:
            raise RuntimeError("read-only dashboard connection")
        body = body.strip()
        if not body or len(body) > 8000:
            raise ValueError("idea reply must contain 1-8,000 characters")
        if type(expected_row_version) is not int or expected_row_version < 1:
            raise ValueError("a positive displayed thread row version is required")
        moment = now()
        payload_hash = digest({"kind": "continue_thread", "thread_id": thread_id, "body": body, "row_version": expected_row_version})
        with self.transaction():
            receipt = self._command_receipt(command_id)
            if receipt:
                if receipt["payload_hash"] != payload_hash:
                    raise ValueError("command ID was reused with different input")
                return int(receipt["result_record_id"])
            thread = self.connection.execute(
                "SELECT status,row_version FROM content_threads WHERE thread_id=?", (thread_id,)
            ).fetchone()
            if thread is None or thread["status"] != "open":
                raise ValueError("only an open thread can receive an idea refinement")
            if expected_row_version is not None and int(thread["row_version"]) != expected_row_version:
                raise ValueError("thread has changed; refresh before submitting a refinement")
            active = self.connection.execute(
                "SELECT intake_request_id FROM intake_requests WHERE thread_id=? "
                "AND status IN ('pending','claimed','retry_wait')", (thread_id,)
            ).fetchone()
            if active:
                raise ValueError("the current idea message is still being processed")
            sequence = int(self.connection.execute(
                "SELECT COALESCE(MAX(sequence_number),0)+1 FROM thread_messages WHERE thread_id=?", (thread_id,)
            ).fetchone()[0])
            message = self.connection.execute(
                "INSERT INTO thread_messages(thread_id,sequence_number,author_kind,body,created_at) VALUES (?,?, 'human',?,?)",
                (thread_id, sequence, body, moment),
            )
            message_id = int(message.lastrowid)
            context = {
                "kind": "human_conversation", "thread_id": thread_id,
                "last_message_id": message_id, "conversation_version": "thread_messages_v2",
            }
            request = self.connection.execute(
                "INSERT INTO intake_requests(thread_id,context_json,context_version,status,attempt_limit,created_at) VALUES (?,?,'intake_context_v2','pending',3,?)",
                (thread_id, canonical(context), moment),
            )
            self.connection.execute(
                "UPDATE content_threads SET updated_at=?,row_version=row_version+1 WHERE thread_id=?",
                (moment, thread_id),
            )
            self.connection.execute(
                "INSERT INTO human_command_receipts(command_id,command_kind,actor_id,payload_hash,result_record_id,created_at) VALUES (?, 'continue_thread','local_owner',?,?,?)",
                (command_id, payload_hash, int(request.lastrowid), moment),
            )
            return int(request.lastrowid)


    def _command_receipt(self, command_id: str) -> Any | None:
        if not isinstance(command_id, str) or not command_id.strip() or len(command_id) > 200:
            raise ValueError("command ID must contain 1-200 characters")
        return self.connection.execute(
            "SELECT result_record_id,payload_hash FROM human_command_receipts WHERE command_id=?", (command_id,)
        ).fetchone()

    def conversation_snapshot(self, thread_id: int, through_message_id: int | None) -> dict[str, Any]:
        """Return the bounded immutable conversation seen by one Intake request."""
        if through_message_id is None:
            return {"kind": "conversation", "messages": []}
        boundary = self.connection.execute(
            "SELECT sequence_number FROM thread_messages WHERE thread_id=? AND message_id=?",
            (thread_id, through_message_id),
        ).fetchone()
        if boundary is None:
            raise ValueError("Intake request references a message outside its thread")
        rows = self.connection.execute(
            "SELECT message_id,sequence_number,author_kind,body,created_at FROM thread_messages "
            "WHERE thread_id=? AND sequence_number<=? ORDER BY sequence_number",
            (thread_id, boundary["sequence_number"]),
        ).fetchall()
        snapshot = {"kind": "conversation", "through_message_id": through_message_id, "messages": [dict(row) for row in rows]}
        if len(canonical(snapshot)) > 32000:
            raise ValueError("input_too_large: frozen conversation exceeds 32,000 characters")
        return snapshot

    def register_capability(self, pipeline_id: str, *, enabled: bool, generation_ready: bool, outputs: list[dict[str, str | bool]]) -> int:
        """Operator/test-only registration; no account is inferred or enabled by default."""
        if pipeline_id not in WORKFLOW_PIPELINES:
            raise ValueError("unknown pipeline")
        if type(enabled) is not bool or type(generation_ready) is not bool:
            raise ValueError("fixture readiness must be boolean")
        if len(outputs) > 1:
            raise ValueError("a domain has one Instagram destination")
        normalized = []
        for output in outputs:
            allowed = {"platform", "account", "content_format", "output_contract_version", "ready", "safe_reason"}
            if not isinstance(output, dict) or set(output) - allowed:
                raise ValueError("fixture output contains unsupported fields")
            if output.get("platform") not in {"instagram"} or not str(output.get("account", "")).strip():
                raise ValueError("fixture output requires a supported platform and explicit account")
            if not isinstance(output.get("content_format"), str) or not output["content_format"].strip():
                raise ValueError("fixture output requires a format")
            if type(output.get("ready", False)) is not bool:
                raise ValueError("fixture output readiness must be boolean")
            normalized.append({
                "platform": output["platform"], "account": output["account"], "content_format": output["content_format"],
                "output_contract_version": output.get("output_contract_version", "placeholder_v1"),
                "ready": int(output.get("ready", False)), "safe_reason": output.get("safe_reason", "operator fixture"),
            })
        if len({(o["platform"], o["account"], o["content_format"]) for o in normalized}) != len(normalized):
            raise ValueError("duplicate fixture output binding")
        moment = now()
        with self.transaction():
            active = self.connection.execute("SELECT configuration_release_id FROM configuration_activations WHERE scope_key='global' AND status='active'").fetchone()
            if active is None:
                raise RuntimeError("a detection configuration release must be active first")
            prior = self.connection.execute(
                "SELECT * FROM pipeline_capabilities WHERE pipeline_id=? AND pipeline_version='domain_pipeline_catalog_v1' AND configuration_release_id=?",
                (pipeline_id, active[0]),
            ).fetchone()
            if prior:
                bindings = self.connection.execute(
                    "SELECT platform,account,content_format,output_contract_version,ready,safe_reason FROM output_bindings WHERE pipeline_capability_id=?",
                    (prior["pipeline_capability_id"],),
                ).fetchall()
                if (bool(prior["enabled"]) != enabled or bool(prior["generation_ready"]) != generation_ready
                        or sorted(canonical(dict(b)) for b in bindings) != sorted(canonical(b) for b in normalized)):
                    raise ValueError("immutable fixture capability already exists with different input")
                return int(prior["pipeline_capability_id"])
            cur = self.connection.execute(
                "INSERT INTO pipeline_capabilities(pipeline_id,pipeline_version,enabled,remit_json,generation_ready,configuration_release_id,created_at) VALUES (?, 'domain_pipeline_catalog_v1', ?, ?, ?, ?, ?)",
                (pipeline_id, int(enabled), canonical({"development_fixture": True, "description": DOMAIN_REMITS[pipeline_id]}), int(generation_ready), active[0], moment),
            )
            capability_id = int(cur.lastrowid)
            for output in outputs:
                self.connection.execute(
                    "INSERT INTO output_bindings(pipeline_capability_id,platform,account,content_format,output_contract_version,ready,safe_reason,created_at) VALUES (?,?,?,?,?,?,?,?)",
                    (capability_id, output["platform"], output["account"], output["content_format"], output.get("output_contract_version", "placeholder_v1"), int(bool(output.get("ready"))), str(output.get("safe_reason", "operator fixture")), moment),
                )
        return capability_id

    def claim(self, table: str, primary_key: str, worker: str, *, lease_seconds: int = 300) -> Any | None:
        if CLAIM_KEYS.get(table) != primary_key:
            raise ValueError("unsupported claim table")
        if type(lease_seconds) is not int or lease_seconds < 1 or not worker:
            raise ValueError("claim needs a worker and positive lease")
        action = {
            "intake_requests": "planning",
            "determination_requests": "planning",
            "editorial_plan_runs": "planning",
            "generation_runs": "creative",
            "adaptation_runs": "creative",
            "visual_plan_runs": "creative",
            "storyboard_plan_runs": "creative",
            "render_runs": "creative",
            "post_records": "delivery",
            "delivery_cleanup_tasks": "safe_cleanup",
            "reconciliation_requests": "reconciliation",
        }[table]
        if not self._storage_action_allowed(action):
            return None
        moment = now()
        expiry = serialize_timestamp(parse_timestamp(moment) + timedelta(seconds=lease_seconds))
        with self.transaction():
            if table == "post_records":
                self._recover_stale_post_claims(moment)
            # Only the local, no-model scaffold is automatically recoverable.
            # Any model invocation needs a separately audited recovery decision.
            expired = self.connection.execute(
                f"SELECT * FROM {table} WHERE status IN ('claimed','running') AND lease_expires_at<=?",
                (moment,),
            ).fetchall()
            for stale in expired:
                invoked = self.connection.execute(
                    "SELECT 1 FROM model_invocations WHERE entity_type IN (?,?) AND entity_id=? LIMIT 1",
                    (table, primary_key.removesuffix('_id'), stale[primary_key]),
                ).fetchone()
                checkpointed_adaptation = (
                    table == "adaptation_runs"
                    and "adapted_body_json" in stale.keys()
                    and stale["adapted_body_json"] is not None
                    and self.connection.execute(
                        "SELECT 1 FROM model_invocations WHERE phase='adaptation' "
                        "AND entity_type='adaptation_run' AND entity_id=? AND outcome='started'",
                        (stale[primary_key],),
                    ).fetchone() is None
                )
                safe = table != "post_records" and (not invoked or checkpointed_adaptation)
                status = "retry_wait" if safe and stale["attempt_count"] < stale["attempt_limit"] else "failed"
                column = "failure_detail" if table == "intake_requests" else "failure_reason"
                self.connection.execute(
                    f"UPDATE {table} SET status=?,{column}=?,next_attempt_at=?,completed_at=?,claim_version=claim_version+1 WHERE {primary_key}=?",
                    (status, "expired local lease" if safe else "expired claim requires explicit external-history review", moment,
                     None if status == "retry_wait" else moment, stale[primary_key]),
                )
            column = "failure_detail" if table == "intake_requests" else "failure_reason"
            self.connection.execute(
                f"UPDATE {table} SET status='failed',completed_at=?,{column}='attempt limit exhausted' "
                "WHERE status IN ('pending','retry_wait') AND attempt_count>=attempt_limit", (moment,),
            )
            row = self.connection.execute(
                f"SELECT * FROM {table} WHERE status IN ('pending','retry_wait') AND attempt_count<attempt_limit "
                "AND (next_attempt_at IS NULL OR next_attempt_at<=?) "
                + ("AND eligible_at<=? " if table == "post_records" else "")
                + f"ORDER BY created_at,{primary_key} LIMIT 1", (moment, moment) if table == "post_records" else (moment,)
            ).fetchone()
            if row is None:
                return None
            update = self.connection.execute(
                f"UPDATE {table} SET status='claimed',claim_owner=?,claimed_at=?,lease_expires_at=?,claim_version=claim_version+1,attempt_count=attempt_count+1 WHERE {primary_key}=? AND status IN ('pending','retry_wait')",
                (worker, moment, expiry, row[primary_key]),
            )
            if update.rowcount != 1:
                return None
            return self.connection.execute(f"SELECT * FROM {table} WHERE {primary_key}=?", (row[primary_key],)).fetchone()

    def _recover_stale_post_claims(self, moment: str) -> None:
        """Conservatively recover delivery claims before generic pickup."""
        stale = self.connection.execute(
            "SELECT p.*,a.post_attempt_id,a.final_publication_request_sent_at "
            "FROM post_records p LEFT JOIN post_attempts a ON a.post_record_id=p.post_record_id "
            "AND a.attempt_number=p.attempt_count "
            "WHERE p.status IN ('claimed','publishing') AND p.lease_expires_at<=?",
            (moment,),
        ).fetchall()
        for record in stale:
            if record["final_publication_request_sent_at"]:
                self.connection.execute(
                    "UPDATE post_records SET status='publication_unknown',publication_unknown_at=?,"
                    "failure_reason='delivery lease expired after final request marker',completed_at=?,"
                    "claim_version=claim_version+1,row_version=row_version+1 WHERE post_record_id=?",
                    (moment, moment, record["post_record_id"]),
                )
                self.connection.execute(
                    "UPDATE post_attempts SET status='outcome_unknown',failure_category='unknown_after_final',"
                    "failure_detail='delivery lease expired after final request marker',completed_at=? "
                    "WHERE post_attempt_id=? AND status='final_request_sent'",
                    (moment, record["post_attempt_id"]),
                )
                if record["post_attempt_id"] is not None:
                    self.connection.execute(
                        "UPDATE publication_resources SET status='retained',updated_at=? "
                        "WHERE post_attempt_id=? AND resource_type!='r2_object' "
                        "AND status NOT IN ('cleaned','failed')",
                        (moment, record["post_attempt_id"]),
                    )
                    self._schedule_attempt_cleanup(int(record["post_attempt_id"]), moment)
            else:
                status = "retry_wait" if record["attempt_count"] < record["attempt_limit"] else "failed"
                self.connection.execute(
                    "UPDATE post_records SET status=?,failure_reason='delivery lease expired before final request',"
                    "next_attempt_at=?,completed_at=?,claim_version=claim_version+1,row_version=row_version+1 "
                    "WHERE post_record_id=?",
                    (status, moment if status == "retry_wait" else None,
                     moment if status == "failed" else None, record["post_record_id"]),
                )
                if record["post_attempt_id"] is not None:
                    self.connection.execute(
                        "UPDATE post_attempts SET status=?,failure_category='local_interruption',"
                        "failure_detail='delivery lease expired before final request',completed_at=? "
                        "WHERE post_attempt_id=? AND status IN ('created','staging','ready_to_publish')",
                        ("retryable_failed" if status == "retry_wait" else "failed", moment,
                         record["post_attempt_id"]),
                    )
                    self.connection.execute(
                        "UPDATE publication_resources SET status='retained',updated_at=? "
                        "WHERE post_attempt_id=? AND resource_type!='r2_object' "
                        "AND status NOT IN ('cleaned','failed')",
                        (moment, record["post_attempt_id"]),
                    )
                    self._schedule_attempt_cleanup(int(record["post_attempt_id"]), moment)

    def register_production_configuration(self, value: dict[str, Any]) -> int:
        """Materialize one immutable, non-secret production catalog for production."""
        expected = {
            "policy_version", "approved_by", "approved_at", "visual_configuration_approved",
            "destinations", "bindings",
        }
        if not isinstance(value, dict) or set(value) != expected:
            raise ValueError("production configuration has an invalid closed shape")
        if value["policy_version"] != "production_configuration_v2":
            raise ValueError("unsupported production configuration policy")
        if not isinstance(value["approved_by"], str) or not value["approved_by"].strip():
            raise ValueError("production configuration requires an approving actor")
        try:
            approved_at = parse_timestamp(str(value["approved_at"]))
        except (TypeError, ValueError) as error:
            raise ValueError("production configuration approved_at must be ISO-8601") from error
        if type(value["visual_configuration_approved"]) is not bool:
            raise ValueError("visual_configuration_approved must be boolean")
        value = {**value, "approved_at": serialize_timestamp(approved_at)}
        destinations = value["destinations"]
        bindings = value["bindings"]
        if not isinstance(destinations, list) or not destinations:
            raise ValueError("at least one production destination is required")
        if not isinstance(bindings, list) or not bindings:
            raise ValueError("at least one production output binding is required")
        config_hash = digest(value)
        moment = now()
        with self.transaction():
            active = self.connection.execute(
                "SELECT configuration_release_id FROM configuration_activations "
                "WHERE scope_key='global' AND status='active'"
            ).fetchone()
            if active is None:
                raise RuntimeError("an active configuration release is required")
            release_id = int(active[0])
            prior = self.connection.execute(
                "SELECT production_configuration_id,configuration_hash FROM production_configurations "
                "WHERE configuration_release_id=?", (release_id,),
            ).fetchone()
            if prior:
                if prior["configuration_hash"] != config_hash:
                    raise ValueError("active release already has a different immutable production configuration")
                return int(prior["production_configuration_id"])

            configuration_id = int(self.connection.execute(
                "INSERT INTO production_configurations(configuration_release_id,policy_version,"
                "configuration_json,configuration_hash,approved_by,approved_at,created_at) "
                "VALUES (?,?,?,?,?,?,?)",
                (release_id, value["policy_version"], canonical(value), config_hash,
                 value["approved_by"], serialize_timestamp(approved_at), moment),
            ).lastrowid)
            destination_ids: dict[str, int] = {}
            for destination in destinations:
                required = {
                    "destination_key", "platform", "account_key", "provider_account_id",
                    "secret_ref", "enabled", "config", "posting_policy",
                }
                if not isinstance(destination, dict) or set(destination) != required:
                    raise ValueError("production destination has an invalid closed shape")
                if destination["platform"] not in {"instagram"}:
                    raise ValueError("unsupported production platform")
                for key in ("destination_key", "account_key", "provider_account_id", "secret_ref"):
                    if not isinstance(destination[key], str) or not destination[key].strip():
                        raise ValueError(f"production destination requires {key}")
                if type(destination["enabled"]) is not bool or not isinstance(destination["config"], dict):
                    raise ValueError("production destination enabled/config is invalid")
                if destination["destination_key"] != f"{destination['platform']}:{destination['account_key']}":
                    raise ValueError("production destination key must be platform:account_key")
                if not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", destination["account_key"]):
                    raise ValueError("production account key must be a stable local identifier")
                if not re.fullmatch(r"[0-9]{1,30}", destination["provider_account_id"]):
                    raise ValueError("production provider account ID must be numeric")
                if destination["secret_ref"] != "DELIVERY_TOKEN":
                    raise ValueError("inactive delivery boundary requires a generic secret reference")
                config = destination["config"]
                if config != {"adapter_version": "unimplemented"}:
                    raise ValueError("posting provider implementation is outside the current baseline")
                policy = destination["posting_policy"]
                if not isinstance(policy, dict) or set(policy) != {
                    "timezone", "max_posts_per_day", "min_post_interval_minutes",
                    "authorization_ttl_hours",
                }:
                    raise ValueError("posting policy has an invalid closed shape")
                if (
                    type(policy["max_posts_per_day"]) is not int
                    or policy["max_posts_per_day"] < 1
                    or type(policy["min_post_interval_minutes"]) is not int
                    or policy["min_post_interval_minutes"] < 0
                    or type(policy["authorization_ttl_hours"]) is not int
                    or policy["authorization_ttl_hours"] < 1
                ):
                    raise ValueError("posting policy numeric limits are invalid")
                try:
                    ZoneInfo(str(policy["timezone"]))
                except ZoneInfoNotFoundError as error:
                    raise ValueError("posting policy requires a valid IANA timezone") from error
                cursor = self.connection.execute(
                    "INSERT INTO social_destinations(configuration_release_id,destination_key,platform,"
                    "account_key,provider_account_id,secret_ref,enabled,config_json,config_fingerprint,created_at) "
                    "VALUES (?,?,?,?,?,?,?,?,?,?)",
                    (release_id, destination["destination_key"], destination["platform"],
                     destination["account_key"], destination["provider_account_id"],
                     destination["secret_ref"], int(destination["enabled"]),
                     canonical(destination["config"]), digest(destination["config"]), moment),
                )
                destination_id = int(cursor.lastrowid)
                if destination["destination_key"] in destination_ids:
                    raise ValueError("duplicate production destination key")
                destination_ids[destination["destination_key"]] = destination_id
                self.connection.execute(
                    "INSERT INTO posting_policies(social_destination_id,policy_version,timezone_name,"
                    "max_posts_per_day,min_post_interval_minutes,immediate_bypasses_cadence,"
                    "authorization_ttl_hours,created_at) VALUES (?,'posting_policy_v1',?,?,?,0,?,?)",
                    (destination_id, policy["timezone"], policy["max_posts_per_day"],
                     policy["min_post_interval_minutes"], policy["authorization_ttl_hours"], moment),
                )
                readiness = self.connection.execute(
                    "INSERT INTO capability_readiness(social_destination_id,configuration_release_id,status,"
                    "reasons_json,facts_json,checked_at,valid_until,updated_at) "
                    "VALUES (?,?,'unknown',?, '{}',?,?,?)",
                    (destination_id, release_id, canonical(["live readiness has not been checked"]),
                     moment, moment, moment),
                )
                self.connection.execute(
                    "INSERT INTO capability_readiness_checks(capability_readiness_id,status,evidence_json,"
                    "evidence_hash,checked_at) VALUES (?,'unknown',?,?,?)",
                    (int(readiness.lastrowid), canonical({"kind": "configuration_only"}),
                     digest({"kind": "configuration_only"}), moment),
                )

            capability_ids: dict[str, int] = {}
            for pipeline in WORKFLOW_PIPELINES:
                capability_ids[pipeline] = int(self.connection.execute(
                    "INSERT INTO pipeline_capabilities(pipeline_id,pipeline_version,enabled,remit_json,"
                    "generation_ready,configuration_release_id,created_at) "
                    "VALUES (?,'domain_pipeline_catalog_production_v1',1,?,1,?,?)",
                    (pipeline, canonical({"production": True}), release_id, moment),
                ).lastrowid)
            seen: set[tuple[str, str]] = set()
            for binding in bindings:
                required = {"pipeline_id", "destination_key", "content_format"}
                if not isinstance(binding, dict) or set(binding) != required:
                    raise ValueError("production binding has an invalid closed shape")
                pipeline = binding["pipeline_id"]
                destination_key = binding["destination_key"]
                if pipeline not in WORKFLOW_PIPELINES or destination_key not in destination_ids:
                    raise ValueError("production binding references an unknown pipeline or destination")
                pair = (pipeline, destination_key)
                if pair in seen:
                    raise ValueError("duplicate production pipeline/destination binding")
                seen.add(pair)
                destination = next(item for item in destinations if item["destination_key"] == destination_key)
                expected_format = "instagram_static_carousel_v2"
                if binding["content_format"] != expected_format:
                    raise ValueError("production binding format does not match its platform")
                self.connection.execute(
                    "INSERT INTO output_bindings(pipeline_capability_id,platform,account,content_format,"
                    "output_contract_version,ready,safe_reason,created_at,"
                    "social_destination_id,delivery_enabled,visual_configuration_approved) "
                    "VALUES (?,?,?,?,?,1,?,?,?,1,?)",
                    (capability_ids[pipeline], destination["platform"], destination["account_key"],
                     expected_format, expected_format, "production binding; readiness is checked separately",
                     moment, destination_ids[destination_key], int(value["visual_configuration_approved"])),
                )
            expected_pairs = {
                (pipeline, destination["destination_key"])
                for pipeline in WORKFLOW_PIPELINES for destination in destinations
                if destination["enabled"]
            }
            if seen != expected_pairs:
                raise ValueError("production catalog requires every domain/enabled-destination binding")
            return configuration_id

    def catalog(self) -> list[dict[str, Any]]:
        from .catalog import read_catalog
        return read_catalog(self.connection, self.catalog_kind)

    def _cancel_if_closed(self, table: str, row: Any, moment: str) -> bool:
        """Called under the finalization write lock before any child insert."""
        joins = {
            "editorial_plan_runs": "JOIN brief_revisions r ON r.revision_id=q.revision_id JOIN content_threads t ON t.thread_id=r.thread_id",
            "intake_requests": "JOIN content_threads t ON t.thread_id=q.thread_id",
            "determination_requests": "JOIN brief_revisions r ON r.revision_id=q.revision_id JOIN content_threads t ON t.thread_id=r.thread_id",
            "generation_runs": "JOIN content_jobs j ON j.content_job_id=q.content_job_id JOIN brief_revisions r ON r.revision_id=j.brief_revision_id JOIN content_threads t ON t.thread_id=r.thread_id",
            "adaptation_runs": "JOIN output_requests o ON o.output_request_id=q.output_request_id JOIN canonical_contents c ON c.canonical_content_id=o.canonical_content_id JOIN content_jobs j ON j.content_job_id=c.content_job_id JOIN brief_revisions r ON r.revision_id=j.brief_revision_id JOIN content_threads t ON t.thread_id=r.thread_id",
            "visual_plan_runs": "JOIN output_requests o ON o.output_request_id=q.output_request_id JOIN canonical_contents c ON c.canonical_content_id=o.canonical_content_id JOIN content_jobs j ON j.content_job_id=c.content_job_id JOIN brief_revisions r ON r.revision_id=j.brief_revision_id JOIN content_threads t ON t.thread_id=r.thread_id",
            "render_runs": "JOIN content_packages p ON p.content_package_id=q.content_package_id JOIN output_requests o ON o.output_request_id=p.output_request_id JOIN canonical_contents c ON c.canonical_content_id=o.canonical_content_id JOIN content_jobs j ON j.content_job_id=c.content_job_id JOIN brief_revisions r ON r.revision_id=j.brief_revision_id JOIN content_threads t ON t.thread_id=r.thread_id",
            "storyboard_plan_runs": "JOIN content_packages p ON p.content_package_id=q.content_package_id JOIN output_requests o ON o.output_request_id=p.output_request_id JOIN canonical_contents c ON c.canonical_content_id=o.canonical_content_id JOIN content_jobs j ON j.content_job_id=c.content_job_id JOIN brief_revisions r ON r.revision_id=j.brief_revision_id JOIN content_threads t ON t.thread_id=r.thread_id",
        }
        key = CLAIM_KEYS[table]
        thread = self.connection.execute(
            f"SELECT t.status FROM {table} q {joins[table]} WHERE q.{key}=?", (row[key],)
        ).fetchone()
        if thread is None or thread["status"] != "open":
            self._finish_claim(table, key, row, "cancelled", moment, "thread is not open")
            return True
        return False

    def intake_source_snapshot(self, request):
        context = json.loads(request["context_json"])
        if context.get("kind") != "human_conversation":
            raise ValueError("Intake requires a human conversation context")
        snapshot = self.conversation_snapshot(int(request["thread_id"]), context.get("last_message_id") or context.get("message_id"))
        original = self.connection.execute(
            "SELECT source_snapshot_json FROM brief_revisions WHERE thread_id=? AND created_by='system' ORDER BY revision_number LIMIT 1",
            (request["thread_id"],),
        ).fetchone()
        if original:
            snapshot["detection_evidence"] = json.loads(original["source_snapshot_json"])
        return snapshot

    def complete_intake(self, request: Any, brief: dict[str, Any], *, actor_message: str | None = None) -> int:
        moment = now(); thread_id = int(request["thread_id"])
        identity = coverage(str(brief["coverage_kind"]), str(brief["canonical_target"]))
        with self.transaction():
            owned = self.connection.execute("SELECT status,coverage_identity FROM content_threads WHERE thread_id=?", (thread_id,)).fetchone()
            if owned is None or owned["status"] != "open":
                self._finish_claim("intake_requests", "intake_request_id", request, "cancelled", moment, "thread is not open")
                return None
            if owned["coverage_identity"] is not None and owned["coverage_identity"] != identity:
                raise ValueError("a refinement cannot silently change a thread's editorial coverage")
            collision = self.connection.execute("SELECT thread_id FROM content_threads WHERE coverage_identity=?", (identity,)).fetchone()
            if collision and int(collision["thread_id"]) != thread_id:
                sequence = self.connection.execute("SELECT COALESCE(MAX(sequence_number),0)+1 FROM thread_messages WHERE thread_id=?", (thread_id,)).fetchone()[0]
                self.connection.execute(
                    "INSERT INTO thread_messages(thread_id,sequence_number,author_kind,body,created_at) VALUES (?,?,'intake_agent',?,?)",
                    (thread_id, sequence, f"Coverage already belongs to thread #{collision['thread_id']}. Continue that thread; no duplicate revision was created.", moment),
                )
                self._finish_claim("intake_requests", "intake_request_id", request, "completed", moment, None)
                self.connection.execute("UPDATE content_threads SET status='closed',closure_actor='intake_agent',closure_reason='coverage_collision_merged',closed_at=?,updated_at=?,row_version=row_version+1 WHERE thread_id=?", (moment,moment,thread_id))
                return None
            latest = self.connection.execute("SELECT revision_id,revision_number FROM brief_revisions WHERE thread_id=? ORDER BY revision_number DESC LIMIT 1", (thread_id,)).fetchone()
            message_id = None
            if actor_message:
                sequence = int(self.connection.execute("SELECT COALESCE(MAX(sequence_number),0)+1 FROM thread_messages WHERE thread_id=?", (thread_id,)).fetchone()[0])
                message_id = int(self.connection.execute("INSERT INTO thread_messages(thread_id,sequence_number,author_kind,body,created_at) VALUES (?,?, 'intake_agent',?,?)", (thread_id,sequence,actor_message,moment)).lastrowid)
            last_human = self.connection.execute("SELECT message_id FROM thread_messages WHERE thread_id=? AND author_kind='human' ORDER BY sequence_number DESC LIMIT 1", (thread_id,)).fetchone()
            context = json.loads(request["context_json"])
            snapshot = self.intake_source_snapshot(request)
            revision = self.connection.execute(
                "INSERT INTO brief_revisions(thread_id,revision_number,parent_revision_id,input_through_message_id,brief_json,source_snapshot_json,revision_reason,created_by,source_intake_request_id,created_at) VALUES (?,?,?,?,?,?,?,?,?,?)",
                (thread_id, 1 if latest is None else int(latest["revision_number"])+1, None if latest is None else latest["revision_id"], None if last_human is None else last_human[0], canonical(brief), canonical(snapshot), "initial" if latest is None else "human_rework", "intake_agent", request["intake_request_id"], moment),
            )
            revision_id = int(revision.lastrowid)
            self.connection.execute("UPDATE content_threads SET coverage_identity=COALESCE(coverage_identity,?),updated_at=?,row_version=row_version+1 WHERE thread_id=?", (identity,moment,thread_id))
            catalog = self.catalog(); snapshot_value = {
                "brief": brief,
                "source_context": snapshot,
                "catalog": catalog,
                "catalog_version": (
                    "domain_pipeline_catalog_production_v1"
                    if self.catalog_kind == "production" else "domain_pipeline_catalog_v1"
                ),
                "routing_policy_version":"determination_policy_v2",
            }
            self.connection.execute("INSERT INTO determination_requests(revision_id,input_snapshot_json,input_fingerprint,status,attempt_limit,created_at) VALUES (?,?,?,'pending',3,?)", (revision_id,canonical(snapshot_value),digest(snapshot_value),moment))
            self._finish_claim("intake_requests", "intake_request_id", request, "completed", moment, None)
            return revision_id

    def clarify_intake(self, request: Any, question: str) -> None:
        moment = now()
        with self.transaction():
            if self._cancel_if_closed("intake_requests", request, moment):
                return None
            sequence = int(self.connection.execute("SELECT COALESCE(MAX(sequence_number),0)+1 FROM thread_messages WHERE thread_id=?", (request["thread_id"],)).fetchone()[0])
            self.connection.execute("INSERT INTO thread_messages(thread_id,sequence_number,author_kind,body,created_at) VALUES (?,?, 'intake_agent',?,?)", (request["thread_id"],sequence,question,moment))
            self._finish_claim("intake_requests", "intake_request_id", request, "needs_clarification", moment, None)
            self.connection.execute("UPDATE content_threads SET updated_at=?,row_version=row_version+1 WHERE thread_id=?", (moment, request["thread_id"]))

    def _finish_claim(self, table: str, key: str, row: Any, status: str, moment: str, reason: str | None) -> None:
        if CLAIM_KEYS.get(table) != key:
            raise ValueError("unsupported claim table/key")
        reason_column = "failure_detail" if table == "intake_requests" else "failure_reason"
        version_update = ",row_version=row_version+1" if table == "post_records" else ""
        result = self.connection.execute(f"UPDATE {table} SET status=?,completed_at=?,{reason_column}=COALESCE(?,{reason_column}){version_update} WHERE {key}=? AND status='claimed' AND claim_owner=? AND claim_version=? AND lease_expires_at>?", (status,moment,reason,row[key],row["claim_owner"],row["claim_version"],moment))
        if result.rowcount != 1:
            raise RuntimeError("stale claim cannot finalize")

    def fail_claim(self, table: str, key: str, row: Any, reason: str) -> None:
        with self.transaction():
            self._finish_claim(table,key,row,"failed",now(),safe_diagnostic(reason))

    def block_render(self, run: Any, reason: str) -> None:
        """Finish an expected capability stop without an error or paid retry."""
        with self.transaction():
            if self._cancel_if_closed("render_runs", run, now()):
                return
            self._finish_claim("render_runs", "render_run_id", run, "blocked", now(), reason)

    def defer_model_budget_claim(self, table: str, key: str, row: Any, reason: str) -> None:
        """Defer a daily-cap refusal; terminally stop a ContentJob-cap refusal."""
        if CLAIM_KEYS.get(table) != key:
            raise ValueError("unsupported claim table/key")
        moment = now()
        daily = "daily Gemini hard limit" in reason
        if table == 'render_runs' and self.connection.execute(
            "SELECT 1 FROM model_invocations WHERE entity_type='render_run' AND entity_id=? AND outcome!='blocked'",
            (row[key],)).fetchone():
            daily = False
            reason = 'partial storyboard rendering requires fresh manual work; ' + reason
        status = "retry_wait" if daily else "failed"
        retry_at = None
        if daily:
            current = parse_timestamp(moment)
            retry_at = datetime.combine(
                current.date() + timedelta(days=1), datetime.min.time(), tzinfo=timezone.utc,
            )
            retry_at = serialize_timestamp(retry_at)
        reason_column = "failure_detail" if table == "intake_requests" else "failure_reason"
        with self.transaction():
            result = self.connection.execute(
                f"UPDATE {table} SET status=?,next_attempt_at=?,{reason_column}=?,completed_at=? "
                f"WHERE {key}=? AND status='claimed' AND claim_owner=? AND claim_version=? "
                "AND lease_expires_at>?",
                (status, retry_at, safe_diagnostic(reason), None if daily else moment,
                 row[key], row["claim_owner"], row["claim_version"], moment),
            )
            if result.rowcount != 1:
                raise RuntimeError("stale claim cannot record its budget refusal")

    def begin_model_invocation(
        self,
        *,
        phase: str,
        table: str,
        key: str,
        row: Any,
        request_version: str,
        prompt_version: str,
        schema_version: str,
        request_value: Any,
        model_id: str,
        budget_policy: Any | None = None,
        board_index: int | None = None,
    ) -> int:
        """Audit a claimed model operation before making its provider call."""
        policy = budget_policy or self.model_budget_policy
        model_claims = {
            "intake_requests": "intake",
            "determination_requests": "determination",
            "editorial_plan_runs": "editorial_planning",
            "generation_runs": "generation",
            "adaptation_runs": "adaptation",
            "render_runs": "image_rendering",
        }
        if CLAIM_KEYS.get(table) != key or model_claims.get(table) != phase:
            raise ValueError("model invocation requires a supported AI-phase claim")
        if not all(isinstance(value, str) and value for value in (
            phase, request_version, prompt_version, schema_version, model_id,
        )):
            raise ValueError("model invocation versions and model ID are required")
        if len(canonical(request_value)) > 32_000:
            raise ValueError("input_too_large: frozen model input exceeds 32,000 characters")
        moment = now()
        entity_type = key.removesuffix("_id")
        entity_id = int(row[key])
        ordinal = int(row["attempt_count"])
        blocked_reason: str | None = None
        with self.transaction():
            current = self.connection.execute(
                f"SELECT status,claim_owner,claim_version,lease_expires_at FROM {table} WHERE {key}=?",
                (entity_id,),
            ).fetchone()
            if (
                current is None
                or current["status"] != "claimed"
                or current["claim_owner"] != row["claim_owner"]
                or int(current["claim_version"]) != int(row["claim_version"])
                or current["lease_expires_at"] <= moment
            ):
                raise RuntimeError("stale claim cannot start a model invocation")
            if table == "editorial_plan_runs":
                thread = self.connection.execute(
                    "SELECT t.status FROM editorial_plan_runs e JOIN brief_revisions b ON b.revision_id=e.revision_id "
                    "JOIN content_threads t USING(thread_id) WHERE e.editorial_plan_run_id=?",
                    (entity_id,),
                ).fetchone()
                if thread is None or thread["status"] != "open":
                    raise RuntimeError("closed thread cannot start editorial invocation")
            if table == "render_runs":
                history = self.connection.execute(
                    "SELECT * FROM model_invocations WHERE entity_type='render_run' "
                    "AND entity_id=? AND outcome!='blocked' ORDER BY model_invocation_id", (entity_id,),
                ).fetchall()
                if board_index is not None:
                    plan_row = self.connection.execute('SELECT boards_json FROM storyboard_plans WHERE storyboard_plan_id=?',
                        (row['storyboard_plan_id'],)).fetchone()
                    boards = json.loads(plan_row[0])
                    if (type(board_index) is not int or not 1 <= board_index <= len(boards)
                        or request_value.get('board') != boards[board_index - 1]
                        or len(history) != board_index - 1
                        or any(h['outcome'] != 'succeeded' or h['attempt_ordinal'] != i
                               or h['claim_version'] != row['claim_version'] for i, h in enumerate(history, 1))):
                        raise RuntimeError('board invocation must follow the committed plan in one claim')
                    ordinal = board_index
                elif history:
                    raise RuntimeError("image render has external history; create fresh manual work")
            existing = self.connection.execute(
                "SELECT model_invocation_id FROM model_invocations "
                "WHERE phase=? AND entity_type=? AND entity_id=? AND attempt_ordinal=? "
                "AND prompt_version=?" + (" AND outcome!='blocked'" if table == "render_runs" else ""),
                (phase, entity_type, entity_id, ordinal, prompt_version),
            ).fetchone()
            if existing is not None:
                raise RuntimeError("model invocation already exists for this claim attempt")
            job_id = self._model_job_id(table, row)
            budget = None
            if policy is not None:
                input_max, output_max, worst_case = policy.worst_case(phase)
                accounting_day = moment[:10]
                daily_used = int(self.connection.execute(
                    "SELECT COALESCE(SUM(CASE WHEN status='settled' THEN settled_micro_usd "
                    "ELSE worst_case_micro_usd END),0) FROM gemini_budget_reservations "
                    "WHERE accounting_day=? AND status IN ('reserved','settled','uncertain')",
                    (accounting_day,),
                ).fetchone()[0])
                job_used = 0
                if job_id is not None:
                    job_used = int(self.connection.execute(
                        "SELECT COALESCE(SUM(CASE WHEN status='settled' THEN settled_micro_usd "
                        "ELSE worst_case_micro_usd END),0) FROM gemini_budget_reservations "
                        "WHERE content_job_id=? AND status IN ('reserved','settled','uncertain')",
                        (job_id,),
                    ).fetchone()[0])
                if daily_used + worst_case > policy.daily_hard_micro_usd:
                    blocked_reason = "daily Gemini hard limit would be exceeded"
                elif job_id is not None and job_used + worst_case > policy.job_hard_micro_usd:
                    blocked_reason = "ContentJob Gemini hard limit would be exceeded"
                budget = (accounting_day, input_max, output_max, worst_case, job_id)
            invocation = self.connection.execute(
                "INSERT INTO model_invocations("
                "phase,entity_type,entity_id,attempt_ordinal,request_version,prompt_version,"
                "schema_version,request_hash,model_id,outcome,started_at,claim_version"
                ") VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    phase, entity_type, entity_id, ordinal, request_version,
                    prompt_version, schema_version, digest(request_value), model_id,
                    "blocked" if blocked_reason else "started", moment, row["claim_version"],
                ),
            )
            invocation_id = int(invocation.lastrowid)
            if blocked_reason:
                self.connection.execute(
                    "UPDATE model_invocations SET safe_error=?,completed_at=? WHERE model_invocation_id=?",
                    (blocked_reason, moment, invocation_id),
                )
            elif budget is not None:
                accounting_day, input_max, output_max, worst_case, job_id = budget
                self.connection.execute(
                    "INSERT INTO gemini_budget_reservations(accounting_day,model_invocation_id,claim_type,"
                    "claim_id,worst_case_micro_usd,status,created_at,content_job_id,phase,price_snapshot_hash,"
                    "max_input_tokens,max_output_tokens,daily_limit_micro_usd,daily_warning_micro_usd,"
                    "job_limit_micro_usd) VALUES (?,?,?,?,?,'reserved',?,?,?,?,?,?,?,?,?)",
                    (accounting_day, invocation_id, entity_type, entity_id, worst_case, moment,
                     job_id, phase, policy.fingerprint, input_max, output_max,
                     policy.daily_hard_micro_usd,
                     policy.daily_warning_micro_usd,
                     policy.job_hard_micro_usd),
                )
        if blocked_reason:
            raise ModelBudgetExceeded(blocked_reason)
        return invocation_id

    def _model_job_id(self, table: str, row: Any) -> int | None:
        if table == "generation_runs":
            return int(row["content_job_id"])
        if table == "render_runs":
            found = self.connection.execute(
                "SELECT c.content_job_id FROM content_packages p "
                "JOIN output_requests o ON o.output_request_id=p.output_request_id "
                "JOIN canonical_contents c ON c.canonical_content_id=o.canonical_content_id "
                "WHERE p.content_package_id=?", (row["content_package_id"],),
            ).fetchone()
            return None if found is None else int(found[0])
        if table == "adaptation_runs":
            found = self.connection.execute(
                "SELECT c.content_job_id FROM output_requests o "
                "JOIN canonical_contents c ON c.canonical_content_id=o.canonical_content_id "
                "WHERE o.output_request_id=?", (row["output_request_id"],),
            ).fetchone()
            return None if found is None else int(found[0])
        return None

    def finish_model_invocation(
        self,
        invocation_id: int,
        *,
        outcome: str,
        usage: Any | None = None,
        response_value: Any | None = None,
        error: str | None = None,
        budget_policy: Any | None = None,
    ) -> None:
        """Settle safe response metadata without retaining prompts or raw responses."""
        policy = budget_policy or self.model_budget_policy
        if outcome not in {"succeeded", "transport_failed", "invalid_output", "parse_failed", "schema_failed", "blocked"}:
            raise ValueError("invalid terminal model invocation outcome")
        input_tokens = None if usage is None else int(getattr(usage, "input_tokens", 0) or 0)
        output_tokens = None if usage is None else int(getattr(usage, "output_tokens", 0) or 0)
        total_tokens = None if usage is None else int(getattr(usage, "total_tokens", 0) or 0)
        estimate = None if usage is None else estimated_cost_usd(usage)
        if usage is not None and policy is not None:
            estimated_cost_micro_usd = policy.actual_cost(
                input_tokens or 0, output_tokens or 0
            )
        else:
            estimated_cost_micro_usd = 0 if estimate is None else max(0, int(round(estimate * 1_000_000)))
        response_hash = None if response_value is None else digest(response_value)
        model_id = None if usage is None else str(getattr(usage, "model", "") or "") or None
        with self.transaction():
            result = self.connection.execute(
                "UPDATE model_invocations SET outcome=?,model_id=COALESCE(?,model_id),"
                "response_hash=?,input_tokens=?,output_tokens=?,total_tokens=?,"
                "estimated_cost_micro_usd=?,safe_error=?,completed_at=? "
                "WHERE model_invocation_id=? AND outcome='started'",
                (
                    outcome, model_id, response_hash, input_tokens, output_tokens,
                    total_tokens, estimated_cost_micro_usd,
                    None if error is None else safe_diagnostic(error), now(), invocation_id,
                ),
            )
            if result.rowcount != 1:
                raise RuntimeError("model invocation is missing or already finalized")
            reservation = self.connection.execute(
                "SELECT gemini_budget_reservation_id FROM gemini_budget_reservations "
                "WHERE model_invocation_id=?", (invocation_id,),
            ).fetchone()
            if reservation is not None:
                if usage is None:
                    self.connection.execute(
                        "UPDATE gemini_budget_reservations SET status='uncertain',settled_at=? "
                        "WHERE gemini_budget_reservation_id=? AND status='reserved'",
                        (now(), reservation[0]),
                    )
                else:
                    self.connection.execute(
                        "UPDATE gemini_budget_reservations SET status='settled',settled_micro_usd=?,settled_at=? "
                        "WHERE gemini_budget_reservation_id=? AND status='reserved'",
                        (estimated_cost_micro_usd, now(), reservation[0]),
                    )

        invocation = self.connection.execute('SELECT phase,entity_id,model_id,started_at,completed_at FROM model_invocations WHERE model_invocation_id=?', (invocation_id,)).fetchone()
        emit(invocation['phase'], 'model_result', operation_id=invocation_id,
             request_id=invocation['entity_id'], model_id=invocation['model_id'], outcome=outcome,
             input_tokens=input_tokens, output_tokens=output_tokens, total_tokens=total_tokens,
             cost_micro_usd=estimated_cost_micro_usd if usage else None,
             duration_ms=round((parse_timestamp(invocation['completed_at'])-parse_timestamp(invocation['started_at'])).total_seconds()*1000),
             error_code=outcome if error else None)

    def record_decision(self, request: Any, decision: dict[str, Any]) -> int:
        moment = now(); routes = decision["routes"]
        if {item["pipeline_id"] for item in routes} != set(WORKFLOW_PIPELINES) or len(routes) != len(WORKFLOW_PIPELINES):
            raise ValueError("determination must persist exactly three routes")
        selected = any(item["disposition"] == "selected" for item in routes)
        expected = "accepted" if selected else ("blocked" if any(item["disposition"] == "blocked" for item in routes) else "not_recommended")
        if decision["outcome"] != expected:
            raise ValueError("aggregate outcome contradicts route dispositions")
        frozen_catalog = json.loads(request["input_snapshot_json"])["catalog"]
        if decision["catalog"] != frozen_catalog:
            raise ValueError("decision catalog differs from frozen request")
        for route in routes:
            if not isinstance(route.get("fit"), str) or not route["fit"].strip():
                raise ValueError("every determination route requires a fit assessment")
            if not isinstance(route.get("reason"), str) or not route["reason"].strip():
                raise ValueError("every determination route requires a reason")
            if route["disposition"] not in {"selected", "skipped", "blocked"}:
                raise ValueError("unsupported route disposition")
            cap = next((c for c in frozen_catalog if c["pipeline_id"] == route["pipeline_id"]), None)
            outputs = route.get("outputs", [])
            if not isinstance(outputs, list):
                raise ValueError("route outputs must be a list")
            if cap is None and outputs:
                raise ValueError("route output is not present in the frozen catalog")
            if cap is not None and any(o not in cap["outputs"] or not o["ready"] for o in outputs):
                raise ValueError("route output is not ready in the frozen catalog")
            if route["disposition"] == "selected":
                if not cap or not cap["enabled"] or not cap["generation_ready"] or not outputs:
                    raise ValueError("selected route lacks ready frozen capability")
                if len(outputs) > 1 or len({o["platform"] for o in outputs}) != len(outputs):
                    raise ValueError("output plan allows at most one output per platform")
        with self.transaction():
            if self._cancel_if_closed("determination_requests", request, moment):
                return None
            existing = self.connection.execute("SELECT determination_decision_id FROM determination_decisions WHERE determination_request_id=?", (request["determination_request_id"],)).fetchone()
            if existing:
                self._finish_claim("determination_requests","determination_request_id",request,"completed",moment,None)
                return int(existing[0])
            request_snapshot = json.loads(request["input_snapshot_json"])
            revision = self.connection.execute("SELECT r.*,t.coverage_identity FROM brief_revisions r JOIN content_threads t ON t.thread_id=r.thread_id WHERE r.revision_id=?", (request["revision_id"],)).fetchone()
            cur = self.connection.execute("INSERT INTO determination_decisions(determination_request_id,outcome,opportunity_value,rationale,warnings_json,coverage_identity,catalog_fingerprint,readiness_fingerprint,routing_policy_version,created_at) VALUES (?,?,?,?,?,?,?,?,?,?)", (request["determination_request_id"],decision["outcome"],decision["opportunity_value"],decision["rationale"],canonical(decision.get("warnings",[])),revision["coverage_identity"],digest(decision["catalog"]),digest(decision["catalog"]),"determination_policy_v2",moment))
            decision_id=int(cur.lastrowid)
            for route in routes:
                route_cur=self.connection.execute("INSERT INTO determination_routes(determination_decision_id,pipeline_id,disposition,fit,reason,evidence_json,output_assessments_json,created_at) VALUES (?,?,?,?,?,?,?,?)", (decision_id,route["pipeline_id"],route["disposition"],route["fit"],route["reason"],canonical(route.get("evidence",[])),canonical(route.get("outputs",[])),moment))
                if route["disposition"] == "selected":
                    from .editorial_planning import freeze_input
                    snapshot = freeze_input(self.connection, revision, request_snapshot, route, int(route_cur.lastrowid), moment)
                    self.connection.execute(
                        "INSERT INTO editorial_plan_runs(determination_route_id,revision_id,pipeline_id,input_snapshot_json,input_fingerprint,status,attempt_limit,created_at) VALUES (?,?,?,?,?,'pending',3,?)",
                        (route_cur.lastrowid, revision["revision_id"], route["pipeline_id"], canonical(snapshot), digest(snapshot), moment),
                    )
            self._finish_claim("determination_requests","determination_request_id",request,"completed",moment,None)
            return decision_id

    def complete_editorial_plan(self, run: Any, value: dict[str, Any], *, planner_version: str) -> int | None:
        from .editorial_planning import validate_plan
        persisted = self.connection.execute("SELECT * FROM editorial_plan_runs WHERE editorial_plan_run_id=?", (run["editorial_plan_run_id"],)).fetchone()
        for field in ("determination_route_id", "revision_id", "pipeline_id", "input_snapshot_json", "input_fingerprint"):
            if persisted is None or persisted[field] != run[field]:
                raise ValueError("editorial input lineage mismatch")
        snapshot = json.loads(run["input_snapshot_json"])
        if digest(snapshot) != run["input_fingerprint"] or snapshot["brief_revision_id"] != run["revision_id"] or snapshot["determination_route_id"] != run["determination_route_id"] or snapshot["domain"] != run["pipeline_id"]:
            raise ValueError("editorial input fingerprint/lineage mismatch")
        if not isinstance(planner_version, str) or not planner_version.strip():
            raise ValueError("planner version is required")
        validate_plan(value, snapshot)
        moment = now()
        with self.transaction():
            if self._cancel_if_closed("editorial_plan_runs", run, moment):
                return None
            plan = {**value, "schema_version": "editorial_plan_v1", "planner_version": planner_version,
                    "brief_revision_id": run["revision_id"], "determination_route_id": run["determination_route_id"],
                    "input_fingerprint": run["input_fingerprint"], "history": snapshot["history"]}
            plan_id = int(self.connection.execute(
                "INSERT INTO editorial_plans(editorial_plan_run_id,determination_route_id,brief_revision_id,pipeline_id,lane,schema_version,planner_version,input_fingerprint,plan_json,created_at) VALUES (?,?,?,?,?,'editorial_plan_v1',?,?,?,?)",
                (run["editorial_plan_run_id"],run["determination_route_id"],run["revision_id"],run["pipeline_id"],value["lane"],planner_version,run["input_fingerprint"],canonical(plan),moment),
            ).lastrowid)
            selected = next(c for c in value["candidates"] if c["candidate_id"] == value["selected_candidate_id"])
            recipe = {"brief": snapshot["brief"], "pipeline_id": run["pipeline_id"],
                      "source_context": snapshot["source_context"], "outputs": snapshot["outputs"],
                      "editorial_plan": plan, "editorial_plan_id": plan_id,
                      "angle": {"angle_kind": selected["angle_type"], "canonical_target": snapshot["brief"]["canonical_target"],
                                "thesis": selected["angle"], "audience": value["audience_intent"], "reader_value": selected["reader_promise"]}}
            job = int(self.connection.execute(
                "INSERT INTO content_jobs(editorial_plan_id,determination_route_id,brief_revision_id,pipeline_id,content_identity,recipe_json,output_plan_json,priority,created_at) VALUES (?,?,?,?,?,?,?,50,?)",
                (plan_id,run["determination_route_id"],run["revision_id"],run["pipeline_id"],digest(recipe),canonical(recipe),canonical(snapshot["outputs"]),moment),
            ).lastrowid)
            self.connection.execute("INSERT INTO generation_runs(content_job_id,run_number,status,attempt_limit,created_at) VALUES (?,1,'pending',2,?)", (job,moment))
            self._finish_claim("editorial_plan_runs","editorial_plan_run_id",run,"succeeded",moment,None)
            return plan_id

    def create_canonical(self, run: Any, value: dict[str, Any]) -> int:
        moment=now()
        with self.transaction():
            if self._cancel_if_closed("generation_runs", run, moment):
                return None
            job=self.connection.execute("SELECT * FROM content_jobs WHERE content_job_id=?",(run["content_job_id"],)).fetchone()
            existing=self.connection.execute("SELECT canonical_content_id FROM canonical_contents WHERE content_job_id=?",(job["content_job_id"],)).fetchone()
            if existing:
                self._finish_claim("generation_runs","generation_run_id",run,"succeeded",moment,None); return int(existing[0])
            identity=digest({"job":job["content_identity"],"body":value})
            canonical_id=int(self.connection.execute("INSERT INTO canonical_contents(content_job_id,generation_run_id,canonical_identity,canonical_json,canonical_hash,schema_version,created_at) VALUES (?,?,?,?,?,'canonical_content_v1',?)",(job["content_job_id"],run["generation_run_id"],identity,canonical(value),digest(value),moment)).lastrowid)
            for output in json.loads(job["output_plan_json"]):
                input_value={"canonical_content_id":canonical_id,"output":output}
                out=int(self.connection.execute("INSERT INTO output_requests(canonical_content_id,output_binding_id,platform,account,content_format,output_identity,output_contract_version,input_json,created_at) VALUES (?,?,?,?,?,?,?,?,?)",(canonical_id,output.get("output_binding_id"),output["platform"],output["account"],output["content_format"],digest(input_value),output.get("output_contract_version","placeholder_v1"),canonical(input_value),moment)).lastrowid)
                self.connection.execute("INSERT INTO visual_plan_runs(output_request_id,run_number,status,attempt_limit,created_at) VALUES (?,1,'pending',2,?)",(out,moment))
            self._finish_claim("generation_runs","generation_run_id",run,"succeeded",moment,None)
            return canonical_id

    def create_package(self, run: Any, package: dict[str, Any]) -> int:
        moment=now()
        with self.transaction():
            if self._cancel_if_closed("adaptation_runs", run, moment):
                return None
            output=self.connection.execute("SELECT * FROM output_requests WHERE output_request_id=?",(run["output_request_id"],)).fetchone()
            prior=self.connection.execute("SELECT content_package_id FROM content_packages WHERE output_request_id=?",(output["output_request_id"],)).fetchone()
            if prior:
                self._finish_claim("adaptation_runs","adaptation_run_id",run,"succeeded",moment,None); return int(prior[0])
            from .active_visual_profiles import validate_recipe, validate_archetype_units
            from .visual_cues import validate_cues
            selected = self.connection.execute("SELECT recipe_json FROM visual_recipes WHERE visual_recipe_id=? AND output_request_id=?",
                (run["visual_recipe_id"], output["output_request_id"])).fetchone()
            if selected is None:
                raise ValueError("adaptation requires its preselected recipe")
            recipe = validate_recipe(json.loads(selected[0]))
            if package.get("archetype_id") != recipe["archetype_id"] or package.get("account") != recipe["account"]:
                raise ValueError("adaptation cannot change the selected archetype/account")
            validate_archetype_units(package["visual_units"], recipe["archetype_id"])
            canonical_content = json.loads(self.connection.execute("SELECT canonical_json FROM canonical_contents WHERE canonical_content_id=?",
                (output["canonical_content_id"],)).fetchone()[0])
            cues = validate_cues(package.get("visual_cues"), {c['claim_id'] for c in canonical_content.get('claims', [])}, package["visual_units"])
            package_id = int(self.connection.execute(
                "INSERT INTO content_packages(output_request_id,adaptation_run_id,visual_recipe_id,package_json,content_hash,visual_cues_json,created_at) VALUES (?,?,?,?,?,?,?)",
                (output["output_request_id"], run["adaptation_run_id"], run["visual_recipe_id"], canonical(package), digest(package), canonical(cues), moment)).lastrowid)
            self.connection.execute("INSERT INTO storyboard_plan_runs(content_package_id,status,attempt_limit,created_at) VALUES (?,'pending',2,?)",
                (package_id, moment))
            self._finish_claim("adaptation_runs", "adaptation_run_id", run, "succeeded", moment, None)
            return package_id

    def create_storyboard_plan(self, run):
        from .storyboard_planner import make_plan
        from .active_visual_profiles import validate_archetype_units
        moment = now()
        with self.transaction():
            if self._cancel_if_closed('storyboard_plan_runs', run, moment):
                return None
            row = self.connection.execute(
                'SELECT p.*,j.pipeline_id FROM content_packages p JOIN output_requests o USING(output_request_id) '
                'JOIN canonical_contents c USING(canonical_content_id) JOIN content_jobs j USING(content_job_id) '
                'WHERE p.content_package_id=?', (run['content_package_id'],)).fetchone()
            package = json.loads(row['package_json'])
            validate_archetype_units(package['visual_units'], package['archetype_id'])
            plan = make_plan(len(package['visual_units']), row['pipeline_id'])
            plan_id = self.connection.execute(
                'INSERT INTO storyboard_plans(storyboard_plan_run_id,content_package_id,output_request_id,'
                'visual_recipe_id,schema_version,planner_version,total_slides,boards_json,created_at) VALUES (?,?,?,?,?,?,?,?,?)',
                (run['storyboard_plan_run_id'], row['content_package_id'], row['output_request_id'], row['visual_recipe_id'],
                 plan['schema_version'], plan['planner_version'], plan['total_slides'], canonical(plan['boards']), moment)).lastrowid
            self.connection.execute(
                "INSERT INTO render_runs(storyboard_plan_id,content_package_id,visual_recipe_id,run_number,status,attempt_limit,created_at) VALUES (?,?,?,1,'pending',2,?)",
                (plan_id, row['content_package_id'], row['visual_recipe_id'], moment))
            self._finish_claim('storyboard_plan_runs', 'storyboard_plan_run_id', run, 'succeeded', moment, None)
            return plan_id

    def create_visual_recipe(self, run: Any) -> int:
        """Select under the write lock, freeze history and recipe, then hand off adaptation."""
        from .active_visual_profiles import active_recipe, validate_recipe
        from .archetype_selection import HISTORY_LIMIT, select_archetype
        moment = now()
        with self.transaction():
            if self._cancel_if_closed("visual_plan_runs", run, moment):
                return None
            prior = self.connection.execute("SELECT visual_recipe_id FROM visual_recipes WHERE output_request_id=?", (run["output_request_id"],)).fetchone()
            if prior:
                self._finish_claim("visual_plan_runs", "visual_plan_run_id", run, "succeeded", moment, None)
                return int(prior[0])
            output = self.connection.execute(
                "SELECT o.*,c.canonical_json,c.canonical_hash,j.pipeline_id,b.account binding_account,b.platform binding_platform,pc.pipeline_id binding_domain "
                "FROM output_requests o JOIN canonical_contents c USING(canonical_content_id) "
                "JOIN content_jobs j USING(content_job_id) JOIN output_bindings b USING(output_binding_id) "
                "JOIN pipeline_capabilities pc USING(pipeline_capability_id) WHERE o.output_request_id=?",
                (run["output_request_id"],)).fetchone()
            if (output is None or output['platform'] != 'instagram'
                or output['content_format'] != 'instagram_static_carousel_v2'
                or output['binding_domain'] != output['pipeline_id']
                or output['binding_account'] != output['account'] or output['binding_platform'] != output['platform']):
                raise ValueError("visual planner requires an eligible frozen account/domain binding")
            rows = self.connection.execute(
                "SELECT v.visual_recipe_id,v.recipe_json FROM visual_recipes v JOIN output_requests o USING(output_request_id) "
                "WHERE o.platform=? AND o.account=? ORDER BY v.visual_recipe_id DESC LIMIT ?",
                (output['platform'], output['account'], HISTORY_LIMIT)).fetchall()
            history = [{'visual_recipe_id': r['visual_recipe_id'], 'archetype_id': json.loads(r['recipe_json'])['archetype_id']} for r in rows]
            archetype_id, selection = select_archetype(json.loads(output['canonical_json']), output['pipeline_id'], history)
            recipe = validate_recipe(active_recipe(output['pipeline_id'], account=output['account'], archetype_id=archetype_id, selection=selection))
            provenance = {'canonical_hash': output['canonical_hash'], 'output_request_id': output['output_request_id'],
                          'output_binding_id': output['output_binding_id'], 'pipeline_id': output['pipeline_id'],
                          'account': output['account'], **selection}
            recipe_id = int(self.connection.execute(
                "INSERT INTO visual_recipes(output_request_id,visual_plan_run_id,recipe_json,recipe_hash,selection_provenance_json,created_at) VALUES (?,?,?,?,?,?)",
                (run["output_request_id"], run["visual_plan_run_id"], canonical(recipe), digest(recipe), canonical(provenance), moment)).lastrowid)
            self.connection.execute("INSERT INTO adaptation_runs(output_request_id,visual_recipe_id,run_number,status,attempt_limit,created_at) VALUES (?,?,1,'pending',2,?)", (run["output_request_id"], recipe_id, moment))
            self._finish_claim("visual_plan_runs", "visual_plan_run_id", run, "succeeded", moment, None)
            return recipe_id

    def complete_render(
        self,
        run: Any,
        manifest: dict[str, Any],
        assets: dict[str, Any] | list[dict[str, Any]],
    ) -> int:
        moment=now(); manifest_json=canonical(manifest); manifest_hash=digest(manifest)
        with self.transaction():
            if self._cancel_if_closed("render_runs", run, moment):
                return None
            prior=self.connection.execute("SELECT review_request_id FROM review_requests WHERE render_run_id=?",(run["render_run_id"],)).fetchone()
            if prior:
                self._finish_claim("render_runs","render_run_id",run,"succeeded",moment,None); return int(prior[0])
            asset_list = [assets] if isinstance(assets, dict) else assets
            if manifest.get('review_only') is True:
                plan = self.connection.execute('SELECT total_slides FROM storyboard_plans WHERE storyboard_plan_id=?',
                    (run['storyboard_plan_id'],)).fetchone()
                if (manifest.get('storyboard_plan_id') != run['storyboard_plan_id']
                    or [a.get('ordinal') for a in asset_list] != list(range(1, plan[0] + 1))
                    or any((a.get('width'), a.get('height'), a.get('role')) != (1080, 1350, 'preview_png') for a in asset_list)):
                    raise ValueError('review assets must match the complete ordered storyboard plan')
            if not asset_list:
                raise ValueError("a successful render requires at least one asset")
            for position, asset in enumerate(asset_list, start=1):
                values = (
                    run["render_run_id"], asset["role"],
                    int(asset.get("ordinal", position)), asset["path"], asset["mime"],
                    asset["width"], asset["height"], asset["bytes"],
                    asset["sha256"], moment,
                )
                self.connection.execute(
                    "INSERT INTO render_assets(render_run_id,asset_role,ordinal,local_path,mime_type,"
                    "width,height,bytes,sha256,created_at,encoder_version) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                    values + (str(manifest.get("pillow_version") or manifest.get("renderer") or "unknown"),),
                )
            self.connection.execute("UPDATE render_runs SET manifest_json=? WHERE render_run_id=?",(manifest_json,run["render_run_id"]))
            package=self.connection.execute("SELECT p.content_package_id,p.content_hash FROM content_packages p JOIN render_runs r ON r.content_package_id=p.content_package_id WHERE r.render_run_id=?",(run["render_run_id"],)).fetchone()
            expires=serialize_timestamp(parse_timestamp(moment)+timedelta(days=14))
            destination = self.connection.execute(
                "SELECT d.destination_key FROM render_runs rr "
                "JOIN content_packages cp ON cp.content_package_id=rr.content_package_id "
                "JOIN output_requests o ON o.output_request_id=cp.output_request_id "
                "LEFT JOIN output_bindings b ON b.output_binding_id=o.output_binding_id "
                "LEFT JOIN social_destinations d ON d.social_destination_id=b.social_destination_id "
                "WHERE rr.render_run_id=?", (run["render_run_id"],),
            ).fetchone()
            review=int(self.connection.execute(
                "INSERT INTO review_requests(content_package_id,render_run_id,review_cycle_number,"
                "package_hash,manifest_hash,status,expires_at,created_at,destination_key) "
                "VALUES (?,?,1,?,?,'awaiting_review',?,?,?)",
                (package["content_package_id"],run["render_run_id"],package["content_hash"],
                 manifest_hash,expires,moment,None if destination is None else destination[0]),
            ).lastrowid)
            self._finish_claim("render_runs","render_run_id",run,"succeeded",moment,None); return review

    def decide_review(
        self,
        review_id: int,
        *,
        decision: str,
        note: str,
        row_version: int,
        command_id: str,
    ) -> int:
        """Record editorial acceptance/rejection without authorizing delivery."""
        if decision not in {"approved", "rejected"}:
            raise ValueError("review decision must be approved or rejected")
        if type(row_version) is not int or row_version < 1:
            raise ValueError("a positive displayed review row version is required")
        note = note.strip()
        if len(note) > 2000:
            raise ValueError("review note must contain at most 2,000 characters")
        if decision == "rejected" and not note:
            raise ValueError("a rejection requires a review note")
        payload_hash = digest({
            "kind": "review_decision", "review_id": review_id,
            "decision": decision, "note": note, "row_version": row_version,
        })
        moment = now()
        with self.transaction():
            receipt = self._command_receipt(command_id)
            if receipt:
                if receipt["payload_hash"] != payload_hash:
                    raise ValueError("command ID was reused with different input")
                return int(receipt["result_record_id"])
            review = self.connection.execute(
                "SELECT status,row_version,expires_at FROM review_requests WHERE review_request_id=?",
                (review_id,),
            ).fetchone()
            if review is None:
                raise ValueError("review request does not exist")
            if review["status"] != "awaiting_review":
                raise ValueError("only an awaiting review can be decided")
            if int(review["row_version"]) != row_version:
                raise ValueError("review has changed; refresh before submitting a decision")
            if review["expires_at"] <= moment:
                raise ValueError("review has expired; refresh before continuing")
            result = self.connection.execute(
                "UPDATE review_requests SET status=?,decision_note=?,actor_id='local_owner',"
                "decided_at=?,row_version=row_version+1 WHERE review_request_id=? "
                "AND status='awaiting_review' AND row_version=?",
                (decision, note or None, moment, review_id, row_version),
            )
            if result.rowcount != 1:
                raise RuntimeError("stale review command cannot finalize")
            self.connection.execute(
                "INSERT INTO human_command_receipts(command_id,command_kind,actor_id,payload_hash,result_record_id,created_at) "
                "VALUES (?,?,'local_owner',?,?,?)",
                (command_id, f"review_{decision}", payload_hash, review_id, moment),
            )
            return review_id

    def request_review_changes(
        self,
        review_id: int,
        *,
        note: str,
        row_version: int,
        command_id: str,
    ) -> int:
        """Close one review and enqueue its human feedback through Intake."""
        if type(row_version) is not int or row_version < 1:
            raise ValueError("a positive displayed review row version is required")
        note = note.strip()
        if not note or len(note) > 2000:
            raise ValueError("change feedback must contain 1-2,000 characters")
        payload_hash = digest({
            "kind": "review_changes", "review_id": review_id,
            "note": note, "row_version": row_version,
        })
        moment = now()
        with self.transaction():
            receipt = self._command_receipt(command_id)
            if receipt:
                if receipt["payload_hash"] != payload_hash:
                    raise ValueError("command ID was reused with different input")
                return int(receipt["result_record_id"])
            context = self.connection.execute(
                "SELECT v.status,v.row_version,v.expires_at,p.content_package_id,o.output_request_id,"
                "o.platform,o.account,o.content_format,r.thread_id,t.status thread_status "
                "FROM review_requests v "
                "JOIN content_packages p ON p.content_package_id=v.content_package_id "
                "JOIN output_requests o ON o.output_request_id=p.output_request_id "
                "JOIN canonical_contents c ON c.canonical_content_id=o.canonical_content_id "
                "JOIN content_jobs j ON j.content_job_id=c.content_job_id "
                "JOIN brief_revisions r ON r.revision_id=j.brief_revision_id "
                "JOIN content_threads t ON t.thread_id=r.thread_id "
                "WHERE v.review_request_id=?",
                (review_id,),
            ).fetchone()
            if context is None:
                raise ValueError("review request does not exist")
            if context["status"] != "awaiting_review" or context["thread_status"] != "open":
                raise ValueError("only an awaiting review on an open thread can request changes")
            if int(context["row_version"]) != row_version:
                raise ValueError("review has changed; refresh before submitting feedback")
            if context["expires_at"] <= moment:
                raise ValueError("review has expired; refresh before continuing")
            active = self.connection.execute(
                "SELECT intake_request_id FROM intake_requests WHERE thread_id=? "
                "AND status IN ('pending','claimed','retry_wait')",
                (context["thread_id"],),
            ).fetchone()
            if active:
                raise ValueError("the thread already has an active Intake request")
            sequence = int(self.connection.execute(
                "SELECT COALESCE(MAX(sequence_number),0)+1 FROM thread_messages WHERE thread_id=?",
                (context["thread_id"],),
            ).fetchone()[0])
            body = (
                f"Changes requested for {context['platform']}/{context['account']} "
                f"{context['content_format']} preview #{review_id}: {note}"
            )
            message_id = int(self.connection.execute(
                "INSERT INTO thread_messages(thread_id,sequence_number,author_kind,body,created_at) "
                "VALUES (?,?,'human',?,?)",
                (context["thread_id"], sequence, body, moment),
            ).lastrowid)
            intake_context = {
                "kind": "human_conversation",
                "thread_id": context["thread_id"],
                "last_message_id": message_id,
                "conversation_version": "thread_messages_v2",
                "revision_scope": "output_request",
                "review_request_id": review_id,
                "output_request_id": context["output_request_id"],
                "content_package_id": context["content_package_id"],
            }
            request_id = int(self.connection.execute(
                "INSERT INTO intake_requests(thread_id,context_json,context_version,status,attempt_limit,created_at) "
                "VALUES (?,?,'intake_context_v2','pending',3,?)",
                (context["thread_id"], canonical(intake_context), moment),
            ).lastrowid)
            review_update = self.connection.execute(
                "UPDATE review_requests SET status='changes_requested',decision_note=?,"
                "actor_id='local_owner',decided_at=?,row_version=row_version+1 "
                "WHERE review_request_id=? AND status='awaiting_review' AND row_version=?",
                (note, moment, review_id, row_version),
            )
            if review_update.rowcount != 1:
                raise RuntimeError("stale review feedback cannot finalize")
            self.connection.execute(
                "UPDATE content_threads SET updated_at=?,row_version=row_version+1 WHERE thread_id=?",
                (moment, context["thread_id"]),
            )
            self.connection.execute(
                "INSERT INTO human_command_receipts(command_id,command_kind,actor_id,payload_hash,result_record_id,created_at) "
                "VALUES (?,'review_changes','local_owner',?,?,?)",
                (command_id, payload_hash, request_id, moment),
            )
            return request_id

    def approve_review(self, review_id: int, *, row_version: int, command_id: str) -> int:
        """Compatibility boundary: editorial approval creates no PostRequest."""
        return self.decide_review(
            review_id,
            decision="approved",
            note="",
            row_version=row_version,
            command_id=command_id,
        )

    # Production workflow -------------------------------------------------

    def record_destination_readiness(
        self,
        destination_id: int,
        *,
        status: str,
        reasons: list[str],
        facts: dict[str, Any],
        valid_for: timedelta = timedelta(hours=6),
    ) -> int:
        """Persist one bounded provider/config readiness observation."""
        self._validate_schema()
        if status not in {"ready", "degraded", "blocked", "unknown"}:
            raise ValueError("invalid destination readiness status")
        if not isinstance(reasons, list) or any(not isinstance(item, str) or not item for item in reasons):
            raise ValueError("readiness reasons must be non-empty strings")
        if not isinstance(facts, dict) or valid_for <= timedelta(0):
            raise ValueError("readiness facts or validity window is invalid")
        moment = now()
        valid_until = serialize_timestamp(parse_timestamp(moment) + valid_for)
        evidence = {"status": status, "reasons": reasons, "facts": facts, "valid_until": valid_until}
        with self.transaction():
            row = self.connection.execute(
                "SELECT capability_readiness_id FROM capability_readiness WHERE social_destination_id=?",
                (destination_id,),
            ).fetchone()
            if row is None:
                raise ValueError("production destination does not exist")
            readiness_id = int(row[0])
            self.connection.execute(
                "UPDATE capability_readiness SET status=?,reasons_json=?,facts_json=?,checked_at=?,"
                "valid_until=?,row_version=row_version+1,updated_at=? WHERE capability_readiness_id=?",
                (status, canonical(reasons), canonical(facts), moment, valid_until, moment, readiness_id),
            )
            return int(self.connection.execute(
                "INSERT INTO capability_readiness_checks(capability_readiness_id,status,evidence_json,"
                "evidence_hash,checked_at) VALUES (?,?,?,?,?)",
                (readiness_id, status, canonical(evidence), digest(evidence), moment),
            ).lastrowid)

    def authorize_post_now(
        self,
        review_id: int,
        *,
        row_version: int,
        command_id: str,
    ) -> int:
        """Approve one exact review and atomically create immediate delivery work."""
        self._validate_schema()
        self._require_storage_action("post_now")
        if type(row_version) is not int or row_version < 1:
            raise ValueError("a positive displayed review row version is required")
        payload_hash = digest({
            "kind": "post_now", "review_id": review_id, "row_version": row_version,
        })
        prior_receipt = self._command_receipt(command_id)
        if prior_receipt:
            if prior_receipt["payload_hash"] != payload_hash:
                raise ValueError("command ID was reused with different input")
            return int(prior_receipt["result_record_id"])
        moment = now()
        # File reads and hashing stay outside the write transaction. The exact
        # database hashes and row version are rechecked while authorizing.
        context = self._review_delivery_context(review_id, moment=moment)
        with self.transaction():
            receipt = self._command_receipt(command_id)
            if receipt:
                if receipt["payload_hash"] != payload_hash:
                    raise ValueError("command ID was reused with different input")
                return int(receipt["result_record_id"])
            review = self.connection.execute(
                "SELECT status,row_version,package_hash,manifest_hash,expires_at "
                "FROM review_requests WHERE review_request_id=?", (review_id,),
            ).fetchone()
            if review is None or review["status"] != "awaiting_review":
                raise ValueError("only an awaiting production review can be posted")
            if int(review["row_version"]) != row_version:
                raise ValueError("review has changed; refresh before posting")
            if review["expires_at"] <= moment:
                raise ValueError("review has expired; a fresh review cycle is required")
            if (
                review["package_hash"] != context["package_hash"]
                or review["manifest_hash"] != context["manifest_hash"]
            ):
                raise ValueError("review binding changed during authorization")
            eligible_at = self._earliest_eligible_at(context, moment)
            expires_at = (
                parse_timestamp(moment)
                + timedelta(hours=int(context["authorization_ttl_hours"]))
            )
            expires_at = serialize_timestamp(expires_at)
            if eligible_at >= expires_at:
                raise ValueError("posting policy cannot provide an eligible slot before authorization expires")
            publication_identity = digest({
                "review_request_id": review_id,
                "package_hash": context["package_hash"],
                "manifest_hash": context["manifest_hash"],
                "destination_key": context["destination_key"],
            })
            post_request_id = int(self.connection.execute(
                "INSERT INTO post_requests(review_request_id,content_package_id,status,delivery_mode,"
                "publication_identity,row_version,created_at,expires_at,render_run_id,package_hash,"
                "manifest_hash,destination_key) VALUES (?,?,'approved','immediate',?,1,?,?,?,?,?,?)",
                (review_id, context["content_package_id"], publication_identity, moment, expires_at,
                 context["render_run_id"], context["package_hash"], context["manifest_hash"],
                 context["destination_key"]),
            ).lastrowid)
            policy_snapshot = {
                "version": context["policy_version"],
                "timezone": context["timezone_name"],
                "max_posts_per_day": context["max_posts_per_day"],
                "min_post_interval_minutes": context["min_post_interval_minutes"],
                "authorization_ttl_hours": context["authorization_ttl_hours"],
                "computed_at": moment,
            }
            record_id = int(self.connection.execute(
                "INSERT INTO post_records(post_request_id,status,eligible_at,attempt_limit,row_version,"
                "created_at,policy_snapshot_json) VALUES (?,'pending',?,3,1,?,?)",
                (post_request_id, eligible_at, moment, canonical(policy_snapshot)),
            ).lastrowid)
            updated = self.connection.execute(
                "UPDATE review_requests SET status='approved',destination_key=?,decision_note='Post now',"
                "actor_id='local_owner',decided_at=?,row_version=row_version+1 "
                "WHERE review_request_id=? AND status='awaiting_review' AND row_version=?",
                (context["destination_key"], moment, review_id, row_version),
            )
            if updated.rowcount != 1:
                raise RuntimeError("stale Post now command cannot finalize")
            self.connection.execute(
                "INSERT INTO human_command_receipts(command_id,command_kind,actor_id,payload_hash,"
                "result_record_id,created_at) VALUES (?,'post_now','local_owner',?,?,?)",
                (command_id, payload_hash, record_id, moment),
            )
            return record_id

    def prepare_post_attempt(self, record: Any) -> dict[str, Any]:
        """Revalidate a claimed delivery and create its durable attempt."""
        self._validate_schema()
        moment = now()
        context = self._post_delivery_context(int(record["post_record_id"]), moment=moment)
        with self.transaction():
            current = self.connection.execute(
                "SELECT status,claim_owner,claim_version,attempt_count,lease_expires_at "
                "FROM post_records WHERE post_record_id=?", (record["post_record_id"],),
            ).fetchone()
            if (
                current is None or current["status"] != "claimed"
                or current["claim_owner"] != record["claim_owner"]
                or int(current["claim_version"]) != int(record["claim_version"])
                or current["lease_expires_at"] <= moment
            ):
                raise RuntimeError("delivery claim is stale")
            attempt_number = int(current["attempt_count"])
            attempt_id = int(self.connection.execute(
                "INSERT INTO post_attempts(post_record_id,attempt_number,status,started_at) "
                "VALUES (?,?,'created',?)",
                (record["post_record_id"], attempt_number, moment),
            ).lastrowid)
            changed = self.connection.execute(
                "UPDATE post_records SET status='publishing',row_version=row_version+1 "
                "WHERE post_record_id=? AND status='claimed' AND claim_owner=? AND claim_version=?",
                (record["post_record_id"], record["claim_owner"], record["claim_version"]),
            )
            if changed.rowcount != 1:
                raise RuntimeError("delivery claim changed before attempt creation")
            self.connection.execute(
                "UPDATE post_attempts SET status='staging' WHERE post_attempt_id=?",
                (attempt_id,),
            )
        context["post_attempt_id"] = attempt_id
        context["claim_owner"] = record["claim_owner"]
        context["claim_version"] = int(record["claim_version"])
        return context

    def defer_post_claim(self, record: Any, detail: str) -> int:
        """Finish a claimed record that was blocked before any external side effect."""
        moment = now()
        safe = safe_diagnostic(detail)
        temporary = "readiness is not current" in safe.casefold()
        with self.transaction():
            request = self.connection.execute(
                "SELECT q.expires_at FROM post_records p JOIN post_requests q "
                "ON q.post_request_id=p.post_request_id WHERE p.post_record_id=?",
                (record["post_record_id"],),
            ).fetchone()
            if request is not None and request["expires_at"] <= moment:
                self._expire_post(int(record["post_record_id"]), None, moment)
                return int(record["post_record_id"])
            status = "retry_wait" if temporary and int(record["attempt_count"]) < int(record["attempt_limit"]) else "failed"
            next_attempt = serialize_timestamp(
                parse_timestamp(moment) + timedelta(minutes=5)
            ) if status == "retry_wait" else None
            result = self.connection.execute(
                "UPDATE post_records SET status=?,next_attempt_at=?,failure_reason=?,completed_at=?,"
                "row_version=row_version+1 WHERE post_record_id=? AND status='claimed' "
                "AND claim_owner=? AND claim_version=?",
                (status, next_attempt, safe, None if status == "retry_wait" else moment,
                 record["post_record_id"], record["claim_owner"], record["claim_version"]),
            )
            if result.rowcount != 1:
                raise RuntimeError("delivery claim is stale")
            return int(record["post_record_id"])

    def record_publication_resource(
        self,
        attempt_id: int,
        *,
        resource_type: str,
        remote_id: str,
        asset_ordinal: int | None = None,
        status: str = "created",
        safe_metadata: dict[str, Any] | None = None,
    ) -> int:
        self._validate_schema()
        if status not in {"created", "ready", "published", "cleanup_pending", "cleaned", "retained", "failed"}:
            raise ValueError("invalid publication resource status")
        if not resource_type or not remote_id or len(remote_id) > 500:
            raise ValueError("publication resource identity is invalid")
        moment = now()
        with self.transaction():
            attempt = self.connection.execute(
                "SELECT status FROM post_attempts WHERE post_attempt_id=?", (attempt_id,),
            ).fetchone()
            if attempt is None or attempt["status"] not in {"staging", "ready_to_publish"}:
                raise RuntimeError("publication resource cannot be attached to this attempt")
            return int(self.connection.execute(
                "INSERT INTO publication_resources(post_attempt_id,resource_type,asset_ordinal,remote_id,"
                "status,safe_metadata_json,created_at,updated_at) VALUES (?,?,?,?,?,?,?,?)",
                (attempt_id, resource_type, asset_ordinal, remote_id, status,
                 canonical(safe_metadata or {}), moment, moment),
            ).lastrowid)

    def update_publication_resource(self, resource_id: int, *, status: str) -> int:
        """Advance one provider-side resource without changing its identity."""
        self._validate_schema()
        if status not in {"ready", "published", "cleanup_pending", "cleaned", "retained", "failed"}:
            raise ValueError("invalid publication resource status")
        moment = now()
        with self.transaction():
            result = self.connection.execute(
                "UPDATE publication_resources SET status=?,updated_at=? "
                "WHERE publication_resource_id=? AND status NOT IN ('cleaned','failed')",
                (status, moment, resource_id),
            )
            if result.rowcount != 1:
                raise RuntimeError("publication resource is missing or terminal")
            return resource_id

    def mark_attempt_ready(self, attempt_id: int) -> None:
        with self.transaction():
            result = self.connection.execute(
                "UPDATE post_attempts SET status='ready_to_publish' "
                "WHERE post_attempt_id=? AND status='staging'", (attempt_id,),
            )
            if result.rowcount != 1:
                raise RuntimeError("delivery attempt is not in staging")

    def mark_final_publication_request(self, context: dict[str, Any]) -> None:
        """Commit the no-retry boundary immediately before the public call."""
        moment = now()
        with self.transaction():
            row = self.connection.execute(
                "SELECT p.status,p.claim_owner,p.claim_version,p.lease_expires_at,"
                "q.status request_status,q.expires_at,"
                "t.status thread_status,a.status attempt_status,a.final_publication_request_sent_at "
                ",b.delivery_enabled,b.visual_configuration_approved,d.enabled destination_enabled,"
                "cr.status readiness_status,cr.valid_until readiness_valid_until "
                "FROM post_records p JOIN post_requests q ON q.post_request_id=p.post_request_id "
                "JOIN review_requests v ON v.review_request_id=q.review_request_id "
                "JOIN content_packages cp ON cp.content_package_id=v.content_package_id "
                "JOIN output_requests o ON o.output_request_id=cp.output_request_id "
                "JOIN output_bindings b ON b.output_binding_id=o.output_binding_id "
                "JOIN social_destinations d ON d.social_destination_id=b.social_destination_id "
                "JOIN capability_readiness cr ON cr.social_destination_id=d.social_destination_id "
                "JOIN configuration_activations ca ON ca.configuration_release_id=d.configuration_release_id "
                "AND ca.scope_key='global' AND ca.status='active' "
                "JOIN canonical_contents c ON c.canonical_content_id=o.canonical_content_id "
                "JOIN content_jobs j ON j.content_job_id=c.content_job_id "
                "JOIN brief_revisions b ON b.revision_id=j.brief_revision_id "
                "JOIN content_threads t ON t.thread_id=b.thread_id "
                "JOIN post_attempts a ON a.post_attempt_id=? AND a.post_record_id=p.post_record_id "
                "WHERE p.post_record_id=?",
                (context["post_attempt_id"], context["post_record_id"]),
            ).fetchone()
            if row is None:
                raise RuntimeError("delivery lineage is missing")
            if row["expires_at"] <= moment:
                self._expire_post(int(context["post_record_id"]), int(context["post_attempt_id"]), moment)
                raise RuntimeError("delivery authorization expired during staging")
            if (
                row["status"] != "publishing" or row["request_status"] != "approved"
                or row["thread_status"] != "open" or row["attempt_status"] != "ready_to_publish"
                or row["final_publication_request_sent_at"] is not None
                or row["lease_expires_at"] <= moment
                or row["claim_owner"] != context["claim_owner"]
                or int(row["claim_version"]) != int(context["claim_version"])
            ):
                raise RuntimeError("delivery authorization was cancelled or claim is stale")
            if (
                not row["delivery_enabled"] or not row["visual_configuration_approved"]
                or not row["destination_enabled"] or row["readiness_status"] != "ready"
                or row["readiness_valid_until"] <= moment
            ):
                raise RuntimeError("production destination readiness expired during staging")
            result = self.connection.execute(
                "UPDATE post_attempts SET status='final_request_sent',"
                "final_publication_request_sent_at=? WHERE post_attempt_id=? "
                "AND status='ready_to_publish' AND final_publication_request_sent_at IS NULL",
                (moment, context["post_attempt_id"]),
            )
            if result.rowcount != 1:
                raise RuntimeError("final publication marker was not committed")

    def complete_publication(self, context: dict[str, Any], external_post_id: str) -> int:
        if not external_post_id or len(external_post_id) > 300:
            raise ValueError("provider post ID is invalid")
        moment = now()
        with self.transaction():
            attempt = self.connection.execute(
                "SELECT status FROM post_attempts WHERE post_attempt_id=? AND post_record_id=?",
                (context["post_attempt_id"], context["post_record_id"]),
            ).fetchone()
            if attempt is None or attempt["status"] != "final_request_sent":
                raise RuntimeError("publication success lacks the final request marker")
            self.connection.execute(
                "UPDATE post_attempts SET status='succeeded',completed_at=? WHERE post_attempt_id=?",
                (moment, context["post_attempt_id"]),
            )
            result = self.connection.execute(
                "UPDATE post_records SET status='published',external_post_id=?,published_at=?,"
                "completed_at=?,failure_reason=NULL,row_version=row_version+1 "
                "WHERE post_record_id=? AND status='publishing' AND claim_owner=? AND claim_version=?",
                (external_post_id, moment, moment, context["post_record_id"],
                 context["claim_owner"], context["claim_version"]),
            )
            if result.rowcount != 1:
                raise RuntimeError("provider succeeded but local publication finalization is uncertain")
            self.connection.execute(
                "UPDATE post_requests SET status='fulfilled',row_version=row_version+1 "
                "WHERE post_request_id=? AND status='approved'", (context["post_request_id"],),
            )
            self.connection.execute(
                "UPDATE publication_resources SET status='published',updated_at=? "
                "WHERE post_attempt_id=? AND resource_type!='r2_object'",
                (moment, context["post_attempt_id"]),
            )
            self._schedule_attempt_cleanup(int(context["post_attempt_id"]), moment)
            return int(context["post_record_id"])

    def fail_post_attempt(
        self,
        context: dict[str, Any],
        *,
        category: str,
        detail: str,
        retryable: bool,
        after_final_marker: bool,
    ) -> int:
        """Persist typed pre-final failure or terminal publication uncertainty."""
        moment = now()
        with self.transaction():
            current = self.connection.execute(
                "SELECT status,claim_owner,claim_version,lease_expires_at FROM post_records "
                "WHERE post_record_id=?", (context["post_record_id"],),
            ).fetchone()
            marker = self.connection.execute(
                "SELECT final_publication_request_sent_at FROM post_attempts WHERE post_attempt_id=?",
                (context["post_attempt_id"],),
            ).fetchone()
            marker_sent = marker is not None and marker[0] is not None
            if after_final_marker and not marker_sent:
                raise RuntimeError("publication uncertainty requires a committed final request marker")
            if current is None:
                raise RuntimeError("delivery record is missing")
            if (
                current["status"] != "publishing"
                or current["claim_owner"] != context["claim_owner"]
                or int(current["claim_version"]) != int(context["claim_version"])
            ):
                # Cancellation, expiry, stale recovery, or another terminal
                # outcome won. Never overwrite the durable winner.
                return int(context["post_record_id"])
            uncertain = marker_sent
            if uncertain:
                self.connection.execute(
                    "UPDATE post_attempts SET status='outcome_unknown',failure_category=?,failure_detail=?,"
                    "completed_at=? WHERE post_attempt_id=?",
                    (category, safe_diagnostic(detail), moment, context["post_attempt_id"]),
                )
                updated = self.connection.execute(
                    "UPDATE post_records SET status='publication_unknown',publication_unknown_at=?,"
                    "failure_reason=?,completed_at=?,row_version=row_version+1 WHERE post_record_id=? "
                    "AND status='publishing' AND claim_owner=? AND claim_version=?",
                    (moment, safe_diagnostic(detail), moment, context["post_record_id"],
                     context["claim_owner"], context["claim_version"]),
                )
                if updated.rowcount != 1:
                    raise RuntimeError("delivery claim changed before uncertainty was recorded")
                self.connection.execute(
                    "UPDATE publication_resources SET status='retained',updated_at=? "
                    "WHERE post_attempt_id=? AND resource_type!='r2_object' "
                    "AND status NOT IN ('cleaned','failed')",
                    (moment, context["post_attempt_id"]),
                )
                self._schedule_attempt_cleanup(int(context["post_attempt_id"]), moment)
            else:
                if current["lease_expires_at"] <= moment:
                    # Leave the record for the conservative stale-claim recovery
                    # transaction. It owns retry classification and fencing.
                    return int(context["post_record_id"])
                attempt_count = int(self.connection.execute(
                    "SELECT attempt_count FROM post_records WHERE post_record_id=?",
                    (context["post_record_id"],),
                ).fetchone()[0])
                attempt_limit = int(self.connection.execute(
                    "SELECT attempt_limit FROM post_records WHERE post_record_id=?",
                    (context["post_record_id"],),
                ).fetchone()[0])
                will_retry = retryable and attempt_count < attempt_limit
                status = "retry_wait" if will_retry else "failed"
                self.connection.execute(
                    "UPDATE post_attempts SET status=?,failure_category=?,failure_detail=?,completed_at=? "
                    "WHERE post_attempt_id=?",
                    ("retryable_failed" if will_retry else "failed", category,
                     safe_diagnostic(detail), moment, context["post_attempt_id"]),
                )
                next_attempt = serialize_timestamp(
                    parse_timestamp(moment) + timedelta(seconds=30 * (2 ** max(0, attempt_count - 1)))
                ) if will_retry else None
                updated = self.connection.execute(
                    "UPDATE post_records SET status=?,next_attempt_at=?,failure_reason=?,completed_at=?,"
                    "row_version=row_version+1 WHERE post_record_id=? AND status='publishing' "
                    "AND claim_owner=? AND claim_version=?",
                    (status, next_attempt, safe_diagnostic(detail), None if will_retry else moment,
                     context["post_record_id"], context["claim_owner"], context["claim_version"]),
                )
                if updated.rowcount != 1:
                    raise RuntimeError("delivery claim changed before failure was recorded")
                self.connection.execute(
                    "UPDATE publication_resources SET status='retained',updated_at=? "
                    "WHERE post_attempt_id=? AND resource_type!='r2_object' "
                    "AND status NOT IN ('cleaned','failed')",
                    (moment, context["post_attempt_id"]),
                )
                self._schedule_attempt_cleanup(int(context["post_attempt_id"]), moment)
            return int(context["post_record_id"])

    def cancel_delivery(
        self,
        post_record_id: int,
        *,
        row_version: int,
        command_id: str,
    ) -> int:
        """Cancel only before the final provider-request marker commits."""
        self._validate_schema()
        if type(row_version) is not int or row_version < 1:
            raise ValueError("a positive displayed delivery row version is required")
        payload_hash = digest({"kind": "cancel_delivery", "post_record_id": post_record_id,
                               "row_version": row_version})
        moment = now()
        with self.transaction():
            receipt = self._command_receipt(command_id)
            if receipt:
                if receipt["payload_hash"] != payload_hash:
                    raise ValueError("command ID was reused with different input")
                return int(receipt["result_record_id"])
            row = self.connection.execute(
                "SELECT p.status,p.row_version,p.post_request_id,a.post_attempt_id,"
                "a.final_publication_request_sent_at FROM post_records p "
                "LEFT JOIN post_attempts a ON a.post_record_id=p.post_record_id "
                "AND a.attempt_number=p.attempt_count WHERE p.post_record_id=?",
                (post_record_id,),
            ).fetchone()
            if row is None or row["status"] not in {"pending", "claimed", "publishing", "retry_wait"}:
                raise ValueError("delivery can no longer be cancelled")
            if int(row["row_version"]) != row_version:
                raise ValueError("delivery changed; refresh before cancelling")
            if row["final_publication_request_sent_at"] is not None:
                raise ValueError("final publication may have been sent; reconcile instead of cancelling")
            self.connection.execute(
                "UPDATE post_records SET status='cancelled',failure_reason='cancelled by local owner',"
                "completed_at=?,row_version=row_version+1 WHERE post_record_id=? AND row_version=?",
                (moment, post_record_id, row_version),
            )
            self.connection.execute(
                "UPDATE post_requests SET status='cancelled',row_version=row_version+1 "
                "WHERE post_request_id=? AND status='approved'", (row["post_request_id"],),
            )
            if row["post_attempt_id"] is not None:
                self.connection.execute(
                    "UPDATE post_attempts SET status='cancelled',failure_category='human_cancel',"
                    "failure_detail='cancelled before final publication request',completed_at=? "
                    "WHERE post_attempt_id=? AND status IN ('created','staging','ready_to_publish')",
                    (moment, row["post_attempt_id"]),
                )
                self.connection.execute(
                    "UPDATE publication_resources SET status='retained',updated_at=? "
                    "WHERE post_attempt_id=? AND resource_type!='r2_object'",
                    (moment, row["post_attempt_id"]),
                )
                self._schedule_attempt_cleanup(int(row["post_attempt_id"]), moment)
            self.connection.execute(
                "INSERT INTO human_command_receipts(command_id,command_kind,actor_id,payload_hash,"
                "result_record_id,created_at) VALUES (?,'cancel_delivery','local_owner',?,?,?)",
                (command_id, payload_hash, post_record_id, moment),
            )
            return post_record_id

    def request_publication_reconciliation(
        self, post_record_id: int, *, command_id: str
    ) -> int:
        self._validate_schema()
        payload_hash = digest({"kind": "request_reconciliation", "post_record_id": post_record_id})
        moment = now()
        with self.transaction():
            receipt = self._command_receipt(command_id)
            if receipt:
                if receipt["payload_hash"] != payload_hash:
                    raise ValueError("command ID was reused with different input")
                return int(receipt["result_record_id"])
            row = self.connection.execute(
                "SELECT status FROM post_records WHERE post_record_id=?", (post_record_id,),
            ).fetchone()
            if row is None or row["status"] != "publication_unknown":
                raise ValueError("only an uncertain publication can be reconciled")
            request_id = self._ensure_reconciliation(
                post_record_id, "requested by local owner", moment,
            )
            self.connection.execute(
                "INSERT INTO human_command_receipts(command_id,command_kind,actor_id,payload_hash,"
                "result_record_id,created_at) VALUES (?,'request_reconciliation','local_owner',?,?,?)",
                (command_id, payload_hash, request_id, moment),
            )
            return request_id

    def record_reconciliation_check(
        self,
        request: Any,
        *,
        outcome: str,
        query_version: str,
        evidence: dict[str, Any],
    ) -> int:
        if outcome not in {"confirmed_published", "confirmed_not_published", "ambiguous", "provider_unavailable"}:
            raise ValueError("invalid reconciliation outcome")
        moment = now()
        with self.transaction():
            current = self.connection.execute(
                "SELECT 1 FROM reconciliation_requests r JOIN post_records p USING(post_record_id) "
                "WHERE r.reconciliation_request_id=? AND r.status='claimed' "
                "AND r.claim_owner=? AND r.claim_version=? AND r.lease_expires_at>? "
                "AND p.status='publication_unknown'",
                (request["reconciliation_request_id"], request["claim_owner"],
                 request["claim_version"], moment),
            ).fetchone()
            if current is None:
                raise RuntimeError("reconciliation claim is stale or publication is no longer unknown")
            check_id = int(self.connection.execute(
                "INSERT INTO reconciliation_checks(reconciliation_request_id,outcome,query_version,"
                "evidence_json,evidence_hash,checked_at) VALUES (?,?,?,?,?,?)",
                (request["reconciliation_request_id"], outcome, query_version, canonical(evidence),
                 digest(evidence), moment),
            ).lastrowid)
            if outcome == "confirmed_published":
                self.connection.execute(
                    "UPDATE reconciliation_requests SET status='resolved',completed_at=? "
                    "WHERE reconciliation_request_id=? AND claim_owner=? AND claim_version=?",
                    (moment, request["reconciliation_request_id"], request["claim_owner"],
                     request["claim_version"]),
                )
                self.connection.execute(
                    "UPDATE post_records SET status='published',published_at=COALESCE(published_at,?),"
                    "completed_at=?,row_version=row_version+1 WHERE post_record_id=? "
                    "AND status='publication_unknown'",
                    (moment, moment, request["post_record_id"]),
                )
                self.connection.execute(
                    "UPDATE post_requests SET status='fulfilled',row_version=row_version+1 "
                    "WHERE post_request_id=(SELECT post_request_id FROM post_records "
                    "WHERE post_record_id=?) AND status='approved'",
                    (request["post_record_id"],),
                )
            else:
                self.connection.execute(
                    "UPDATE reconciliation_requests SET status='needs_human',claim_owner=NULL,"
                    "claimed_at=NULL,lease_expires_at=NULL,row_version=row_version+1 "
                    "WHERE reconciliation_request_id=? AND claim_owner=? AND claim_version=?",
                    (request["reconciliation_request_id"], request["claim_owner"],
                     request["claim_version"]),
                )
            return check_id

    def resolve_publication_unknown(
        self,
        reconciliation_request_id: int,
        *,
        reconciliation_check_id: int,
        decision: str,
        note: str,
        row_version: int,
        command_id: str,
    ) -> int:
        if decision not in {"published", "not_published_cancel", "leave_unknown"}:
            raise ValueError("invalid reconciliation decision")
        note = note.strip()
        if not note or len(note) > 2000:
            raise ValueError("reconciliation note must contain 1-2,000 characters")
        payload_hash = digest({"kind": "resolve_reconciliation", "request": reconciliation_request_id,
                               "check": reconciliation_check_id, "decision": decision,
                               "note": note, "row_version": row_version})
        moment = now()
        with self.transaction():
            receipt = self._command_receipt(command_id)
            if receipt:
                if receipt["payload_hash"] != payload_hash:
                    raise ValueError("command ID was reused with different input")
                return int(receipt["result_record_id"])
            request = self.connection.execute(
                "SELECT * FROM reconciliation_requests WHERE reconciliation_request_id=?",
                (reconciliation_request_id,),
            ).fetchone()
            check = self.connection.execute(
                "SELECT reconciliation_check_id FROM reconciliation_checks "
                "WHERE reconciliation_check_id=? AND reconciliation_request_id=?",
                (reconciliation_check_id, reconciliation_request_id),
            ).fetchone()
            if request is None or request["status"] != "needs_human" or check is None:
                raise ValueError("the selected reconciliation check is not awaiting human resolution")
            if int(request["row_version"]) != row_version:
                raise ValueError("reconciliation changed; refresh before deciding")
            self.connection.execute(
                "INSERT INTO human_reconciliation_decisions(reconciliation_request_id,"
                "reconciliation_check_id,decision,actor_id,note,created_at) "
                "VALUES (?,? ,?,'local_owner',?,?)",
                (reconciliation_request_id, reconciliation_check_id, decision, note, moment),
            )
            self.connection.execute(
                "UPDATE reconciliation_requests SET status='resolved',row_version=row_version+1,completed_at=? "
                "WHERE reconciliation_request_id=? AND row_version=?",
                (moment, reconciliation_request_id, row_version),
            )
            if decision == "published":
                self.connection.execute(
                    "UPDATE post_records SET status='published',published_at=COALESCE(published_at,?),"
                    "completed_at=?,row_version=row_version+1 WHERE post_record_id=?",
                    (moment, moment, request["post_record_id"]),
                )
                self.connection.execute(
                    "UPDATE post_requests SET status='fulfilled',row_version=row_version+1 "
                    "WHERE post_request_id=(SELECT post_request_id FROM post_records WHERE post_record_id=?)",
                    (request["post_record_id"],),
                )
            elif decision == "not_published_cancel":
                self.connection.execute(
                    "UPDATE post_records SET status='cancelled',completed_at=?,row_version=row_version+1 "
                    "WHERE post_record_id=?", (moment, request["post_record_id"]),
                )
                self.connection.execute(
                    "UPDATE post_requests SET status='cancelled',row_version=row_version+1 "
                    "WHERE post_request_id=(SELECT post_request_id FROM post_records WHERE post_record_id=?)",
                    (request["post_record_id"],),
                )
            self.connection.execute(
                "INSERT INTO human_command_receipts(command_id,command_kind,actor_id,payload_hash,"
                "result_record_id,created_at) VALUES (?,'resolve_reconciliation','local_owner',?,?,?)",
                (command_id, payload_hash, reconciliation_request_id, moment),
            )
            return reconciliation_request_id

    def complete_cleanup(self, task: Any) -> int:
        moment = now()
        with self.transaction():
            result = self.connection.execute(
                "UPDATE delivery_cleanup_tasks SET status='succeeded',completed_at=? "
                "WHERE delivery_cleanup_task_id=? AND status='claimed' AND claim_owner=? AND claim_version=?",
                (moment, task["delivery_cleanup_task_id"], task["claim_owner"], task["claim_version"]),
            )
            if result.rowcount != 1:
                raise RuntimeError("cleanup claim is stale")
            self.connection.execute(
                "UPDATE publication_resources SET status='cleaned',updated_at=? "
                "WHERE publication_resource_id=?", (moment, task["publication_resource_id"]),
            )
            return int(task["delivery_cleanup_task_id"])

    def fail_cleanup(self, task: Any, detail: str, *, retryable: bool) -> int:
        moment = now()
        with self.transaction():
            retry = retryable and int(task["attempt_count"]) < int(task["attempt_limit"])
            status = "retry_wait" if retry else "failed"
            next_attempt = serialize_timestamp(parse_timestamp(moment) + timedelta(minutes=5)) if retry else None
            result = self.connection.execute(
                "UPDATE delivery_cleanup_tasks SET status=?,next_attempt_at=?,failure_reason=?,completed_at=? "
                "WHERE delivery_cleanup_task_id=? AND status='claimed' AND claim_owner=? AND claim_version=?",
                (status, next_attempt, safe_diagnostic(detail), None if retry else moment,
                 task["delivery_cleanup_task_id"], task["claim_owner"], task["claim_version"]),
            )
            if result.rowcount != 1:
                raise RuntimeError("cleanup claim is stale")
            return int(task["delivery_cleanup_task_id"])

    def checkpoint_adaptation(
        self,
        run: Any,
        *,
        body: dict[str, Any] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        """Checkpoint valid adaptation body independently from metadata."""
        self._validate_schema()
        if body is None and metadata is None:
            raise ValueError("an adaptation checkpoint value is required")
        assignments: list[str] = []
        parameters: list[Any] = []
        if body is not None:
            assignments += ["adapted_body_json=?", "adapted_body_hash=?"]
            parameters += [canonical(body), digest(body)]
        if metadata is not None:
            assignments += ["metadata_json=?", "metadata_hash=?"]
            parameters += [canonical(metadata), digest(metadata)]
        parameters += [run["adaptation_run_id"], run["claim_owner"], run["claim_version"]]
        with self.transaction():
            result = self.connection.execute(
                "UPDATE adaptation_runs SET " + ",".join(assignments)
                + " WHERE adaptation_run_id=? AND status='claimed' AND claim_owner=? AND claim_version=?",
                parameters,
            )
            if result.rowcount != 1:
                raise RuntimeError("adaptation checkpoint claim is stale")

    def record_artifact_quarantine(
        self, render_run_id: int, original: Path, quarantine: Path, reason: str
    ) -> None:
        self._validate_schema()
        with self.transaction():
            self.connection.execute(
                "INSERT INTO artifact_reconciliations(render_run_id,original_path,quarantine_path,reason,created_at) "
                "VALUES (?,?,?,?,?)", (render_run_id, str(original), str(quarantine), reason, now()),
            )

    def _validate_schema(self) -> None:
        validate_database(self.connection, check_foreign_keys=False)

    def _storage_action_allowed(self, action: str) -> bool:
        # Planning never consults disk measurements. Real writes may still fail.
        if action == 'planning':
            return True
        if not self.enforce_storage:
            return True
        from common.storage import storage_status
        state = storage_status(self.connection)['reason']
        if action in {"safe_cleanup", "reconciliation"}:
            return True
        if state == "normal":
            return True
        if state == "storage_warning":
            return action in {"post_now", "delivery"}
        return False

    def _require_storage_action(self, action: str) -> None:
        if not self._storage_action_allowed(action):
            from common.storage import storage_status, storage_recovery
            state = storage_status(self.connection)
            raise RuntimeError(f"storage admission refused ({state['reason']}); "
                               f"last sample: {state['sampled_at'] or 'none'}. " + storage_recovery(state))

    def _review_delivery_context(self, review_id: int, *, moment: str) -> dict[str, Any]:
        row = self.connection.execute(
            "SELECT v.review_request_id,v.status review_status,v.expires_at review_expires_at,"
            "v.package_hash,v.manifest_hash,v.render_run_id,p.content_package_id,p.package_json,"
            "p.content_hash,r.manifest_json,o.output_request_id,o.platform,o.account,o.content_format,"
            "b.output_binding_id,b.delivery_enabled,b.visual_configuration_approved,d.social_destination_id,"
            "d.destination_key,d.enabled destination_enabled,d.config_json,d.secret_ref,"
            "d.provider_account_id,d.configuration_release_id,cr.status readiness_status,"
            "cr.valid_until readiness_valid_until,pp.policy_version,pp.timezone_name,"
            "pp.max_posts_per_day,pp.min_post_interval_minutes,pp.authorization_ttl_hours "
            "FROM review_requests v JOIN content_packages p ON p.content_package_id=v.content_package_id "
            "JOIN render_runs r ON r.render_run_id=v.render_run_id "
            "JOIN output_requests o ON o.output_request_id=p.output_request_id "
            "JOIN output_bindings b ON b.output_binding_id=o.output_binding_id "
            "JOIN social_destinations d ON d.social_destination_id=b.social_destination_id "
            "JOIN capability_readiness cr ON cr.social_destination_id=d.social_destination_id "
            "JOIN posting_policies pp ON pp.social_destination_id=d.social_destination_id "
            "JOIN configuration_activations ca ON ca.configuration_release_id=d.configuration_release_id "
            "AND ca.scope_key='global' AND ca.status='active' "
            "WHERE v.review_request_id=?", (review_id,),
        ).fetchone()
        if row is None:
            raise ValueError("review is not bound to an active production destination")
        if row["review_status"] != "awaiting_review" or row["review_expires_at"] <= moment:
            raise ValueError("review is not current and awaiting authorization")
        if not row["delivery_enabled"] or not row["visual_configuration_approved"] or not row["destination_enabled"]:
            raise ValueError("production destination is disabled or visual configuration is not approved")
        if row["readiness_status"] != "ready" or row["readiness_valid_until"] <= moment:
            raise ValueError("production destination readiness is not current")
        return self._validate_delivery_artifacts(row)

    def _post_delivery_context(self, post_record_id: int, *, moment: str) -> dict[str, Any]:
        row = self.connection.execute(
            "SELECT pr.post_record_id,pr.status post_status,pr.eligible_at,pr.claim_owner,pr.claim_version,"
            "pq.post_request_id,pq.status request_status,pq.expires_at,pq.package_hash,pq.manifest_hash,"
            "pq.destination_key,pq.render_run_id,p.content_package_id,p.package_json,p.content_hash,"
            "r.manifest_json,o.output_request_id,o.platform,o.account,o.content_format,"
            "b.output_binding_id,b.delivery_enabled,b.visual_configuration_approved,d.social_destination_id,"
            "d.enabled destination_enabled,d.config_json,d.secret_ref,d.provider_account_id,"
            "d.configuration_release_id,cr.status readiness_status,cr.valid_until readiness_valid_until,"
            "pp.policy_version,pp.timezone_name,pp.max_posts_per_day,pp.min_post_interval_minutes,"
            "pp.authorization_ttl_hours "
            "FROM post_records pr JOIN post_requests pq ON pq.post_request_id=pr.post_request_id "
            "JOIN review_requests v ON v.review_request_id=pq.review_request_id "
            "JOIN content_packages p ON p.content_package_id=pq.content_package_id "
            "JOIN render_runs r ON r.render_run_id=pq.render_run_id "
            "JOIN output_requests o ON o.output_request_id=p.output_request_id "
            "JOIN output_bindings b ON b.output_binding_id=o.output_binding_id "
            "JOIN social_destinations d ON d.social_destination_id=b.social_destination_id "
            "JOIN capability_readiness cr ON cr.social_destination_id=d.social_destination_id "
            "JOIN posting_policies pp ON pp.social_destination_id=d.social_destination_id "
            "JOIN configuration_activations ca ON ca.configuration_release_id=d.configuration_release_id "
            "AND ca.scope_key='global' AND ca.status='active' WHERE pr.post_record_id=?",
            (post_record_id,),
        ).fetchone()
        if row is None or row["request_status"] != "approved":
            raise ValueError("delivery lacks current approved authorization")
        if row["expires_at"] <= moment or row["eligible_at"] > moment:
            raise ValueError("delivery is expired or not yet policy eligible")
        if not row["delivery_enabled"] or not row["visual_configuration_approved"] or not row["destination_enabled"]:
            raise ValueError("production destination is disabled or visual configuration is not approved")
        if row["readiness_status"] != "ready" or row["readiness_valid_until"] <= moment:
            raise ValueError("production destination readiness is not current")
        context = self._validate_delivery_artifacts(row)
        context["post_record_id"] = post_record_id
        context["post_request_id"] = int(row["post_request_id"])
        return context

    def _validate_delivery_artifacts(self, row: Any) -> dict[str, Any]:
        package = json.loads(row["package_json"])
        manifest = json.loads(row["manifest_json"] or "null")
        if not isinstance(package, dict) or package.get("delivery_ready") is not True:
            raise ValueError("package is explicitly non-deliverable")
        if not isinstance(manifest, dict) or manifest.get("review_only") is not False:
            raise ValueError("render manifest is not approved for delivery")
        if digest(package) != row["content_hash"] or row["package_hash"] != row["content_hash"]:
            raise ValueError("package hash does not match the reviewed package")
        if digest(manifest) != row["manifest_hash"]:
            raise ValueError("manifest hash does not match the reviewed render")
        assets = self.connection.execute(
            "SELECT render_asset_id,asset_role,ordinal,local_path,mime_type,width,height,bytes,sha256 "
            "FROM render_assets WHERE render_run_id=? AND asset_role='delivery_jpeg' "
            "AND deleted_at IS NULL ORDER BY ordinal", (row["render_run_id"],),
        ).fetchall()
        manifest_assets = [
            item for item in manifest.get("assets", [])
            if isinstance(item, dict) and item.get("role") == "delivery_jpeg"
        ]
        if len(assets) != len(manifest_assets) or not assets:
            raise ValueError("delivery asset set differs from the reviewed manifest")
        validated: list[dict[str, Any]] = []
        for stored, frozen in zip(assets, manifest_assets, strict=True):
            path = Path(stored["local_path"]).resolve(strict=True)
            if path.stat().st_size != int(stored["bytes"]) or int(stored["bytes"]) > 8_000_000:
                raise ValueError("physical delivery asset size changed after review")
            data = path.read_bytes()
            actual_hash = sha256(data).hexdigest()
            try:
                with Image.open(path) as image:
                    actual_format = image.format
                    actual_dimensions = image.size
                    image.verify()
            except (OSError, UnidentifiedImageError) as error:
                raise ValueError("physical delivery asset is not a valid image") from error
            if actual_format != "JPEG" or actual_dimensions != (
                int(stored["width"]), int(stored["height"])
            ):
                raise ValueError("physical delivery image format or dimensions changed after review")
            expected = {
                "role": stored["asset_role"], "ordinal": stored["ordinal"],
                "path": stored["local_path"], "mime": stored["mime_type"],
                "width": stored["width"], "height": stored["height"],
                "bytes": stored["bytes"], "sha256": stored["sha256"],
            }
            if any(frozen.get(key) != value for key, value in expected.items()):
                raise ValueError("stored delivery asset differs from the reviewed manifest")
            if len(data) != int(stored["bytes"]) or actual_hash != stored["sha256"]:
                raise ValueError("physical delivery asset hash or size changed after review")
            validated.append({**expected, "render_asset_id": int(stored["render_asset_id"]), "path": str(path)})
        if row["platform"] == "instagram":
            if not 5 <= len(validated) <= 8 or any(
                item["mime"] != "image/jpeg" or (item["width"], item["height"]) != (1080, 1350)
                or item["bytes"] > 8_000_000 for item in validated
            ):
                raise ValueError("Instagram delivery assets violate the frozen static-carousel contract")
        else:
            raise ValueError("unsupported production delivery platform")
        result = dict(row)
        result["package"] = package
        result["manifest"] = manifest
        result["assets"] = validated
        result["destination_config"] = json.loads(row["config_json"])
        return result

    def _earliest_eligible_at(self, context: dict[str, Any], moment: str) -> str:
        try:
            zone = ZoneInfo(context["timezone_name"])
        except ZoneInfoNotFoundError as error:
            raise ValueError("posting policy has an invalid IANA timezone") from error
        candidate = parse_timestamp(moment)
        interval = timedelta(minutes=int(context["min_post_interval_minutes"]))
        rows = self.connection.execute(
            "SELECT p.eligible_at,COALESCE(p.published_at,p.publication_unknown_at) terminal_at "
            "FROM post_records p JOIN post_requests q ON q.post_request_id=p.post_request_id "
            "WHERE q.destination_key=? AND p.status IN "
            "('pending','claimed','publishing','published','publication_unknown')",
            (context["destination_key"],),
        ).fetchall()
        occupied = [parse_timestamp(row["terminal_at"] or row["eligible_at"]) for row in rows]
        if occupied:
            candidate = max(candidate, max(occupied) + interval)
        daily_cap = int(context["max_posts_per_day"])
        for _ in range(370):
            local_day = candidate.astimezone(zone).date()
            count = sum(item.astimezone(zone).date() == local_day for item in occupied)
            if count < daily_cap:
                return serialize_timestamp(candidate)
            next_local = datetime.combine(
                local_day + timedelta(days=1), datetime.min.time(), tzinfo=zone,
            )
            candidate = max(candidate, next_local.astimezone(timezone.utc))
        raise RuntimeError("posting policy could not find a bounded eligible slot")

    def _expire_post(self, post_record_id: int, attempt_id: int | None, moment: str) -> None:
        self.connection.execute(
            "UPDATE post_records SET status='expired',failure_reason='authorization expired',"
            "completed_at=?,row_version=row_version+1 WHERE post_record_id=?", (moment, post_record_id),
        )
        self.connection.execute(
            "UPDATE post_requests SET status='expired',row_version=row_version+1 "
            "WHERE post_request_id=(SELECT post_request_id FROM post_records WHERE post_record_id=?)",
            (post_record_id,),
        )
        if attempt_id is not None:
            self.connection.execute(
                "UPDATE post_attempts SET status='failed',failure_category='authorization_expired',"
                "failure_detail='authorization expired before final request',completed_at=? "
                "WHERE post_attempt_id=?", (moment, attempt_id),
            )
            self._schedule_attempt_cleanup(attempt_id, moment)

    def _schedule_attempt_cleanup(self, attempt_id: int, moment: str) -> None:
        resources = self.connection.execute(
            "SELECT publication_resource_id,remote_id FROM publication_resources "
            "WHERE post_attempt_id=? AND resource_type='r2_object' AND status NOT IN ('cleaned','cleanup_pending')",
            (attempt_id,),
        ).fetchall()
        for resource in resources:
            self.connection.execute(
                "UPDATE publication_resources SET status='cleanup_pending',updated_at=? "
                "WHERE publication_resource_id=?", (moment, resource["publication_resource_id"]),
            )
            self.connection.execute(
                "INSERT OR IGNORE INTO delivery_cleanup_tasks(publication_resource_id,object_key,status,"
                "attempt_limit,created_at) VALUES (?,?,'pending',5,?)",
                (resource["publication_resource_id"], resource["remote_id"], moment),
            )

    def _ensure_reconciliation(self, post_record_id: int, reason: str, moment: str) -> int:
        prior = self.connection.execute(
            "SELECT reconciliation_request_id FROM reconciliation_requests WHERE post_record_id=? "
            "AND status IN ('pending','claimed','retry_wait','needs_human')", (post_record_id,),
        ).fetchone()
        if prior:
            return int(prior[0])
        return int(self.connection.execute(
            "INSERT INTO reconciliation_requests(post_record_id,reason,status,attempt_limit,created_at) "
            "VALUES (?,?,'pending',3,?)", (post_record_id, reason, moment),
        ).lastrowid)
