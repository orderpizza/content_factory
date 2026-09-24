import json
from decimal import Decimal
from pathlib import Path

import pytest

from acceptance.framework import (
    AcceptanceError, Category, Finding, RunWorkspace, StageCase, StageExecution,
    StageEvaluation, StageRegistry, Status, authorize_live, build_run_budget, discover_cases,
    case_fits_remaining, evaluate_hard_invariants, initialize_acceptance_database, result_dict,
    LiveAuthorization, require_live_authorization, validate_case, write_json,
)
from acceptance.runners import matrix
from workflow.model_budget import ModelBudgetPolicy


ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "acceptance" / "cases"


def environment():
    return {
        "GEMINI_INPUT_COST_PER_MILLION_USD": "1.25",
        "GEMINI_OUTPUT_COST_PER_MILLION_USD": "5",
        "GEMINI_DAILY_WARNING_USD": "5",
        "GEMINI_DAILY_HARD_LIMIT_USD": "10",
        "GEMINI_JOB_HARD_LIMIT_USD": "2",
    }


def text_policy():
    return ModelBudgetPolicy.from_environment("fake-text", environment())


def raw_case():
    return json.loads((FIXTURES / "english_icebreaker.json").read_text())


@pytest.mark.parametrize("env,cli", [({}, False), ({}, True), ({"CONTENT_FACTORY_ENABLE_LIVE_GEMINI_TESTS": "1"}, False),
    ({"CONTENT_FACTORY_ENABLE_LIVE_GEMINI_TESTS": "true"}, True),
    ({"GOOGLE_APPLICATION_CREDENTIALS": "/tmp/fake.json", "GOOGLE_CLOUD_PROJECT": "p", "GEMINI_MODEL": "m"}, False)])
def test_central_live_gate_fails_closed(env, cli):
    with pytest.raises(AcceptanceError):
        authorize_live(cli_live=cli, environment=env)


def test_both_opt_ins_enable_eligibility():
    token = authorize_live(cli_live=True, environment={"CONTENT_FACTORY_ENABLE_LIVE_GEMINI_TESTS": "1"})
    assert token.nonce
    require_live_authorization(token)
    with pytest.raises(AcceptanceError):
        require_live_authorization(LiveAuthorization("forged", object()))


@pytest.mark.parametrize("value", ["x", "-1", "0", "NaN", "Infinity", "1e999999", ""])
def test_usd_budget_rejects_invalid_values(value):
    with pytest.raises(AcceptanceError):
        build_run_budget({"max_usd": value}, {}, planned_calls=1, planned_images=0, planned_cases=1)


def test_usd_budget_decimal_and_stricter_precedence():
    policy = build_run_budget({"max_usd": "0.30", "max_calls": 5, "max_image_calls": None, "max_cases": 4},
        {"LIVE_TEST_MAX_USD": "0.25", "LIVE_TEST_MAX_CALLS": "3", "LIVE_TEST_MAX_IMAGE_CALLS": "2", "LIVE_TEST_MAX_CASES": "2"},
        planned_calls=10, planned_images=4, planned_cases=8)
    assert policy.max_usd == Decimal("0.25")
    assert (policy.max_calls, policy.max_image_calls, policy.max_cases) == (3, 2, 2)


def test_finite_usd_ceiling_can_come_from_cli_or_environment():
    assert build_run_budget({"max_usd": "0.1"}, {}, planned_calls=1, planned_images=0, planned_cases=1).max_usd == Decimal("0.1")
    assert build_run_budget({"max_usd": "0.1"}, {"LIVE_TEST_MAX_USD": "", "LIVE_TEST_MAX_CALLS": ""}, planned_calls=1, planned_images=0, planned_cases=1).max_usd == Decimal("0.1")
    assert build_run_budget({"max_usd": None}, {"LIVE_TEST_MAX_USD": "0.2"}, planned_calls=1, planned_images=0, planned_cases=1).max_usd == Decimal("0.2")
    with pytest.raises(AcceptanceError):
        build_run_budget({}, {}, planned_calls=1, planned_images=0, planned_cases=1)


@pytest.mark.parametrize("kwargs,expected", [
    ({"case_calls": 2, "case_image_calls": 1, "case_cost_micro_usd": 10, "remaining_calls": 2, "remaining_image_calls": 1, "remaining_cases": 1, "remaining_micro_usd": 10}, True),
    ({"case_calls": 2, "case_image_calls": 1, "case_cost_micro_usd": 10, "remaining_calls": 1, "remaining_image_calls": 1, "remaining_cases": 1, "remaining_micro_usd": 10}, False),
    ({"case_calls": 2, "case_image_calls": 1, "case_cost_micro_usd": 10, "remaining_calls": 2, "remaining_image_calls": 0, "remaining_cases": 1, "remaining_micro_usd": 10}, False),
    ({"case_calls": 2, "case_image_calls": 1, "case_cost_micro_usd": 11, "remaining_calls": 2, "remaining_image_calls": 1, "remaining_cases": 1, "remaining_micro_usd": 10}, False),
    ({"case_calls": 2, "case_image_calls": 1, "case_cost_micro_usd": 10, "remaining_calls": 2, "remaining_image_calls": 1, "remaining_cases": 0, "remaining_micro_usd": 10}, False),
])
def test_full_case_envelope_admission(kwargs, expected):
    assert case_fits_remaining(**kwargs) is expected


@pytest.mark.parametrize("name,value", [("LIVE_TEST_MAX_CALLS", "0"), ("LIVE_TEST_MAX_IMAGE_CALLS", "1.0"), ("LIVE_TEST_MAX_CASES", "-2")])
def test_environment_count_limits_are_strict_positive_integers(name, value):
    with pytest.raises(AcceptanceError):
        build_run_budget({"max_usd": "1"}, {name: value}, planned_calls=2, planned_images=1, planned_cases=1)


def test_case_validation_and_closed_schema():
    assert validate_case(raw_case()).case_id == "english_icebreaker"
    for mutate in (
        lambda c: c.update(schema_version=2),
        lambda c: c.pop("description"),
        lambda c: c.update(extra=True),
        lambda c: c.update(source_kind="other"),
        lambda c: c.update(expectations={"carousel": {"unexpected": 2}}),
        lambda c: c.update(live_budget={"calls_by_stage": {"intake": 1}, "image_calls": -1}),
    ):
        value = raw_case(); mutate(value)
        with pytest.raises(AcceptanceError):
            validate_case(value)


def test_duplicate_case_ids_rejected(tmp_path):
    data = raw_case()
    (tmp_path / "a.json").write_text(json.dumps(data))
    (tmp_path / "b.json").write_text(json.dumps(data))
    with pytest.raises(AcceptanceError, match="duplicate"):
        discover_cases(tmp_path)


def test_profiles_filter_by_metadata_and_unknown_profile_cli_rejected():
    cases = discover_cases(FIXTURES)
    assert [c.case_id for c in cases if "smoke" in c.profiles] == ["english_icebreaker"]
    with pytest.raises(SystemExit):
        matrix.main(["--profile", "unknown", "--dry-run"])


def test_repeat_expands_attempts_without_losing_parent_id():
    case = validate_case(raw_case())
    attempts = [StageCase(case, n, case.case_id) for n in range(1, 4)]
    assert [(a.attempt, a.parent_case_id) for a in attempts] == [(1, case.case_id), (2, case.case_id), (3, case.case_id)]
    for invalid in ["0", "-1", "1.5", "NaN", "01"]:
        with pytest.raises(ValueError):
            matrix._parse_repeat(invalid)


def test_result_model_round_trip_statuses_categories_and_order(tmp_path):
    case = validate_case(raw_case())
    findings = tuple(Finding(case.case_id, "intake", status, category, f"{category.value}_{status.value}", "finding")
        for status in Status for category in Category)
    execution = StageExecution(Status.PASS, "intake", "fake", output={"ok": True})
    value = result_dict(StageCase(case, 1, case.case_id), execution, StageEvaluation(Status.PASS, findings))
    target = tmp_path / "result.json"; write_json(target, value)
    loaded = json.loads(target.read_text())
    assert [f["status"] for f in loaded["findings"]] == [s.value for s in Status for _ in Category]
    assert {f["category"] for f in loaded["findings"]} == {c.value for c in Category}


def test_hard_invariant_evaluator_reports_stage_failure():
    case = validate_case(raw_case())
    value = evaluate_hard_invariants(StageCase(case, 1, case.case_id),
        StageExecution(Status.ERROR, "intake", None, error="safe failure"))
    assert value.status == Status.ERROR
    assert value.findings[0].category == Category.PROVIDER


def test_stage_registry_routes_supported_stage_and_reports_unregistered_stage():
    case = validate_case(raw_case())
    registry = StageRegistry({"intake": lambda stage_case, db, auth, policy:
        StageExecution(Status.PASS, "intake", "fake", output={"ok": True})})
    supported = registry.execute(StageCase(case, 1, case.case_id), Path("unused.db"), None, None)
    assert supported.status == Status.PASS
    other = validate_case(json.loads((FIXTURES / "detection_frozen_minimal.json").read_text()))
    unsupported = registry.execute(StageCase(other, 1, other.case_id), Path("unused.db"), None, None)
    assert unsupported.status == Status.ERROR and "No live stage adapter" in unsupported.error


def test_run_workspace_and_schema_are_isolated(tmp_path):
    workspace = RunWorkspace.create(tmp_path / "acceptance")
    case_workspace = workspace.case_attempt("english_icebreaker", 1)
    assert case_workspace.is_relative_to(workspace.case_root)
    database = case_workspace / "workflow.db"
    initialize_acceptance_database(database)
    assert database.exists()
    import sqlite3
    with sqlite3.connect(database) as connection:
        assert connection.execute("PRAGMA user_version").fetchone()[0] == 14
    assert not (tmp_path / "development.db").exists()


def test_normal_pytest_dry_run_cannot_make_real_provider_invocation_even_with_credentials_configured(tmp_path, monkeypatch):
    monkeypatch.setattr(matrix, "_policies", lambda env, need_images: (text_policy(), None))
    from common import gemini
    calls = []
    monkeypatch.setattr(gemini, "VertexGeminiClient", lambda *args, **kwargs: calls.append((args, kwargs)))
    output, info = matrix.run_matrix(profile="smoke", dry_run=True, cli_live=False, repeat=2,
        limits={"max_usd": "0.20", "max_calls": None, "max_image_calls": None, "max_cases": None},
        environment={"GOOGLE_CLOUD_PROJECT": "configured", "GEMINI_MODEL": "configured", "GOOGLE_APPLICATION_CREDENTIALS": "/fake"},
        case_directory=FIXTURES, output_root=tmp_path / "acceptance")
    assert calls == []
    assert info["actual_calls"] == 0
    assert info["result_counts"]["SKIP"] == 2
    assert (output / "run.json").exists() and (output / "summary.md").exists() and (output / "costs.json").exists()
    assert Decimal(info["estimated_cost_usd"]) == 0
    assert Decimal(info["planned_max_cost_usd"]) > 0
    costs = json.loads((output / "costs.json").read_text())
    assert costs["total_estimated_cost_usd"] == "0"
    assert costs["cases"][0]["planned_max_calls"] == 1
    assert costs["cases"][0]["text_calls"] == 0
    assert "Planned maximum spend" in (output / "summary.md").read_text()


def test_case_that_does_not_fit_is_skipped_before_execution(tmp_path, monkeypatch):
    monkeypatch.setattr(matrix, "_policies", lambda env, need_images: (text_policy(), None))
    calls = []
    def fake_execute(*args):
        calls.append(args)
        return StageExecution(Status.PASS, "intake", "fake", output={"ok": True}, calls=1,
                              estimated_cost_micro_usd=1000)
    monkeypatch.setattr(matrix, "_intake_executor", fake_execute)
    output, info = matrix.run_matrix(profile="smoke", dry_run=False, cli_live=True, repeat=1,
        limits={"max_usd": "0.000000001", "max_calls": None, "max_image_calls": None, "max_cases": None},
        environment={"CONTENT_FACTORY_ENABLE_LIVE_GEMINI_TESTS": "1"}, case_directory=FIXTURES,
        output_root=tmp_path / "acceptance")
    result = json.loads((output / "cases/english_icebreaker/attempt-01/evaluation.json").read_text())
    assert result["status"] == Status.SKIP_BUDGET.value
    assert calls == [] and info["actual_calls"] == 0


def test_repeat_expansion_respects_case_limit_before_attempt_execution(tmp_path, monkeypatch):
    monkeypatch.setattr(matrix, "_policies", lambda env, need_images: (text_policy(), None))
    calls = []
    def fake_execute(*args):
        calls.append(args)
        return StageExecution(Status.PASS, "intake", "fake", output={"ok": True}, calls=1,
                              estimated_cost_micro_usd=1000)
    monkeypatch.setattr(matrix, "_intake_executor", fake_execute)
    output, info = matrix.run_matrix(profile="smoke", dry_run=False, cli_live=True, repeat=2,
        limits={"max_usd": "0.2", "max_calls": None, "max_image_calls": None, "max_cases": 1},
        environment={"CONTENT_FACTORY_ENABLE_LIVE_GEMINI_TESTS": "1"}, case_directory=FIXTURES,
        output_root=tmp_path / "acceptance")
    attempts = [json.loads(path.read_text()) for path in sorted(output.glob("cases/**/evaluation.json"))]
    assert [item["status"] for item in attempts] == [Status.PASS.value, Status.SKIP_BUDGET.value]
    assert len(calls) == 1


def test_live_environment_or_cli_alone_cannot_reach_provider(tmp_path, monkeypatch):
    monkeypatch.setattr(matrix, "_policies", lambda env, need_images: (text_policy(), None))
    calls = []
    monkeypatch.setattr(matrix, "_intake_executor", lambda *args: calls.append(args))
    common = dict(profile="smoke", dry_run=False, repeat=1,
        limits={"max_usd": "0.2", "max_calls": None, "max_image_calls": None, "max_cases": None},
        case_directory=FIXTURES, output_root=tmp_path / "acceptance")
    for enabled, cli in [({}, True), ({"CONTENT_FACTORY_ENABLE_LIVE_GEMINI_TESTS": "1"}, False)]:
        with pytest.raises(AcceptanceError):
            matrix.run_matrix(**common, cli_live=cli, environment=enabled)
    assert calls == []
