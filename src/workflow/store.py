"""Transactional repository for the v2 SQLite workflow handoffs."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from hashlib import sha256
from pathlib import Path
from typing import Any
import json

from database.migrations import SchemaError, connect, validate_editorial_workflow

WORKFLOW_PIPELINES = ("english", "ai_tools", "personal_finance", "business_side_hustle", "psychology_behavior")


def now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def canonical(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def digest(value: Any) -> str:
    return sha256(canonical(value).encode("utf-8")).hexdigest()


def coverage(kind: str, target: str) -> str:
    normalized = " ".join(target.casefold().strip().split())
    return f"coverage:coverage_normalization_v2:{kind.casefold().strip()}:{normalized}"


class WorkflowStore:
    def __init__(self, path: str | Path, *, read_only: bool = False):
        self.path = Path(path).resolve()
        if not self.path.is_file():
            raise SchemaError(f"Database does not exist: {self.path}")
        self.connection = connect(self.path, read_only=read_only)
        validate_editorial_workflow(self.connection)
        self.read_only = read_only

    def close(self) -> None:
        self.connection.close()

    def __enter__(self) -> "WorkflowStore":
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    def create_human_idea(self, body: str, *, command_id: str) -> int:
        if self.read_only:
            raise RuntimeError("read-only dashboard connection")
        body = body.strip()
        if not body or len(body) > 8000:
            raise ValueError("idea must contain 1-8,000 characters")
        moment = now()
        payload_hash = digest({"body": body})
        with self.connection:
            receipt = self.connection.execute(
                "SELECT result_record_id,payload_hash FROM human_command_receipts WHERE command_id=?", (command_id,)
            ).fetchone() if self._has_receipts() else None
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
            if self._has_receipts():
                self.connection.execute(
                    "INSERT INTO human_command_receipts(command_id,command_kind,actor_id,payload_hash,result_record_id,created_at) VALUES (?, 'new_idea','local_owner',?,?,?)",
                    (command_id, payload_hash, thread_id, moment),
                )
            return int(request.lastrowid)

    def _has_receipts(self) -> bool:
        return self.connection.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='human_command_receipts'").fetchone() is not None

    def register_capability(self, pipeline_id: str, *, enabled: bool, generation_ready: bool, outputs: list[dict[str, str | bool]]) -> int:
        """Operator/test-only registration; no account is inferred or enabled by default."""
        if pipeline_id not in WORKFLOW_PIPELINES:
            raise ValueError("unknown pipeline")
        active = self.connection.execute("SELECT configuration_release_id FROM configuration_activations WHERE scope_key='global' AND status='active'").fetchone()
        if active is None:
            raise RuntimeError("a detection configuration release must be active first")
        moment = now()
        with self.connection:
            cur = self.connection.execute(
                "INSERT INTO pipeline_capabilities(pipeline_id,pipeline_version,enabled,remit_json,generation_ready,configuration_release_id,created_at) VALUES (?, 'domain_pipeline_catalog_v1', ?, ?, ?, ?, ?)",
                (pipeline_id, int(enabled), canonical({"placeholder": True}), int(generation_ready), active[0], moment),
            )
            capability_id = int(cur.lastrowid)
            for output in outputs:
                self.connection.execute(
                    "INSERT INTO output_bindings(pipeline_capability_id,platform,account,content_format,output_contract_version,renderer_compatibility,ready,safe_reason,created_at) VALUES (?,?,?,?,?,?,?,?,?)",
                    (capability_id, output["platform"], output["account"], output["content_format"], output.get("output_contract_version", "placeholder_v1"), output.get("renderer_compatibility", "placeholder"), int(bool(output.get("ready"))), str(output.get("safe_reason", "operator fixture")), moment),
                )
        return capability_id

    def claim(self, table: str, primary_key: str, worker: str, *, lease_seconds: int = 300) -> Any | None:
        allowed = {
            "intake_requests", "determination_requests", "generation_runs", "adaptation_runs", "render_runs", "post_records"
        }
        if table not in allowed:
            raise ValueError("unsupported claim table")
        moment = now()
        expiry = (datetime.fromisoformat(moment) + timedelta(seconds=lease_seconds)).isoformat()
        with self.connection:
            row = self.connection.execute(
                f"SELECT * FROM {table} WHERE status IN ('pending','retry_wait') AND (next_attempt_at IS NULL OR next_attempt_at<=?) ORDER BY created_at,{primary_key} LIMIT 1", (moment,)
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

    def catalog(self) -> list[dict[str, Any]]:
        rows = self.connection.execute(
            "SELECT c.*, b.output_binding_id,b.platform,b.account,b.content_format,b.output_contract_version,b.ready,b.safe_reason FROM pipeline_capabilities c LEFT JOIN output_bindings b ON b.pipeline_capability_id=c.pipeline_capability_id ORDER BY c.pipeline_capability_id,b.output_binding_id"
        ).fetchall()
        by_pipeline: dict[str, dict[str, Any]] = {}
        for row in rows:
            item = by_pipeline.setdefault(row["pipeline_id"], {"pipeline_id": row["pipeline_id"], "enabled": bool(row["enabled"]), "generation_ready": bool(row["generation_ready"]), "outputs": []})
            if row["output_binding_id"] is not None:
                item["outputs"].append({key: row[key] for key in ("output_binding_id","platform","account","content_format","output_contract_version","ready","safe_reason")})
        return [by_pipeline[key] for key in WORKFLOW_PIPELINES if key in by_pipeline]

    def complete_intake(self, request: Any, brief: dict[str, Any], *, actor_message: str | None = None) -> int:
        moment = now(); thread_id = int(request["thread_id"])
        identity = coverage(str(brief["coverage_kind"]), str(brief["canonical_target"]))
        with self.connection:
            owned = self.connection.execute("SELECT status FROM content_threads WHERE thread_id=?", (thread_id,)).fetchone()
            if owned is None or owned["status"] != "open":
                self._finish_claim("intake_requests", "intake_request_id", request, "cancelled", moment, "thread is not open")
                raise RuntimeError("thread is not open")
            collision = self.connection.execute("SELECT thread_id FROM content_threads WHERE coverage_identity=?", (identity,)).fetchone()
            if collision and int(collision["thread_id"]) != thread_id:
                self._finish_claim("intake_requests", "intake_request_id", request, "completed", moment, None)
                self.connection.execute("UPDATE content_threads SET status='closed',closure_actor='intake_agent',closure_reason='coverage_collision_merged',closed_at=?,updated_at=?,row_version=row_version+1 WHERE thread_id=?", (moment,moment,thread_id))
                return int(collision["thread_id"])
            latest = self.connection.execute("SELECT revision_id,revision_number FROM brief_revisions WHERE thread_id=? ORDER BY revision_number DESC LIMIT 1", (thread_id,)).fetchone()
            message_id = None
            if actor_message:
                sequence = int(self.connection.execute("SELECT COALESCE(MAX(sequence_number),0)+1 FROM thread_messages WHERE thread_id=?", (thread_id,)).fetchone()[0])
                message_id = int(self.connection.execute("INSERT INTO thread_messages(thread_id,sequence_number,author_kind,body,created_at) VALUES (?,?, 'intake_agent',?,?)", (thread_id,sequence,actor_message,moment)).lastrowid)
            last_human = self.connection.execute("SELECT message_id FROM thread_messages WHERE thread_id=? AND author_kind='human' ORDER BY sequence_number DESC LIMIT 1", (thread_id,)).fetchone()
            snapshot = json.loads(request["context_json"])
            revision = self.connection.execute(
                "INSERT INTO brief_revisions(thread_id,revision_number,parent_revision_id,input_through_message_id,brief_json,source_snapshot_json,revision_reason,created_by,source_intake_request_id,created_at) VALUES (?,?,?,?,?,?,?,?,?,?)",
                (thread_id, 1 if latest is None else int(latest["revision_number"])+1, None if latest is None else latest["revision_id"], None if last_human is None else last_human[0], canonical(brief), canonical(snapshot), "initial" if latest is None else "human_rework", "intake_agent", request["intake_request_id"], moment),
            )
            revision_id = int(revision.lastrowid)
            self.connection.execute("UPDATE content_threads SET coverage_identity=COALESCE(coverage_identity,?),updated_at=? WHERE thread_id=?", (identity,moment,thread_id))
            catalog = self.catalog(); snapshot_value = {"brief": brief, "source_context": snapshot, "catalog": catalog, "catalog_version":"domain_pipeline_catalog_v1", "routing_policy_version":"determination_policy_v1"}
            self.connection.execute("INSERT INTO determination_requests(revision_id,input_snapshot_json,input_fingerprint,status,attempt_limit,created_at) VALUES (?,?,?,'pending',3,?)", (revision_id,canonical(snapshot_value),digest(snapshot_value),moment))
            self._finish_claim("intake_requests", "intake_request_id", request, "completed", moment, None)
            return revision_id

    def clarify_intake(self, request: Any, question: str) -> None:
        moment = now()
        with self.connection:
            sequence = int(self.connection.execute("SELECT COALESCE(MAX(sequence_number),0)+1 FROM thread_messages WHERE thread_id=?", (request["thread_id"],)).fetchone()[0])
            self.connection.execute("INSERT INTO thread_messages(thread_id,sequence_number,author_kind,body,created_at) VALUES (?,?, 'intake_agent',?,?)", (request["thread_id"],sequence,question,moment))
            self._finish_claim("intake_requests", "intake_request_id", request, "needs_clarification", moment, None)

    def _finish_claim(self, table: str, key: str, row: Any, status: str, moment: str, reason: str | None) -> None:
        reason_column = "failure_detail" if table == "intake_requests" else "failure_reason"
        result = self.connection.execute(f"UPDATE {table} SET status=?,completed_at=?,{reason_column}=COALESCE(?,{reason_column}) WHERE {key}=? AND status='claimed' AND claim_owner=? AND claim_version=?", (status,moment,reason,row[key],row["claim_owner"],row["claim_version"]))
        if result.rowcount != 1:
            raise RuntimeError("stale claim cannot finalize")

    def fail_claim(self, table: str, key: str, row: Any, reason: str) -> None:
        with self.connection:
            self._finish_claim(table,key,row,"failed",now(),reason[:2000])

    def record_decision(self, request: Any, decision: dict[str, Any]) -> int:
        moment = now(); routes = decision["routes"]
        if {item["pipeline_id"] for item in routes} != set(WORKFLOW_PIPELINES) or len(routes) != 5:
            raise ValueError("determination must persist exactly five routes")
        with self.connection:
            existing = self.connection.execute("SELECT determination_decision_id FROM determination_decisions WHERE determination_request_id=?", (request["determination_request_id"],)).fetchone()
            if existing:
                self._finish_claim("determination_requests","determination_request_id",request,"completed",moment,None)
                return int(existing[0])
            revision = self.connection.execute("SELECT r.*,t.coverage_identity FROM brief_revisions r JOIN content_threads t ON t.thread_id=r.thread_id WHERE r.revision_id=?", (request["revision_id"],)).fetchone()
            cur = self.connection.execute("INSERT INTO determination_decisions(determination_request_id,outcome,opportunity_value,rationale,warnings_json,coverage_identity,catalog_fingerprint,readiness_fingerprint,routing_policy_version,created_at) VALUES (?,?,?,?,?,?,?,?,?,?)", (request["determination_request_id"],decision["outcome"],decision["opportunity_value"],decision["rationale"],canonical(decision.get("warnings",[])),revision["coverage_identity"],digest(decision["catalog"]),digest(decision["catalog"]),"determination_policy_v1",moment))
            decision_id=int(cur.lastrowid)
            for route in routes:
                route_cur=self.connection.execute("INSERT INTO determination_routes(determination_decision_id,pipeline_id,disposition,fit,reason,angle_json,evidence_json,output_assessments_json,created_at) VALUES (?,?,?,?,?,?,?,?,?)", (decision_id,route["pipeline_id"],route["disposition"],route["fit"],route["reason"],None if route.get("angle") is None else canonical(route["angle"]),canonical(route.get("evidence",[])),canonical(route.get("outputs",[])),moment))
                if route["disposition"] == "selected":
                    recipe={"brief":json.loads(revision["brief_json"]),"angle":route["angle"],"pipeline_id":route["pipeline_id"],"outputs":route["outputs"]}
                    self.connection.execute("INSERT INTO content_jobs(determination_route_id,brief_revision_id,pipeline_id,content_identity,recipe_json,output_plan_json,priority,created_at) VALUES (?,?,?,?,?,?,50,?)", (int(route_cur.lastrowid),revision["revision_id"],route["pipeline_id"],digest(recipe),canonical(recipe),canonical(route["outputs"]),moment))
                    job_id=int(self.connection.execute("SELECT last_insert_rowid()").fetchone()[0])
                    self.connection.execute("INSERT INTO generation_runs(content_job_id,run_number,status,attempt_limit,created_at) VALUES (?,1,'pending',2,?)",(job_id,moment))
            self._finish_claim("determination_requests","determination_request_id",request,"completed",moment,None)
            return decision_id

    def create_canonical(self, run: Any, value: dict[str, Any]) -> int:
        moment=now()
        with self.connection:
            job=self.connection.execute("SELECT * FROM content_jobs WHERE content_job_id=?",(run["content_job_id"],)).fetchone()
            existing=self.connection.execute("SELECT canonical_content_id FROM canonical_contents WHERE content_job_id=?",(job["content_job_id"],)).fetchone()
            if existing:
                self._finish_claim("generation_runs","generation_run_id",run,"succeeded",moment,None); return int(existing[0])
            identity=digest({"job":job["content_identity"],"body":value})
            canonical_id=int(self.connection.execute("INSERT INTO canonical_contents(content_job_id,generation_run_id,canonical_identity,canonical_json,canonical_hash,schema_version,created_at) VALUES (?,?,?,?,?,'canonical_content_v1',?)",(job["content_job_id"],run["generation_run_id"],identity,canonical(value),digest(value),moment)).lastrowid)
            for output in json.loads(job["output_plan_json"]):
                input_value={"canonical_content_id":canonical_id,"output":output}
                out=int(self.connection.execute("INSERT INTO output_requests(canonical_content_id,output_binding_id,platform,account,content_format,output_identity,output_contract_version,input_json,created_at) VALUES (?,?,?,?,?,?,?,?,?)",(canonical_id,output.get("output_binding_id"),output["platform"],output["account"],output["content_format"],digest(input_value),output.get("output_contract_version","placeholder_v1"),canonical(input_value),moment)).lastrowid)
                self.connection.execute("INSERT INTO adaptation_runs(output_request_id,run_number,status,attempt_limit,created_at) VALUES (?,1,'pending',2,?)",(out,moment))
            self._finish_claim("generation_runs","generation_run_id",run,"succeeded",moment,None)
            return canonical_id

    def create_package(self, run: Any, package: dict[str, Any]) -> int:
        moment=now()
        with self.connection:
            output=self.connection.execute("SELECT * FROM output_requests WHERE output_request_id=?",(run["output_request_id"],)).fetchone()
            prior=self.connection.execute("SELECT content_package_id FROM content_packages WHERE output_request_id=?",(output["output_request_id"],)).fetchone()
            if prior:
                self._finish_claim("adaptation_runs","adaptation_run_id",run,"succeeded",moment,None); return int(prior[0])
            package_id=int(self.connection.execute("INSERT INTO content_packages(output_request_id,adaptation_run_id,package_json,content_hash,visual_spec_json,created_at) VALUES (?,?,?,?,?,?)",(output["output_request_id"],run["adaptation_run_id"],canonical(package),digest(package),canonical(package["visual_spec"]),moment)).lastrowid)
            self.connection.execute("INSERT INTO render_runs(content_package_id,run_number,status,attempt_limit,created_at) VALUES (?,1,'pending',2,?)",(package_id,moment))
            self._finish_claim("adaptation_runs","adaptation_run_id",run,"succeeded",moment,None)
            return package_id

    def complete_render(self, run: Any, manifest: dict[str, Any], asset: dict[str, Any]) -> int:
        moment=now(); manifest_json=canonical(manifest); manifest_hash=digest(manifest)
        with self.connection:
            prior=self.connection.execute("SELECT review_request_id FROM review_requests WHERE render_run_id=?",(run["render_run_id"],)).fetchone()
            if prior:
                self._finish_claim("render_runs","render_run_id",run,"succeeded",moment,None); return int(prior[0])
            self.connection.execute("INSERT INTO render_assets(render_run_id,asset_role,ordinal,local_path,mime_type,width,height,bytes,sha256,created_at) VALUES (?,?,?,?,?,?,?,?,?,?)",(run["render_run_id"],asset["role"],1,asset["path"],asset["mime"],asset["width"],asset["height"],asset["bytes"],asset["sha256"],moment))
            self.connection.execute("UPDATE render_runs SET manifest_json=? WHERE render_run_id=?",(manifest_json,run["render_run_id"]))
            package=self.connection.execute("SELECT p.content_package_id,p.content_hash FROM content_packages p JOIN render_runs r ON r.content_package_id=p.content_package_id WHERE r.render_run_id=?",(run["render_run_id"],)).fetchone()
            review=int(self.connection.execute("INSERT INTO review_requests(content_package_id,render_run_id,review_cycle_number,package_hash,manifest_hash,status,expires_at,created_at) VALUES (?,?,1,?,?,'awaiting_review',?,?)",(package["content_package_id"],run["render_run_id"],package["content_hash"],manifest_hash,(datetime.fromisoformat(moment)+timedelta(days=14)).isoformat(),moment)).lastrowid)
            self._finish_claim("render_runs","render_run_id",run,"succeeded",moment,None); return review

    def approve_review(self, review_id: int, *, row_version: int, command_id: str) -> int:
        moment=now()
        with self.connection:
            review=self.connection.execute("SELECT * FROM review_requests WHERE review_request_id=?",(review_id,)).fetchone()
            if review is None or review["status"] != "awaiting_review" or int(review["row_version"]) != row_version: raise ValueError("review is no longer approvable")
            package=self.connection.execute("SELECT o.platform,o.account,p.content_package_id FROM content_packages p JOIN output_requests o ON o.output_request_id=p.output_request_id WHERE p.content_package_id=?",(review["content_package_id"],)).fetchone()
            identity=digest({"package":review["package_hash"],"platform":package["platform"],"account":package["account"]})
            self.connection.execute("UPDATE review_requests SET status='approved',decided_at=?,actor_id='local_owner',row_version=row_version+1 WHERE review_request_id=? AND row_version=?",(moment,review_id,row_version))
            request=int(self.connection.execute("INSERT INTO post_requests(review_request_id,content_package_id,status,delivery_mode,publication_identity,row_version,created_at,expires_at) VALUES (?,?,'approved','immediate',?,1,?,?)",(review_id,package["content_package_id"],identity,moment,(datetime.fromisoformat(moment)+timedelta(hours=48)).isoformat())).lastrowid)
            self.connection.execute("INSERT INTO post_records(post_request_id,status,eligible_at,attempt_limit,row_version,created_at) VALUES (?,'pending',?,2,1,?)",(request,moment,moment))
            return request
