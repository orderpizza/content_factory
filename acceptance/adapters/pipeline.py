"""Persist isolated acceptance inputs and drive the authoritative workers."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from acceptance.framework import (Category, StageCase, StageExecution, Status,
                                  initialize_acceptance_database,
                                  require_live_authorization)
from common.gemini import VertexGeminiClient, configured_model
from workflow import (GeminiAdaptationWorker, GeminiDeterminationWorker,
                      GeminiEditorialPlanningWorker, GeminiIntakeWorker,
                      GeminiPipelineRunner, VisualPlanner, WorkflowStore)
from workflow.store import canonical, digest, now


def _client(policy: Any, phase: str) -> VertexGeminiClient:
    return VertexGeminiClient(
        max_output_tokens=policy.phase_limits[phase][1],
        thinking_level="LOW" if configured_model().startswith("gemini-3") else None,
    )


def _seed_detection_fixture(store: WorkflowStore, case: StageCase) -> None:
    """Create the same frozen Determination shape used by Scout handoff.

    Detection collection/scoring is deliberately outside live text acceptance.
    The fixture is already frozen evidence; this writes its downstream
    Determination handoff into the isolated production database.
    """
    brief = case.case.input["frozen_brief"]
    evidence = case.case.input["source_evidence"]
    required = {"editorial_goal", "topic", "coverage_kind", "canonical_target", "revision_scope", "audience", "desired_outcome", "constraints", "source_context", "open_questions"}
    if set(brief) != required or not isinstance(evidence, dict):
        raise ValueError("frozen detection fixture does not contain a production BriefRevision shape")
    moment = now()
    source_context = {"kind": "selected_trend", "fixture_version": "acceptance_detection_v1", **evidence}
    with store.transaction():
        thread = store.connection.execute(
            "INSERT INTO content_threads(origin,status,created_at,updated_at) VALUES ('human','open',?,?)",
            (moment, moment),
        )
        thread_id = int(thread.lastrowid)
        # The frozen brief/request handoff below has the exact persisted contract
        # used by production Scout. The empty local thread is only an isolated
        # ownership shell; no Intake request is created or invoked.
        store.connection.execute(
            "UPDATE content_threads SET coverage_identity=? WHERE thread_id=?",
            (f"coverage:coverage_normalization_v2:{brief['coverage_kind']}:{' '.join(brief['canonical_target'].casefold().split())}", thread_id),
        )
        revision = store.connection.execute(
            "INSERT INTO brief_revisions(thread_id,revision_number,brief_json,source_snapshot_json,revision_reason,created_by,created_at) VALUES (?,1,?,?, 'initial','system',?)",
            (thread_id, canonical(brief), canonical(source_context), moment),
        )
        snapshot = {"brief": brief, "source_context": source_context, "catalog": store.catalog(),
                    "catalog_version": "domain_pipeline_catalog_v1", "routing_policy_version": "determination_policy_v2"}
        store.connection.execute(
            "INSERT INTO determination_requests(revision_id,input_snapshot_json,input_fingerprint,status,attempt_limit,created_at) VALUES (?,?,?,'pending',3,?)",
            (int(revision.lastrowid), canonical(snapshot), digest(snapshot), moment),
        )


def _ledger(store: WorkflowStore, phases: list[str]) -> tuple[int, int, str | None, int]:
    if not phases:
        return 0, 0, None, 0
    placeholders = ",".join("?" for _ in phases)
    rows = store.connection.execute(
        f"SELECT model_invocation_id,model_id,outcome,estimated_cost_micro_usd FROM model_invocations WHERE phase IN ({placeholders}) ORDER BY model_invocation_id",
        phases,
    ).fetchall()
    calls = sum(row["outcome"] != "blocked" for row in rows)
    cost = sum(int(row["estimated_cost_micro_usd"] or 0) for row in rows)
    model = None if not rows else rows[-1]["model_id"]
    return calls, 0, model, cost


def _outputs(store: WorkflowStore) -> dict[str, Any]:
    result: dict[str, Any] = {}
    intake = store.connection.execute("SELECT intake_request_id,status FROM intake_requests ORDER BY intake_request_id DESC LIMIT 1").fetchone()
    if intake:
        brief = store.connection.execute("SELECT brief_json FROM brief_revisions WHERE source_intake_request_id=?", (intake["intake_request_id"],)).fetchone()
        result["intake"] = {"request_id": intake["intake_request_id"], "status": intake["status"],
                            "brief": None if brief is None else json.loads(brief[0])}
    decision = store.connection.execute("SELECT determination_decision_id,outcome,rationale FROM determination_decisions ORDER BY determination_decision_id DESC LIMIT 1").fetchone()
    if decision:
        routes = store.connection.execute("SELECT pipeline_id,disposition,fit,reason,output_assessments_json FROM determination_routes WHERE determination_decision_id=? ORDER BY pipeline_id", (decision["determination_decision_id"],)).fetchall()
        result["determination"] = {"decision_id": decision["determination_decision_id"], "outcome": decision["outcome"], "rationale": decision["rationale"], "routes": [{**dict(row), "outputs": json.loads(row["output_assessments_json"])} for row in routes]}
    plan = store.connection.execute("SELECT editorial_plan_id,plan_json FROM editorial_plans ORDER BY editorial_plan_id DESC LIMIT 1").fetchone()
    if plan:
        result["editorial_planning"] = {"editorial_plan_id": plan["editorial_plan_id"], "plan": json.loads(plan["plan_json"])}
    content = store.connection.execute("SELECT canonical_content_id,canonical_json FROM canonical_contents ORDER BY canonical_content_id DESC LIMIT 1").fetchone()
    if content:
        result["generation"] = {"canonical_content_id": content["canonical_content_id"], "canonical": json.loads(content["canonical_json"])}
    recipe = store.connection.execute("SELECT visual_recipe_id,recipe_json,selection_provenance_json FROM visual_recipes ORDER BY visual_recipe_id DESC LIMIT 1").fetchone()
    if recipe:
        result["visual_selection"] = {"visual_recipe_id": recipe["visual_recipe_id"], "recipe": json.loads(recipe["recipe_json"]), "selection": json.loads(recipe["selection_provenance_json"])}
    package = store.connection.execute("SELECT content_package_id,package_json FROM content_packages ORDER BY content_package_id DESC LIMIT 1").fetchone()
    if package:
        result["adaptation"] = {"content_package_id": package["content_package_id"], "package": json.loads(package["package_json"])}
    return result


def _failed_category(store: WorkflowStore, stage: str) -> Category:
    table = {"intake": "intake_requests", "determination": "determination_requests", "editorial_planning": "editorial_plan_runs", "generation": "generation_runs", "adaptation": "adaptation_runs"}.get(stage)
    if table is None:
        return Category.CONTRACT
    status = store.connection.execute(f"SELECT status FROM {table} ORDER BY 1 DESC LIMIT 1").fetchone()
    if status and status[0] == "retry_wait":
        return Category.BUDGET
    invocation = store.connection.execute(
        "SELECT outcome FROM model_invocations WHERE phase=? ORDER BY model_invocation_id DESC LIMIT 1", (stage,)
    ).fetchone()
    if invocation and invocation[0] in {"transport_failed", "parse_failed"}:
        return Category.PROVIDER
    return Category.CONTRACT


def execute_case(stage_case: StageCase, database: Path, authorization: Any, text_policy: Any) -> StageExecution:
    """Run a requested text-stage range, stopping at the first failed handoff."""
    require_live_authorization(authorization)
    initialize_acceptance_database(database)
    case = stage_case.case
    requested = ("intake", "determination", "editorial_planning", "generation", "visual_selection", "adaptation")
    active = requested[requested.index(case.start_stage):requested.index(case.end_stage) + 1]
    executed: list[str] = []
    with WorkflowStore(database, model_budget_policy=text_policy) as store:
        if case.source_kind == "human":
            store.create_human_idea(case.input["idea"], command_id=f"acceptance-{case.case_id}-{stage_case.attempt}")
        else:
            _seed_detection_fixture(store, stage_case)
        workers = {
            "intake": lambda: GeminiIntakeWorker(store, _client(text_policy, "intake"), instance_id=f"acceptance-intake-{stage_case.attempt}").run_once(),
            "determination": lambda: GeminiDeterminationWorker(store, _client(text_policy, "determination"), instance_id=f"acceptance-determination-{stage_case.attempt}").run_once(),
            "editorial_planning": lambda: GeminiEditorialPlanningWorker(store, _client(text_policy, "editorial_planning"), instance_id=f"acceptance-editorial-{stage_case.attempt}").run_once(),
            "generation": lambda: GeminiPipelineRunner(store, _client(text_policy, "generation"), instance_id=f"acceptance-generation-{stage_case.attempt}").run_once(),
            "visual_selection": lambda: VisualPlanner(store, instance_id=f"acceptance-visual-{stage_case.attempt}").run_once(),
            "adaptation": lambda: GeminiAdaptationWorker(store, _client(text_policy, "adaptation"), instance_id=f"acceptance-adaptation-{stage_case.attempt}", strict_english_capacity=True).run_once(),
        }
        for stage in active:
            value = workers[stage]()
            executed.append(stage)
            if value is None:
                # Clarification is a successful, inspectable terminal Intake
                # outcome for a one-stage case, never a fabricated brief.
                if stage == "intake" and case.end_stage == "intake":
                    intake = _outputs(store).get("intake", {})
                    if intake.get("status") == "needs_clarification":
                        calls, images, model, cost = _ledger(store, ["intake"])
                        return StageExecution(Status.PASS, "intake", model, _outputs(store), calls, images, cost,
                                              executed_stages=tuple(executed))
                calls, images, model, cost = _ledger(store, [s for s in active if s != "visual_selection"])
                return StageExecution(Status.ERROR, stage, model, _outputs(store), calls, images, cost,
                                      f"Production {stage} did not complete; downstream stages were not invoked.",
                                      _failed_category(store, stage), tuple(executed))
        calls, images, model, cost = _ledger(store, [s for s in active if s != "visual_selection"])
        return StageExecution(Status.PASS, case.end_stage, model, _outputs(store), calls, images, cost,
                              executed_stages=tuple(executed))
