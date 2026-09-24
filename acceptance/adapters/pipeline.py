"""Persist isolated acceptance inputs and drive the authoritative workers."""
from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path
from typing import Any

from acceptance.framework import (Category, StageCase, StageExecution, Status, TEXT_STAGES,
                                  initialize_acceptance_database,
                                  require_live_authorization)
from common.gemini import VertexGeminiClient, configured_model
from common.gemini_image import VertexGeminiImageClient
from workflow import (GeminiAdaptationWorker, GeminiDeterminationWorker,
                      GeminiEditorialPlanningWorker, GeminiIntakeWorker,
                      GeminiPipelineRunner, VisualPlanner, WorkflowStore,
                      EditorialPlanningWorker, StoryboardPlanner)
from workflow.gemini_image_renderer import DispatchVisualRenderer
from workflow.gemini_prompt_compiler import build_storyboard_prompt
from workflow.store import canonical, digest, now


def _client(policy: Any, phase: str) -> VertexGeminiClient:
    return VertexGeminiClient(
        max_output_tokens=policy.phase_limits[phase][1],
        thinking_level="LOW" if configured_model().startswith("gemini-3") else None,
    )


def _seed_detection_input(store: WorkflowStore, brief: dict[str, Any], evidence: dict[str, Any]) -> None:
    """Create the same frozen Determination shape used by Scout handoff.

    Detection collection/scoring is deliberately outside live text acceptance.
    The fixture is already frozen evidence; this writes its downstream
    Determination handoff into the isolated production database.
    """
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


def _seed_detection_fixture(store: WorkflowStore, case: StageCase) -> None:
    """Create the frozen Detection handoff declared by an acceptance case."""
    _seed_detection_input(store, case.case.input["frozen_brief"], case.case.input["source_evidence"])


class _FrozenFixtureClient:
    """A local, no-network response source used only to prepare one live stage."""

    model = "acceptance-frozen-stage-fixture"
    last_usage = None

    def __init__(self, response: dict[str, Any]):
        self.response = response

    def generate_json(self, prompt: str, schema: dict[str, Any], *, temperature: float) -> dict[str, Any]:
        return deepcopy(self.response)


PSYCHOLOGY_HARDENING_FIXTURES = {
    "psychology_unfamiliar_group_v1": ("Hesitation in an unfamiliar group", "A person speaks less during their first meeting with an unfamiliar group."),
    "psychology_quiet_employee_v1": ("Quiet employee in a large meeting", "An employee contributes little during a large team meeting but participates actively in smaller discussions."),
    "psychology_delayed_response_v1": ("Delayed text response", "Someone regularly takes several hours to respond to messages."),
    "psychology_deadline_start_v1": ("Deadline-near assignment start", "A student repeatedly starts an assignment shortly before the deadline."),
    "psychology_eye_contact_v1": ("Less eye contact", "Someone makes less eye contact during a conversation."),
    "psychology_workplace_disagreement_v1": ("Workplace disagreement", "A coworker disagrees with a proposal in a meeting but says little afterward."),
    "psychology_reaction_checking_v1": ("Checking social-media reactions", "A person frequently checks how many reactions their posts receive."),
    "psychology_time_alone_v1": ("Requesting time alone", "One partner asks for more time alone after several busy weeks."),
    "psychology_group_preference_v1": ("Changed group preference", "A participant changes their stated preference after hearing that everyone else chose differently."),
    "psychology_option_comparison_v1": ("Continued option comparison", "A shopper continues comparing options after finding one that meets all stated requirements."),
}


def _fixture_brief(pipeline_id: str, fixture_id: str | None = None) -> dict[str, Any]:
    if fixture_id in PSYCHOLOGY_HARDENING_FIXTURES:
        target, observation = PSYCHOLOGY_HARDENING_FIXTURES[fixture_id]
        return {
            "editorial_goal": "Explain the stated observation without diagnosing a person or asserting an unobserved reason.",
            "topic": target,
            "coverage_kind": "behavior_observation",
            "canonical_target": target,
            "revision_scope": "whole_brief",
            "audience": "people considering an everyday social or behavioral observation",
            "desired_outcome": "inform",
            "constraints": {"stage_fixture": "psychology_epistemic_hardening_v1", "observation": observation},
            "source_context": observation,
            "open_questions": [],
        }
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


def _bounded_ai_detection_fixture() -> tuple[dict[str, Any], dict[str, Any]]:
    return ({
        "editorial_goal": "Explain a source-backed enterprise feature update.",
        "topic": "Acme Enterprise assistant availability",
        "coverage_kind": "trend_topic",
        "canonical_target": "Acme Enterprise assistant availability",
        "revision_scope": "whole_brief",
        "audience": "AI tool evaluators",
        "desired_outcome": "inform",
        "constraints": {"source_bound": True},
        "source_context": "Frozen bounded-evidence event fixture.",
        "open_questions": [],
    }, {
        "evidence": [{
            "reference_id": "fixture:acme:1",
            "title": "Acme announces Enterprise assistant",
            "detail": "On 2026-09-20, Acme announced an Enterprise assistant. The announcement says it will be available to Enterprise plan customers in October 2026, with centralized administrative controls and an integration with Acme Data Workspace. It does not state pricing, security certifications, geographic availability, performance benchmarks, rollout phases, deployment requirements, or comparisons with earlier versions.",
            "evidence_time": "2026-09-20T00:00:00",
        }],
        "candidate": {"topic": "Acme Enterprise assistant availability"},
    })


def _bounded_ai_plan(snapshot: dict[str, Any]) -> dict[str, Any]:
    reference = snapshot["allowed_evidence_reference_ids"][0]
    qualifications = ["source_backed_claims", "dated_context", "availability_scope", "limitations", "provider_claim_distinction"]
    candidates = [
        {
            "candidate_id": "confirmed-update", "angle": "What the dated Enterprise assistant announcement confirms and leaves open.",
            "angle_type": "what_changed", "reader_promise": "Separate confirmed access and feature facts from the details evaluators cannot yet infer.",
            "relevance": "AI tool evaluators need a bounded view of an announced Enterprise assistant.",
            "must_cover_points": ["September 20 announcement", "October 2026 Enterprise-plan availability", "centralized administrative controls", "Acme Data Workspace integration", "unstated pricing, certification, geography, benchmarks, rollout, deployment, and comparison details"],
            "evidence_reference_ids": [reference], "evidence_requirements": ["Use only stated announcement facts and identify the named omissions."],
            "qualification_requirements": qualifications,
        },
        {
            "candidate_id": "evaluation-boundary", "angle": "What an evaluator can confirm now versus what remains unavailable.",
            "angle_type": "limitations", "reader_promise": "Give evaluators a source-bound checklist without treating omissions as product claims.",
            "relevance": "The announced availability and controls are useful only with clear limits on unknown details.",
            "must_cover_points": ["dated source", "Enterprise-plan scope", "confirmed controls and integration", "all named unknown categories"],
            "evidence_reference_ids": [reference], "evidence_requirements": ["Do not infer an omitted category from the product name or plan."],
            "qualification_requirements": qualifications,
        },
    ]
    return {
        "domain": "ai_tech", "lane": "trend", "audience_intent": "Inform AI tool evaluators with a source-bound update.",
        "why_now": "The source records a September 20, 2026 announcement with October 2026 availability.",
        "candidates": candidates, "selected_candidate_id": "confirmed-update",
        "selection_rationale": "The confirmed-update angle keeps provider claims and omissions visibly separate.",
        "selection_dimensions": {dimension: "Frozen bounded-evidence fixture." for dimension in ("domain_fit", "audience_usefulness", "evidence_strength", "timeliness", "novelty", "explanatory_potential")},
        "series_key": None, "experiment_key": None, "experiment_intention": None,
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
        "ai_bounded_evidence_v1": "ai_tech",
        "psychology_uncertainty_v1": "psychology",
        **{fixture_id: "psychology" for fixture_id in PSYCHOLOGY_HARDENING_FIXTURES},
    }
    try:
        pipeline_id = pipelines[fixture_id]
    except KeyError as error:
        raise ValueError(f"unsupported frozen stage fixture {fixture_id!r}") from error
    if fixture_id == "ai_bounded_evidence_v1":
        brief, evidence = _bounded_ai_detection_fixture()
        _seed_detection_input(store, brief, evidence)
    else:
        brief = _fixture_brief(pipeline_id, fixture_id)
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
        if fixture_id == "ai_bounded_evidence_v1":
            planning_run = store.connection.execute(
                "SELECT input_snapshot_json FROM editorial_plan_runs WHERE status='pending' ORDER BY editorial_plan_run_id DESC LIMIT 1"
            ).fetchone()
            if planning_run is None:
                raise ValueError("bounded stage fixture did not create an EditorialPlanRun")
            plan = _bounded_ai_plan(json.loads(planning_run["input_snapshot_json"]))
            editorial = GeminiEditorialPlanningWorker(store, _FrozenFixtureClient(plan), instance_id="acceptance-frozen-editorial")
        else:
            editorial = EditorialPlanningWorker(store, instance_id="acceptance-frozen-editorial")
        if editorial.run_once() is None:
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
        f"SELECT model_invocation_id,phase,model_id,outcome,estimated_cost_micro_usd FROM model_invocations WHERE phase IN ({placeholders}) ORDER BY model_invocation_id",
        phases,
    ).fetchall()
    calls = sum(row["outcome"] != "blocked" for row in rows)
    image_calls = sum(row["phase"] == "image_rendering" and row["outcome"] != "blocked" for row in rows)
    cost = sum(int(row["estimated_cost_micro_usd"] or 0) for row in rows)
    model = None if not rows else rows[-1]["model_id"]
    return calls, image_calls, model, cost


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
    storyboard = store.connection.execute("SELECT storyboard_plan_id,schema_version,planner_version,total_slides,boards_json FROM storyboard_plans ORDER BY storyboard_plan_id DESC LIMIT 1").fetchone()
    if storyboard:
        result["storyboard_planning"] = {
            "storyboard_plan_id": storyboard["storyboard_plan_id"],
            "plan": {"schema_version": storyboard["schema_version"], "planner_version": storyboard["planner_version"],
                     "total_slides": storyboard["total_slides"], "boards": json.loads(storyboard["boards_json"])},
        }
    render = store.connection.execute("SELECT render_run_id,status,manifest_json FROM render_runs ORDER BY render_run_id DESC LIMIT 1").fetchone()
    if render:
        review = store.connection.execute("SELECT review_request_id,status FROM review_requests WHERE render_run_id=?", (render["render_run_id"],)).fetchone()
        result["image_rendering"] = {
            "render_run_id": render["render_run_id"], "status": render["status"],
            "manifest": None if render["manifest_json"] is None else json.loads(render["manifest_json"]),
            "review_request": None if review is None else {"review_request_id": review["review_request_id"], "status": review["status"]},
        }
    return result


def _failed_category(store: WorkflowStore, stage: str) -> Category:
    table = {"intake": "intake_requests", "determination": "determination_requests", "editorial_planning": "editorial_plan_runs", "generation": "generation_runs", "adaptation": "adaptation_runs", "storyboard_planning": "storyboard_plan_runs", "image_rendering": "render_runs"}.get(stage)
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


def _write_render_inputs(store: WorkflowStore, artifact_root: Path) -> None:
    """Keep acceptance-only prompt/plan evidence beside production render assets."""
    row = store.connection.execute(
        "SELECT cp.package_json,vr.recipe_json,sp.storyboard_plan_id,sp.schema_version,sp.planner_version,"
        "sp.total_slides,sp.boards_json,j.pipeline_id FROM render_runs rr "
        "JOIN content_packages cp ON cp.content_package_id=rr.content_package_id "
        "JOIN visual_recipes vr ON vr.visual_recipe_id=rr.visual_recipe_id "
        "JOIN storyboard_plans sp ON sp.storyboard_plan_id=rr.storyboard_plan_id "
        "JOIN output_requests o ON o.output_request_id=cp.output_request_id "
        "JOIN canonical_contents c ON c.canonical_content_id=o.canonical_content_id "
        "JOIN content_jobs j ON j.content_job_id=c.content_job_id "
        "ORDER BY rr.render_run_id DESC LIMIT 1"
    ).fetchone()
    if row is None:
        raise ValueError("render evidence requires a committed RenderRun")
    plan = {"schema_version": row["schema_version"], "planner_version": row["planner_version"],
            "total_slides": row["total_slides"], "boards": json.loads(row["boards_json"])}
    package, recipe = json.loads(row["package_json"]), json.loads(row["recipe_json"])
    artifact_root.mkdir(parents=True, exist_ok=True)
    (artifact_root / "storyboard_plan.json").write_text(json.dumps({"storyboard_plan_id": row["storyboard_plan_id"], **plan}, ensure_ascii=False, indent=2) + "\n")
    for board in plan["boards"]:
        prompt = build_storyboard_prompt(package, recipe, pipeline_id=row["pipeline_id"],
                                         board=None if row["pipeline_id"] == "english" else board)
        (artifact_root / f"prompt-board-{board['board_index']:02d}.txt").write_text(prompt + "\n")


def _write_render_outputs(output: dict[str, Any], artifact_root: Path) -> None:
    rendered = output.get("image_rendering", {})
    manifest = rendered.get("manifest")
    if manifest is None:
        return
    (artifact_root / "render-manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n")
    validations = []
    for board in manifest.get("boards", [manifest.get("storyboard")]):
        if not board:
            continue
        raw, split = board.get("raw", {}), board.get("split", {})
        validations.append({"board_index": board.get("board_index"), "grid": {"rows": board.get("rows"), "columns": board.get("cols", board.get("columns"))},
                            "capacity": board.get("capacity"), "provider_aspect_ratio": board.get("provider_aspect_ratio"),
                            "raw": raw, "raw_dimensions": split.get("raw_dimensions"),
                            "source_rectangles": split.get("source_rectangles"), "split_strategy": split.get("method"),
                            "normalization": split.get("normalization")})
    (artifact_root / "board-validation.json").write_text(json.dumps({"boards": validations}, ensure_ascii=False, indent=2) + "\n")


def execute_case(stage_case: StageCase, database: Path, authorization: Any, text_policy: Any,
                 image_policy: Any | None = None, artifact_root: Path | None = None) -> StageExecution:
    """Run an isolated production journey, including image rendering when requested."""
    require_live_authorization(authorization)
    initialize_acceptance_database(database)
    case = stage_case.case
    if case.source_kind == "stage_fixture":
        # Fixture setup must not reserve production model budget or be counted
        # as a live call. It writes only a frozen upstream handoff.
        with WorkflowStore(database) as fixture_store:
            _seed_stage_fixture(fixture_store, stage_case)
    requested = ("intake", "determination", "editorial_planning", "generation", "visual_selection", "adaptation", "storyboard_planning", "image_rendering")
    active = requested[requested.index(case.start_stage):requested.index(case.end_stage) + 1]
    executed: list[str] = []
    with WorkflowStore(database, model_budget_policy=text_policy) as store:
        if case.source_kind == "human":
            store.create_human_idea(case.input["idea"], command_id=f"acceptance-{case.case_id}-{stage_case.attempt}")
        elif case.source_kind == "detection_fixture":
            _seed_detection_fixture(store, stage_case)
        def render():
            if image_policy is None or artifact_root is None:
                raise ValueError("image rendering requires an image budget policy and an artifact workspace")
            _write_render_inputs(store, artifact_root)
            image_client = VertexGeminiImageClient(max_output_tokens=image_policy.phase_limits["image_rendering"][1])
            return DispatchVisualRenderer(store, artifact_root, image_client=image_client,
                                          budget_policy=image_policy).run_once()

        workers = {
            "intake": lambda: GeminiIntakeWorker(store, _client(text_policy, "intake"), instance_id=f"acceptance-intake-{stage_case.attempt}").run_once(),
            "determination": lambda: GeminiDeterminationWorker(store, _client(text_policy, "determination"), instance_id=f"acceptance-determination-{stage_case.attempt}").run_once(),
            "editorial_planning": lambda: GeminiEditorialPlanningWorker(store, _client(text_policy, "editorial_planning"), instance_id=f"acceptance-editorial-{stage_case.attempt}").run_once(),
            "generation": lambda: GeminiPipelineRunner(store, _client(text_policy, "generation"), instance_id=f"acceptance-generation-{stage_case.attempt}").run_once(),
            "visual_selection": lambda: VisualPlanner(store, instance_id=f"acceptance-visual-{stage_case.attempt}").run_once(),
            "adaptation": lambda: GeminiAdaptationWorker(store, _client(text_policy, "adaptation"), instance_id=f"acceptance-adaptation-{stage_case.attempt}", strict_english_capacity=True).run_once(),
            "storyboard_planning": lambda: StoryboardPlanner(store, instance_id=f"acceptance-storyboard-{stage_case.attempt}").run_once(),
            "image_rendering": render,
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
                calls, images, model, cost = _ledger(store, [s for s in active if s in {*TEXT_STAGES, "image_rendering"}])
                return StageExecution(Status.ERROR, stage, model, _outputs(store), calls, images, cost,
                                      f"Production {stage} did not complete; downstream stages were not invoked.",
                                      _failed_category(store, stage), tuple(executed))
        calls, images, model, cost = _ledger(store, [s for s in active if s in {*TEXT_STAGES, "image_rendering"}])
        output = _outputs(store)
        if "image_rendering" in active:
            _write_render_outputs(output, artifact_root)
        return StageExecution(Status.PASS, case.end_stage, model, output, calls, images, cost,
                              executed_stages=tuple(executed))
