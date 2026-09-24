"""Explicitly opt-in local acceptance runner for real Vertex Gemini stages."""
from __future__ import annotations

from argparse import ArgumentParser
from decimal import Decimal
import json
import os
from pathlib import Path
import sys
from typing import Any, Mapping

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT))

from acceptance import FRAMEWORK_VERSION
from acceptance.framework import (
    AcceptanceError, Case, RunWorkspace, StageCase, StageExecution, Status,
    StageRegistry,
    authorize_live, build_run_budget, configured_worst_case, discover_cases,
    case_fits_remaining, Category, evaluate_hard_invariants, initialize_acceptance_database,
    require_live_authorization, result_dict, write_json,
)
from acceptance.adapters import execute_case
from acceptance.evaluators import evaluate_pipeline
from common.environment import load_environment_file
from common.gemini import configured_model
from common.timestamps import utc_now
from workflow.model_budget import ModelBudgetPolicy


def _parse_repeat(value: str) -> int:
    try:
        parsed = int(value, 10)
    except ValueError:
        raise ValueError("--repeat must be a positive integer") from None
    if str(parsed) != value or parsed < 1:
        raise ValueError("--repeat must be a positive integer")
    return parsed


def _integer(value: str) -> int:
    try:
        result = int(value, 10)
    except ValueError:
        raise ValueError("must be a positive integer") from None
    if str(result) != value or result < 1:
        raise ValueError("must be a positive integer")
    return result


def _policies(environment: Mapping[str, str], need_images: bool):
    text = ModelBudgetPolicy.from_environment(configured_model(), environment)
    image = ModelBudgetPolicy.from_environment(
        environment.get("GEMINI_IMAGE_MODEL", "gemini-3.1-flash-image"), environment, image=True
    ) if need_images else None
    return text, image


def _planned(cases: list[Case], text_policy: Any, image_policy: Any | None, repeat: int):
    rows = []
    for case in cases:
        calls, images, cost = configured_worst_case(case, text_policy, image_policy)
        for attempt in range(1, repeat + 1):
            rows.append({"case_id": case.case_id, "attempt": attempt, "stage": case.stage,
                         "start_stage": case.start_stage, "end_stage": case.end_stage,
                         "source_kind": case.source_kind, "max_calls": calls,
                         "max_image_calls": images,
                         "estimated_max_cost_usd": str(Decimal(cost) / Decimal(1_000_000))})
    return rows


def _intake_executor(stage_case: StageCase, database: Path, authorization: Any, text_policy: Any) -> StageExecution:
    # Only this function constructs the live provider client. It requires the
    # authorization object returned by the central environment + CLI gate.
    require_live_authorization(authorization)
    if stage_case.case.stage != "intake" or stage_case.case.source_kind != "human":
        return StageExecution(Status.ERROR, stage_case.case.stage, None,
                              error="No live adapter is registered for this source/stage pair in Pass 1.")
    from workflow import GeminiIntakeWorker, WorkflowStore
    from common.gemini import VertexGeminiClient
    from common.gemini import configured_model
    initialize_acceptance_database(database)
    with WorkflowStore(database, model_budget_policy=text_policy) as store:
        request_id = store.create_human_idea(
            stage_case.case.input["idea"],
            command_id=f"acceptance-{stage_case.parent_case_id}-{stage_case.attempt}",
        )
        client = VertexGeminiClient(
            max_output_tokens=text_policy.phase_limits["intake"][1],
            thinking_level="LOW" if configured_model().startswith("gemini-3") else None,
        )
        worker = GeminiIntakeWorker(store, client, instance_id=f"acceptance-{stage_case.parent_case_id}-{stage_case.attempt}")
        try:
            worker.run_once()
        except Exception as error:
            invocation = store.connection.execute(
                "SELECT model_id,outcome FROM model_invocations WHERE entity_type='intake_request' AND entity_id=?",
                (request_id,),
            ).fetchone()
            reservation = store.connection.execute(
                "SELECT COALESCE(SUM(CASE WHEN status='settled' THEN settled_micro_usd ELSE worst_case_micro_usd END),0) FROM gemini_budget_reservations WHERE claim_type='intake_requests' AND claim_id=?",
                (request_id,),
            ).fetchone()[0]
            # No prompts, auth configuration, or raw exception text are copied
            # into operational logs. The local case artifact captures only type.
            return StageExecution(Status.ERROR, "intake", None if invocation is None else invocation[0],
                                  output={"request_id": request_id},
                                  calls=int(invocation is not None and invocation["outcome"] != "blocked"),
                                  estimated_cost_micro_usd=int(reservation),
                                  error=f"{type(error).__name__}: provider or stage execution failed",
                                  error_category=(Category.BUDGET if invocation is not None and invocation["outcome"] == "blocked"
                                                  else Category.PROVIDER))
        request = store.connection.execute(
            "SELECT status FROM intake_requests WHERE intake_request_id=?", (request_id,)
        ).fetchone()
        revision = store.connection.execute(
            "SELECT brief_json FROM brief_revisions WHERE source_intake_request_id=?", (request_id,)
        ).fetchone()
        invocation = store.connection.execute(
            "SELECT model_id,outcome,estimated_cost_micro_usd FROM model_invocations WHERE entity_type='intake_request' AND entity_id=?",
            (request_id,),
        ).fetchone()
        reservation = store.connection.execute(
            "SELECT COALESCE(SUM(CASE WHEN status='settled' THEN settled_micro_usd ELSE worst_case_micro_usd END),0) FROM gemini_budget_reservations WHERE claim_type='intake_requests' AND claim_id=?",
            (request_id,),
        ).fetchone()[0]
        if not invocation:
            return StageExecution(Status.ERROR, "intake", client.model,
                                  output={"request_id": request_id, "status": request[0]},
                                  error="No model invocation was recorded by the production ledger.",
                                  error_category=Category.LINEAGE)
        output = {"request_id": request_id, "status": request[0],
                  "brief": None if revision is None else json.loads(revision[0]),
                  "invocation_outcome": invocation["outcome"]}
        stage_status = Status.PASS if request[0] in {"completed", "needs_clarification"} and invocation["outcome"] == "succeeded" else Status.ERROR
        error_category = (Category.BUDGET if invocation["outcome"] == "blocked" else
                          Category.CONTRACT if invocation["outcome"] in {"invalid_output", "parse_failed", "schema_failed"} else
                          Category.PROVIDER)
        return StageExecution(stage_status, "intake", invocation["model_id"], output,
                              calls=int(invocation["outcome"] != "blocked"), estimated_cost_micro_usd=int(reservation),
                              error=None if stage_status == Status.PASS else "Intake did not complete successfully.",
                              error_category=error_category)


def _summary(results: list[dict[str, Any]], budget: dict[str, Any], planned: list[dict[str, Any]]) -> str:
    counts = {status.value: sum(item["status"] == status.value for item in results) for status in Status}
    cost = (int(Decimal(budget["planned_max_cost_usd"]) * 1_000_000)
            if budget["mode"] == "dry_run" else
            sum(int(Decimal(item["estimated_cost_usd"]) * 1_000_000) for item in results))
    inspect = [f"- `{r['case_id']}` attempt {r['attempt']}: {r['status']}" for r in results if r["status"] not in {"PASS", "SKIP"}]
    findings = [finding for result in results for finding in result["findings"]]
    provider_errors = sum(f["category"] == "provider" and f["status"] in {"ERROR", "FAIL"} for f in findings)
    contract_errors = sum(f["category"] == "contract" and f["status"] in {"ERROR", "FAIL"} for f in findings)
    budget_findings = sum(f["category"] == "budget" for f in findings)
    lines = ["# Gemini acceptance run", "", f"Run profile: `{budget['profile']}`; mode: `{budget['mode']}`.",
             f"Models: text `{budget['text_model']}`; image `{budget['image_model'] or 'not configured'}`.",
             "", "## Results", "",
             " | ".join(f"{name}: {counts[name]}" for name in counts),
             f"{'Planned maximum' if budget['mode'] == 'dry_run' else 'Estimated'} spend: ${Decimal(cost) / Decimal(1_000_000):.6f} of ${budget['max_usd']} ceiling.",
             f"Planned attempts: {len(planned)}; actual provider calls: {sum(r['calls'] for r in results)}; image calls: {sum(r['image_calls'] for r in results)}.", "", "## Cases needing inspection", ""]
    lines.extend(inspect or ["- None."])
    lines += ["", "## Provider, contract, and budget findings", "",
              f"Provider errors: {provider_errors}; contract errors: {contract_errors}; budget findings: {budget_findings} (including {counts['SKIP_BUDGET']} budget skips).",
              "", ("Dry-run cost is a planned maximum; no spend occurred." if budget["mode"] == "dry_run"
                   else "Costs are estimates or conservative production-ledger reservations, not a billing statement."), ""]
    return "\n".join(lines)


def _write_stage_artifacts(attempt_dir: Path, execution: StageExecution) -> None:
    """Keep partial successful handoffs inspectable after a later stage fails."""
    for stage, value in execution.output.items():
        if stage in {"intake", "determination", "editorial_planning", "generation", "visual_selection", "adaptation"}:
            filename = {"editorial_planning": "editorial_plan", "generation": "canonical",
                        "visual_selection": "visual_recipe"}.get(stage, stage)
            write_json(attempt_dir / f"{filename}.json", value)


def _stability(results: list[dict[str, Any]]) -> dict[str, Any]:
    """Report repeat consistency without treating wording changes as failures."""
    grouped: dict[str, list[dict[str, Any]]] = {}
    for result in results:
        grouped.setdefault(result["case_id"], []).append(result)
    rows = []
    for case_id in sorted(grouped):
        attempts = grouped[case_id]
        successful = [item for item in attempts if item["status"] in {"PASS", "WARN"}]
        outputs = [item.get("output", {}) for item in successful]
        routes = [tuple(sorted(route["pipeline_id"] for route in output.get("determination", {}).get("routes", []) if route["disposition"] == "selected")) for output in outputs]
        outcomes = [output.get("determination", {}).get("outcome") for output in outputs]
        lanes = [output.get("editorial_planning", {}).get("plan", {}).get("lane") for output in outputs]
        slides = [len(output.get("adaptation", {}).get("package", {}).get("visual_units", [])) for output in outputs if output.get("adaptation")]
        conservation_ok = [not any(f["code"].startswith("conservation_") and f["status"] == "FAIL" for f in item["findings"]) for item in successful]
        stable = lambda values: None if len(values) < 2 else len(set(values)) == 1
        rows.append({"case_id": case_id, "attempts": len(attempts), "successful_attempts": len(successful),
                     "schema_success_rate": None if not attempts else len(successful) / len(attempts),
                     "determination_route_stable": stable(routes), "determination_outcome_stable": stable(outcomes),
                     "editorial_lane_stable": stable(lanes), "adaptation_slide_count_stable": stable(slides),
                     "conservation_success_rate": None if not conservation_ok else sum(conservation_ok) / len(conservation_ok)})
    return {"schema_version": 1, "cases": rows}


def run_matrix(*, profile: str, dry_run: bool, cli_live: bool, repeat: int,
               limits: dict[str, Any], environment: Mapping[str, str],
               case_directory: Path, output_root: Path) -> tuple[Path, dict[str, Any]]:
    all_cases = discover_cases(case_directory)
    selected = [case for case in all_cases if profile in case.profiles]
    if not selected:
        raise AcceptanceError(f"profile {profile!r} selected no cases")
    needs_images = any(case.live_budget["image_calls"] for case in selected)
    text_policy, image_policy = _policies(environment, needs_images)
    planned = _planned(selected, text_policy, image_policy, repeat)
    planned_calls = sum(p["max_calls"] for p in planned)
    planned_images = sum(p["max_image_calls"] for p in planned)
    budget = build_run_budget(limits, environment, planned_calls=planned_calls,
                              planned_images=planned_images, planned_cases=len(planned))
    authorization = None if dry_run else authorize_live(cli_live=cli_live, environment=environment)
    stage_registry = None if dry_run else StageRegistry({"intake": _intake_executor})
    workspace = RunWorkspace.create(output_root)
    write_json(workspace.root / "run.json", {
        "schema_version": 1, "framework_version": FRAMEWORK_VERSION,
        "run_id": workspace.run_id, "started_at": workspace.started_at,
        "ended_at": None, "git_revision": _git_revision(), "profile": profile,
        "mode": "dry_run" if dry_run else "live", "text_model": text_policy.model_id,
        "image_model": None if image_policy is None else image_policy.model_id,
        "acceptance_budget": {"max_usd": str(budget.max_usd), "max_calls": budget.max_calls,
                              "max_image_calls": budget.max_image_calls, "max_cases": budget.max_cases},
        "planned_attempts": len(planned), "result_counts": {},
        "estimated_cost_usd": "0", "cases": [p["case_id"] for p in planned],
    })
    write_json(workspace.root / "plan.json", {"profile": profile, "repeat": repeat,
                                                "planned": planned, "selected_case_ids": [c.case_id for c in selected]})
    results: list[dict[str, Any]] = []
    spent = used_calls = used_images = used_cases = 0
    by_id = {c.case_id: c for c in selected}
    for plan in planned:
        case = by_id[plan["case_id"]]
        envelope = int(Decimal(plan["estimated_max_cost_usd"]) * 1_000_000)
        fits = case_fits_remaining(case_calls=plan["max_calls"],
                case_image_calls=plan["max_image_calls"], case_cost_micro_usd=envelope,
                remaining_calls=budget.max_calls - used_calls,
                remaining_image_calls=budget.max_image_calls - used_images,
                remaining_cases=budget.max_cases - used_cases,
                remaining_micro_usd=int(budget.max_usd * 1_000_000) - spent)
        stage_case = StageCase(case, plan["attempt"], case.case_id)
        if not fits:
            evaluation_status = Status.SKIP_BUDGET
            execution = StageExecution(Status.SKIP_BUDGET, case.stage, None,
                                       error="The full case envelope does not fit in the remaining run budget.")
            from acceptance.framework import Finding, Category, StageEvaluation
            evaluation = StageEvaluation(evaluation_status, (Finding(case.case_id, case.stage,
                Status.SKIP_BUDGET, Category.BUDGET, "case_envelope_exceeds_remaining", execution.error),))
        elif dry_run:
            from acceptance.framework import Finding, Category, StageEvaluation
            execution = StageExecution(Status.SKIP, case.stage, None, output={"planned": True},
                                       estimated_cost_micro_usd=envelope)
            evaluation = StageEvaluation(Status.SKIP, (Finding(case.case_id, case.stage, Status.SKIP,
                Category.CONTRACT, "dry_run", "Provider execution omitted in dry-run mode."),))
            used_calls += plan["max_calls"]; used_images += plan["max_image_calls"]; used_cases += 1
            spent += envelope
        else:
            attempt_dir = workspace.case_attempt(case.case_id, plan["attempt"])
            write_json(attempt_dir / "input.json", case.input)
            database = attempt_dir / "workflow.db"
            try:
                # Preserve Pass 1's direct Intake executor for v1 compatibility;
                # v2 routes each requested range through the modular production adapters.
                if case.schema_version == 1 and case.stage == "intake":
                    execution = stage_registry.execute(stage_case, database, authorization, text_policy)
                    evaluation = evaluate_hard_invariants(stage_case, execution)
                else:
                    execution = execute_case(stage_case, database, authorization, text_policy)
                    evaluation = evaluate_pipeline(stage_case, execution)
            except Exception as error:
                execution = StageExecution(Status.ERROR, case.stage, None,
                                           error=f"{type(error).__name__}: case execution failed")
                evaluation = evaluate_hard_invariants(stage_case, execution)
            used_calls += execution.calls; used_images += execution.image_calls; used_cases += 1
            spent += execution.estimated_cost_micro_usd
            write_json(attempt_dir / "evaluation.json", result_dict(stage_case, execution, evaluation))
            _write_stage_artifacts(attempt_dir, execution)
            if database.exists():
                # SQLite stores no secrets; keep it as inspectable run evidence.
                pass
            results.append(result_dict(stage_case, execution, evaluation))
            continue
        attempt_dir = workspace.case_attempt(case.case_id, plan["attempt"])
        write_json(attempt_dir / "input.json", case.input)
        write_json(attempt_dir / "evaluation.json", result_dict(stage_case, execution, evaluation))
        results.append(result_dict(stage_case, execution, evaluation))
    actual_cost = (0 if dry_run else
                   sum(int(Decimal(item["estimated_cost_usd"]) * 1_000_000) for item in results))
    planned_max_cost = sum(int(Decimal(row["estimated_max_cost_usd"]) * 1_000_000) for row in planned)
    counts = {status.value: sum(item["status"] == status.value for item in results) for status in Status}
    cost_rows = []
    plan_by_attempt = {(row["case_id"], row["attempt"]): row for row in planned}
    for result in results:
        plan = plan_by_attempt[(result["case_id"], result["attempt"])]
        cost_rows.append({"case_id": result["case_id"], "attempt": result["attempt"], "stage": result["stage"],
                          "model_id": result["model_id"], "text_calls": result["calls"] - result["image_calls"],
                          "image_calls": result["image_calls"], "estimated_cost_usd": "0" if dry_run else result["estimated_cost_usd"],
                          "planned_max_calls": plan["max_calls"],
                          "planned_max_image_calls": plan["max_image_calls"],
                          "estimated_max_cost_usd": plan["estimated_max_cost_usd"]})
    write_json(workspace.root / "costs.json", {"schema_version": 1, "currency": "USD",
               "basis": "planned_case_maxima" if dry_run else "estimated_cost_or_conservative_production_reservation",
               "total_estimated_cost_usd": str(Decimal(actual_cost) / Decimal(1_000_000)),
               "total_estimated_max_cost_usd": str(Decimal(planned_max_cost) / Decimal(1_000_000)),
               "cases": cost_rows})
    stability = _stability(results)
    write_json(workspace.root / "stability.json", stability)
    run_info = {"schema_version": 1, "framework_version": FRAMEWORK_VERSION,
        "run_id": workspace.run_id, "started_at": workspace.started_at, "ended_at": utc_now(),
        "git_revision": _git_revision(), "profile": profile, "mode": "dry_run" if dry_run else "live",
        "text_model": text_policy.model_id, "image_model": None if image_policy is None else image_policy.model_id,
        "acceptance_budget": {"max_usd": str(budget.max_usd), "max_calls": budget.max_calls,
                              "max_image_calls": budget.max_image_calls, "max_cases": budget.max_cases},
        "estimated_cost_usd": str(Decimal(actual_cost) / Decimal(1_000_000)),
        "planned_max_cost_usd": str(Decimal(planned_max_cost) / Decimal(1_000_000)),
        "result_counts": counts, "actual_calls": sum(r["calls"] for r in results),
        "actual_image_calls": sum(r["image_calls"] for r in results),
        "stability_report": "stability.json"}
    write_json(workspace.root / "run.json", run_info)
    (workspace.root / "summary.md").write_text(_summary(results, {**run_info, "max_usd": str(budget.max_usd)}, planned))
    return workspace.root, run_info


def _git_revision() -> str | None:
    import subprocess
    try:
        return subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True,
                              capture_output=True, check=True, timeout=2).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return None


def main(argv: list[str] | None = None) -> int:
    load_environment_file(ROOT / ".env")
    parser = ArgumentParser(description=__doc__)
    parser.add_argument("--profile", choices=sorted({"smoke", "stage", "regression", "full"}), default="smoke")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--live-gemini", action="store_true")
    parser.add_argument("--max-usd")
    parser.add_argument("--max-calls", type=_integer)
    parser.add_argument("--max-image-calls", type=_integer)
    parser.add_argument("--max-cases", type=_integer)
    parser.add_argument("--repeat", type=_parse_repeat, default=1)
    parser.add_argument("--cases", type=Path, default=ROOT / "acceptance" / "cases")
    parser.add_argument("--output-root", type=Path, default=ROOT / "data" / "acceptance")
    args = parser.parse_args(argv)
    if args.live_gemini and args.dry_run:
        parser.error("--live-gemini cannot be combined with --dry-run")
    try:
        output, run_info = run_matrix(profile=args.profile, dry_run=args.dry_run,
            cli_live=args.live_gemini,
            repeat=args.repeat,
            limits={"max_usd": args.max_usd, "max_calls": args.max_calls,
                    "max_image_calls": args.max_image_calls, "max_cases": args.max_cases},
            environment=os.environ, case_directory=args.cases, output_root=args.output_root)
    except AcceptanceError as error:
        parser.error(str(error))
    except (ValueError, RuntimeError) as error:
        parser.error(str(error))
    cost_label = "planned maximum" if run_info["mode"] == "dry_run" else "estimated spend"
    cost_value = run_info["planned_max_cost_usd"] if run_info["mode"] == "dry_run" else run_info["estimated_cost_usd"]
    print(f"{run_info['mode']} run {run_info['run_id']}: {run_info['result_counts']} ; {cost_label} ${cost_value} ; artifacts {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
