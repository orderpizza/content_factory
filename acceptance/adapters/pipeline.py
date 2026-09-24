"""Persist isolated acceptance inputs and drive the authoritative workers."""
from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path
from typing import Any

from acceptance.framework import (Category, StageCase, StageExecution, Status,
                                  initialize_acceptance_database,
                                  require_live_authorization)
from common.gemini import VertexGeminiClient, configured_model
from workflow import (GeminiAdaptationWorker, GeminiDeterminationWorker,
                      GeminiEditorialPlanningWorker, GeminiIntakeWorker,
                      GeminiPipelineRunner, VisualPlanner, WorkflowStore,
                      EditorialPlanningWorker)
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


class _FrozenFixtureClient:
    """A local, no-network response source used only to prepare one live stage."""

    model = "acceptance-frozen-stage-fixture"
    last_usage = None

    def __init__(self, response: dict[str, Any]):
        self.response = response

    def generate_json(self, prompt: str, schema: dict[str, Any], *, temperature: float) -> dict[str, Any]:
        return deepcopy(self.response)


def _fixture_brief(pipeline_id: str) -> dict[str, Any]:
    targets = {
        "english": ("break the ice", "intermediate English learners", "Teach a practical workplace expression."),
        "ai_tech": ("AI meeting assistant scope", "AI tool evaluators", "Explain a hypothetical, reviewable AI workflow."),
        "psychology": ("hesitation in an unfamiliar group", "people joining a new group", "Explain an observation without diagnosis."),
    }
    target, audience, goal = targets[pipeline_id]
    return {
        "editorial_goal": goal,
        "topic": target,
        "coverage_kind": "language_subject",
        "canonical_target": target,
        "revision_scope": "whole_brief",
        "audience": audience,
        "desired_outcome": "teach",
        "constraints": {"stage_fixture": "frozen_stage_fixture_v1"},
        "source_context": "Frozen local acceptance fixture; not external evidence.",
        "open_questions": [],
    }


def _fixture_decision(catalog: list[dict[str, Any]], pipeline_id: str) -> dict[str, Any]:
    routes = []
    for item in catalog:
        selected = item["pipeline_id"] == pipeline_id
        routes.append({
            "pipeline_id": item["pipeline_id"],
            "disposition": "selected" if selected else "skipped",
            "fit": "strong fixture fit" if selected else "outside this frozen fixture remit",
            "reason": "Frozen stage fixture selects this domain." if selected else "Frozen stage fixture reserves this case for another domain.",
            "outputs": item["outputs"] if selected else [],
        })
    return {
        "outcome": "accepted",
        "opportunity_value": "A bounded frozen fixture for one independently tested text stage.",
        "rationale": "The stage fixture supplies a single selected domain and a fixed upstream handoff.",
        "warnings": [],
        "routes": routes,
    }


def _fixture_canonical(pipeline_id: str) -> dict[str, Any]:
    payloads = {
        "english": {
            "target_kind": "idiom", "target": "break the ice",
            "plain_meaning": "Make an unfamiliar social situation feel easier.",
            "nuance": "It focuses on easing initial tension.",
            "register_and_region": "Neutral conversational English.",
            "usage_notes": ["Use it when people are meeting or feel awkward."],
            "avoid_misuse": ["Do not use it for literal ice unless making a joke."],
        },
        "ai_tech": {
            "product_or_feature": "AI meeting assistant",
            "change_summary": "A hypothetical assistant workflow for meeting preparation.",
            "as_of_context": "Conceptual example; no current product claim.",
            "availability_scope": "No availability claim is made.",
            "capabilities": ["Draft a neutral opening question."],
            "use_cases": ["Prepare for a first team meeting."],
            "limitations": ["A human must review tone and accuracy."],
        },
        "psychology": {
            "observed_behavior": "People may hesitate in an unfamiliar group.",
            "context": "A first business meeting.",
            "concept": "Social uncertainty.",
            "possible_mechanism": "A low-stakes prompt may reduce ambiguity.",
            "alternative_explanations": ["Participants may simply need more time."],
            "example": "A host asks a neutral question before the agenda.",
            "practical_implications": ["Make participation optional."],
            "qualification": "This is a general interpretation, not a diagnosis.",
        },
    }
    return {
        "hook": f"A useful {pipeline_id} angle",
        "context": "A practical, carefully qualified explanation.",
        "key_points": ["Start with the audience need.", "Use a concrete example."],
        "examples": ["A fictional first-meeting scenario."],
        "takeaway": "Use the idea deliberately and review it before publication.",
        "cta": None,
        "claims": [{
            "claim_id": f"{pipeline_id}.example.1",
            "text": "The scenario is illustrative rather than a verified event.",
            "claim_kind": "generated_example",
            "evidence_reference_ids": [],
            "qualification": "Fictional example.",
        }],
        "domain_payload": payloads[pipeline_id],
    }


def _seed_stage_fixture(store: WorkflowStore, case: StageCase) -> None:
    """Prepare a fixed upstream handoff without any provider calls.

    The target stage remains the only model-backed worker in this acceptance
    attempt. Earlier stage records are created through their normal workers so
    their persisted lineage is production-shaped rather than hand-written SQL.
    """
    fixture_id = case.case.input["fixture_id"]
    pipelines = {
        "english_evergreen_v1": "english",
        "ai_scope_v1": "ai_tech",
        "psychology_uncertainty_v1": "psychology",
    }
    try:
        pipeline_id = pipelines[fixture_id]
    except KeyError as error:
        raise ValueError(f"unsupported frozen stage fixture {fixture_id!r}") from error
    brief = _fixture_brief(pipeline_id)
    store.create_human_idea(brief["editorial_goal"], command_id=f"frozen-{fixture_id}-{case.attempt}")
    if GeminiIntakeWorker(store, _FrozenFixtureClient(brief), instance_id="acceptance-frozen-intake").run_once() is None:
        raise ValueError("frozen stage fixture did not create a BriefRevision")
    request = store.connection.execute(
        "SELECT input_snapshot_json FROM determination_requests WHERE status='pending' ORDER BY determination_request_id DESC LIMIT 1"
    ).fetchone()
    if request is None:
        raise ValueError("frozen stage fixture did not create a DeterminationRequest")
    catalog = json.loads(request["input_snapshot_json"])["catalog"]
    if GeminiDeterminationWorker(store, _FrozenFixtureClient(_fixture_decision(catalog, pipeline_id)),
                                 instance_id="acceptance-frozen-determination").run_once() is None:
        raise ValueError("frozen stage fixture did not create a DeterminationDecision")
    if case.case.start_stage in {"generation", "adaptation"}:
        if EditorialPlanningWorker(store, instance_id="acceptance-frozen-editorial").run_once() is None:
            raise ValueError("frozen stage fixture did not create a ContentJob")
    if case.case.start_stage == "adaptation":
        if GeminiPipelineRunner(store, _FrozenFixtureClient(_fixture_canonical(pipeline_id)),
                                instance_id="acceptance-frozen-generation").run_once() is None:
            raise ValueError("frozen stage fixture did not create canonical content")
        if VisualPlanner(store, instance_id="acceptance-frozen-visual").run_once() is None:
            raise ValueError("frozen stage fixture did not create a visual recipe")


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
    if case.source_kind == "stage_fixture":
        # Fixture setup must not reserve production model budget or be counted
        # as a live call. It writes only a frozen upstream handoff.
        with WorkflowStore(database) as fixture_store:
            _seed_stage_fixture(fixture_store, stage_case)
    requested = ("intake", "determination", "editorial_planning", "generation", "visual_selection", "adaptation")
    active = requested[requested.index(case.start_stage):requested.index(case.end_stage) + 1]
    executed: list[str] = []
    with WorkflowStore(database, model_budget_policy=text_policy) as store:
        if case.source_kind == "human":
            store.create_human_idea(case.input["idea"], command_id=f"acceptance-{case.case_id}-{stage_case.attempt}")
        elif case.source_kind == "detection_fixture":
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
