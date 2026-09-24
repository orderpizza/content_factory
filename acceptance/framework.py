"""Versioned case, opt-in, budget, execution, and artifact contracts."""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from decimal import Decimal, InvalidOperation
from enum import Enum
import json
import os
from pathlib import Path
import re
import secrets
from typing import Any, Mapping, Protocol

from common.timestamps import utc_now


class AcceptanceError(ValueError):
    pass


class Status(str, Enum):
    PASS = "PASS"
    WARN = "WARN"
    FAIL = "FAIL"
    ERROR = "ERROR"
    SKIP = "SKIP"
    SKIP_BUDGET = "SKIP_BUDGET"


class Category(str, Enum):
    CONTRACT = "contract"
    LINEAGE = "lineage"
    SEMANTIC = "semantic"
    EDITORIAL = "editorial"
    VISUAL = "visual"
    PROVIDER = "provider"
    BUDGET = "budget"


STAGES = frozenset({"intake", "determination", "editorial_planning", "generation", "visual_selection", "adaptation", "storyboard_planning", "image_rendering"})
TEXT_STAGES = ("intake", "determination", "editorial_planning", "generation", "adaptation")
CHAIN_STAGES = ("intake", "determination", "editorial_planning", "generation", "visual_selection", "adaptation", "storyboard_planning", "image_rendering")
PROFILES = frozenset({"smoke", "stage", "regression", "pass3", "pass3_boards", "pass3_closure", "pass3_journeys", "pass3_detection_journey", "pass3_psychology_journey", "psychology_hardening", "psychology_spotcheck", "full"})
SOURCE_KINDS = frozenset({"human", "detection_fixture", "stage_fixture", "render_fixture"})
_ID = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}$")
_CASE_KEYS_V1 = {"case_id", "schema_version", "description", "source_kind", "input", "expectations", "tags", "profiles", "live_budget", "stage"}
_CASE_KEYS_V2 = {"case_id", "schema_version", "description", "source_kind", "input", "expectations", "conservation", "tags", "profiles", "live_budget", "start_stage", "end_stage"}
_EXPECTATION_KEYS = {"determination", "canonical", "carousel"}
_MAX_BUDGET_MICRO_USD = 9_223_372_036_854_775_807


def _decimal(raw: Any, label: str, *, positive: bool = False) -> Decimal:
    if isinstance(raw, bool) or not isinstance(raw, (str, int, Decimal)):
        raise AcceptanceError(f"{label} must be a decimal number")
    try:
        value = Decimal(str(raw))
    except (InvalidOperation, ValueError):
        raise AcceptanceError(f"{label} must be a decimal number") from None
    if not value.is_finite() or value < 0 or (positive and value == 0):
        raise AcceptanceError(f"{label} must be finite and {'greater than zero' if positive else 'nonnegative'}")
    if value > Decimal(_MAX_BUDGET_MICRO_USD) / Decimal(1_000_000):
        raise AcceptanceError(f"{label} exceeds the supported micro-USD accounting range")
    return value


def _positive_int(value: Any, label: str) -> int:
    if type(value) is not int or value <= 0:
        raise AcceptanceError(f"{label} must be a positive integer")
    return value


@dataclass(frozen=True)
class Case:
    case_id: str
    schema_version: int
    description: str
    source_kind: str
    input: dict[str, Any]
    expectations: dict[str, Any]
    tags: tuple[str, ...]
    profiles: tuple[str, ...]
    live_budget: dict[str, int]
    stage: str
    start_stage: str | None = None
    end_stage: str | None = None
    conservation: tuple[dict[str, Any], ...] = ()


def validate_case(value: Any, *, path: str = "case") -> Case:
    if not isinstance(value, dict):
        raise AcceptanceError(f"{path} must be an object")
    version = value.get("schema_version") if isinstance(value, dict) else None
    keys = _CASE_KEYS_V1 if version == 1 else _CASE_KEYS_V2 if version == 2 else set()
    unknown = set(value) - keys
    missing = keys - set(value)
    if unknown or missing:
        raise AcceptanceError(f"{path} keys invalid (unknown={sorted(unknown)}, missing={sorted(missing)})")
    case_id = value["case_id"]
    if not isinstance(case_id, str) or not _ID.fullmatch(case_id):
        raise AcceptanceError(f"{path}.case_id is invalid")
    if version not in {1, 2} or type(version) is not int:
        raise AcceptanceError(f"{path} uses an unknown schema version")
    if not isinstance(value["description"], str) or not value["description"].strip():
        raise AcceptanceError(f"{path}.description is required")
    if not isinstance(value["source_kind"], str) or value["source_kind"] not in SOURCE_KINDS:
        raise AcceptanceError(f"{path}.source_kind is invalid")
    if version == 1:
        start_stage = end_stage = value["stage"]
    else:
        start_stage, end_stage = value["start_stage"], value["end_stage"]
    if (not isinstance(start_stage, str) or not isinstance(end_stage, str)
            or start_stage not in CHAIN_STAGES or end_stage not in CHAIN_STAGES
            or CHAIN_STAGES.index(start_stage) > CHAIN_STAGES.index(end_stage)):
        raise AcceptanceError(f"{path}.start_stage/end_stage is invalid")
    if value["source_kind"] == "human" and start_stage != "intake":
        raise AcceptanceError(f"{path}.human cases must start at intake")
    if value["source_kind"] == "detection_fixture" and start_stage != "determination":
        raise AcceptanceError(f"{path}.detection fixtures must start at determination")
    if value["source_kind"] == "stage_fixture" and start_stage not in {
            "editorial_planning", "generation", "adaptation"}:
        raise AcceptanceError(f"{path}.stage fixtures must start at a Gemini text stage after determination")
    if value["source_kind"] == "render_fixture" and start_stage != "storyboard_planning":
        raise AcceptanceError(f"{path}.render fixtures must start at storyboard planning")
    if not isinstance(value["input"], dict) or not value["input"]:
        raise AcceptanceError(f"{path}.input must be a nonempty object")
    input_keys = (
        {"idea"} if value["source_kind"] == "human" else
        {"fixture_id"} if value["source_kind"] in {"stage_fixture", "render_fixture"} else
        {"frozen_brief", "source_evidence"}
    )
    if set(value["input"]) != input_keys:
        raise AcceptanceError(f"{path}.input does not match source_kind")
    if value["source_kind"] == "human":
        idea = value["input"]["idea"]
        if not isinstance(idea, str) or not idea.strip() or len(idea) > 8000:
            raise AcceptanceError(f"{path}.input.idea must contain 1-8,000 characters")
    elif value["source_kind"] in {"stage_fixture", "render_fixture"}:
        fixture_id = value["input"]["fixture_id"]
        if not isinstance(fixture_id, str) or not _ID.fullmatch(fixture_id):
            raise AcceptanceError(f"{path}.input.fixture_id is invalid")
    elif any(not isinstance(value["input"][key], dict) for key in input_keys):
        raise AcceptanceError(f"{path}.input frozen detection fields must be objects")
    exp = value["expectations"]
    allowed = {
        "intake": {"statuses", "must_preserve"},
        "determination": {"required_selected", "forbidden_selected", "required_dispositions", "outcome"},
        "editorial": {"lanes", "min_candidates", "max_candidates"},
        "canonical": {"must_preserve", "forbidden_terms", "required_claim_kinds", "require_evidence_refs"},
        "adaptation": {"min_slides", "max_slides", "required_roles"},
        "carousel": {"min_slides", "max_slides"},
    }
    if not isinstance(exp, dict) or set(exp) - set(allowed):
        raise AcceptanceError(f"{path}.expectations has unknown keys")
    for section_name, section_value in exp.items():
        if not isinstance(section_value, dict) or set(section_value) - allowed[section_name]:
            raise AcceptanceError(f"{path}.expectations.{section_name} has invalid shape")
        if section_name in {"determination", "canonical", "intake"}:
            for key, items in section_value.items():
                if key == "outcome":
                    if not isinstance(items, str) or items not in {"accepted", "blocked", "not_recommended"}:
                        raise AcceptanceError(f"{path}.expectations.determination.outcome is invalid")
                elif key == "require_evidence_refs":
                    if type(items) is not bool:
                        raise AcceptanceError(f"{path}.expectations.canonical.require_evidence_refs is invalid")
                elif not isinstance(items, list) or any(not isinstance(item, str) or not item.strip() for item in items):
                    raise AcceptanceError(f"{path}.expectations.{section_name}.{key} must be a list of nonempty strings")
        elif section_name in {"carousel", "adaptation"}:
            for key, count in section_value.items():
                if key == "required_roles":
                    if not isinstance(count, list) or not count or any(not isinstance(role, str) or not role for role in count):
                        raise AcceptanceError(f"{path}.expectations.adaptation.required_roles is invalid")
                else:
                    _positive_int(count, f"{path}.expectations.carousel.{key}")
            if "min_slides" in section_value and "max_slides" in section_value and section_value["min_slides"] > section_value["max_slides"]:
                raise AcceptanceError(f"{path}.expectations.carousel bounds are reversed")
        else:
            for key, count in section_value.items():
                if key == "lanes":
                    if not isinstance(count, list) or not count or any(item not in {"trend", "evergreen", "series", "experiment"} for item in count):
                        raise AcceptanceError(f"{path}.expectations.editorial.lanes is invalid")
                else:
                    _positive_int(count, f"{path}.expectations.editorial.{key}")
    for key in ("tags", "profiles"):
        items = value[key]
        if not isinstance(items, list) or not items or any(not isinstance(x, str) or not _ID.fullmatch(x) for x in items) or len(set(items)) != len(items):
            raise AcceptanceError(f"{path}.{key} must be a nonempty unique string list")
    if set(value["profiles"]) - PROFILES:
        raise AcceptanceError(f"{path}.profiles contains an unknown profile")
    conservation_value = [] if version == 1 else value["conservation"]
    if not isinstance(conservation_value, list):
        raise AcceptanceError(f"{path}.conservation must be a list")
    conservation: list[dict[str, Any]] = []
    kinds = {"exact_identifier", "normalized_phrase", "required_concept_terms", "qualification", "scope", "epistemic_strength", "evidence_reference", "claim_lineage"}
    for index, item in enumerate(conservation_value):
        if not isinstance(item, dict) or set(item) != {"kind", "value"} or item["kind"] not in kinds:
            raise AcceptanceError(f"{path}.conservation[{index}] is invalid")
        if isinstance(item["value"], str):
            if not item["value"].strip():
                raise AcceptanceError(f"{path}.conservation[{index}].value is empty")
        elif item["kind"] == "required_concept_terms" and isinstance(item["value"], list) and all(isinstance(term, str) and term.strip() for term in item["value"]):
            pass
        else:
            raise AcceptanceError(f"{path}.conservation[{index}].value is invalid")
        conservation.append(dict(item))
    budget = value["live_budget"]
    if not isinstance(budget, dict) or set(budget) != {"calls_by_stage", "image_calls"}:
        raise AcceptanceError(f"{path}.live_budget has invalid shape")
    calls = budget["calls_by_stage"]
    if not isinstance(calls, dict) or not calls or set(calls) - STAGES or any(type(n) is not int or n < 0 for n in calls.values()):
        raise AcceptanceError(f"{path}.live_budget.calls_by_stage is invalid")
    if sum(calls.values()) < 1 or any(stage not in STAGES for stage in calls):
        raise AcceptanceError(f"{path}.live_budget must declare provider calls")
    image_calls = budget["image_calls"]
    if type(image_calls) is not int or image_calls < 0 or image_calls != calls.get("image_rendering", 0):
        raise AcceptanceError(f"{path}.live_budget.image_calls is invalid")
    required_live = [stage for stage in CHAIN_STAGES[CHAIN_STAGES.index(start_stage):CHAIN_STAGES.index(end_stage) + 1]
                     if stage in {*TEXT_STAGES, "image_rendering"}]
    if any((calls.get(stage, 0) != 1 if stage != "image_rendering" else calls.get(stage, 0) < 1)
           for stage in required_live):
        raise AcceptanceError(f"{path}.live_budget must declare every live chain stage: one text call per text stage and a positive image-board envelope")
    if any(stage not in required_live and count for stage, count in calls.items()):
        raise AcceptanceError(f"{path}.live_budget includes a stage outside the requested journey")
    return Case(case_id, version, value["description"], value["source_kind"], value["input"], exp,
                tuple(value["tags"]), tuple(value["profiles"]), budget, end_stage,
                start_stage, end_stage, tuple(conservation))


def discover_cases(directory: Path) -> list[Case]:
    cases: list[Case] = []
    for path in sorted(directory.glob("*.json")):
        try:
            parsed = json.loads(path.read_text())
            # A matrix file is only a container for individually closed cases;
            # each child is still validated by the versioned case schema.
            values = parsed["cases"] if isinstance(parsed, dict) and set(parsed) == {"cases"} else [parsed]
            if not isinstance(values, list) or not values:
                raise AcceptanceError(f"{path.name} matrix must contain a nonempty cases list")
            cases.extend(validate_case(item, path=f"{path.name}[{index}]") for index, item in enumerate(values, 1))
        except (json.JSONDecodeError, UnicodeDecodeError) as error:
            raise AcceptanceError(f"{path.name} is not valid JSON: {error}") from None
    ids = [case.case_id for case in cases]
    if len(ids) != len(set(ids)):
        raise AcceptanceError("duplicate case_id found")
    return cases


@dataclass(frozen=True)
class Finding:
    case_id: str
    stage: str
    status: Status
    category: Category
    code: str
    message: str
    details: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class StageCase:
    case: Case
    attempt: int
    parent_case_id: str


@dataclass(frozen=True)
class StageExecution:
    status: Status
    stage: str
    model_id: str | None
    output: dict[str, Any] = field(default_factory=dict)
    calls: int = 0
    image_calls: int = 0
    estimated_cost_micro_usd: int = 0
    error: str | None = None
    error_category: Category = Category.PROVIDER
    executed_stages: tuple[str, ...] = ()


@dataclass(frozen=True)
class StageEvaluation:
    status: Status
    findings: tuple[Finding, ...] = ()


class StageExecutor(Protocol):
    def __call__(self, case: StageCase, database: Path,
                 authorization: "LiveAuthorization", budget_policy: Any) -> StageExecution: ...


class StageRegistry:
    """Explicit stage-to-adapter routing seam for stage, chain, and journey runners."""
    def __init__(self, executors: Mapping[str, StageExecutor]):
        if set(executors) - STAGES:
            raise AcceptanceError("stage registry contains an unknown stage")
        self._executors = dict(executors)

    def execute(self, stage_case: StageCase, database: Path,
                authorization: "LiveAuthorization", budget_policy: Any) -> StageExecution:
        executor = self._executors.get(stage_case.case.stage)
        if executor is None:
            return StageExecution(Status.ERROR, stage_case.case.stage, None,
                                  error="No live stage adapter is registered for Pass 1.",
                                  error_category=Category.CONTRACT)
        return executor(stage_case, database, authorization, budget_policy)


@dataclass(frozen=True)
class LiveAuthorization:
    """Opaque in-process proof created only by the central double opt-in gate."""
    nonce: str
    _authority: object = field(repr=False, compare=False)


_LIVE_AUTHORITY = object()


def authorize_live(*, cli_live: bool, environment: Mapping[str, str] | None = None) -> LiveAuthorization:
    env = os.environ if environment is None else environment
    if env.get("CONTENT_FACTORY_ENABLE_LIVE_GEMINI_TESTS") != "1" or not cli_live:
        raise AcceptanceError("live execution requires CONTENT_FACTORY_ENABLE_LIVE_GEMINI_TESTS=1 and --live-gemini")
    return LiveAuthorization(secrets.token_urlsafe(24), _LIVE_AUTHORITY)


def require_live_authorization(authorization: LiveAuthorization | None) -> None:
    if not isinstance(authorization, LiveAuthorization) or authorization._authority is not _LIVE_AUTHORITY:
        raise AcceptanceError("live provider execution requires authorization from the central opt-in gate")


@dataclass(frozen=True)
class RunBudget:
    max_usd: Decimal
    max_calls: int
    max_image_calls: int
    max_cases: int


def _env_limit(name: str, raw: str | None) -> int | None:
    if raw is None or not raw.strip():
        return None
    if not re.fullmatch(r"[0-9]+", raw.strip()):
        raise AcceptanceError(f"{name} must be a positive integer")
    return _positive_int(int(raw), name)


def build_run_budget(args: Mapping[str, Any], environment: Mapping[str, str], *, planned_calls: int, planned_images: int, planned_cases: int) -> RunBudget:
    env_usd = environment.get("LIVE_TEST_MAX_USD")
    if env_usd is not None and not env_usd.strip():
        env_usd = None
    cli_usd = args.get("max_usd")
    if env_usd is None and cli_usd is None:
        raise AcceptanceError("live execution requires a finite LIVE_TEST_MAX_USD or --max-usd ceiling")
    candidates = [_decimal(v, "LIVE_TEST_MAX_USD" if v == env_usd else "--max-usd", positive=True) for v in (env_usd, cli_usd) if v is not None]
    max_usd = min(candidates)
    call_values = [planned_calls]
    image_values = [planned_images]
    case_values = [planned_cases]
    if environment.get("LIVE_TEST_MAX_CALLS") is not None and environment.get("LIVE_TEST_MAX_CALLS").strip():
        call_values.append(_env_limit("LIVE_TEST_MAX_CALLS", environment.get("LIVE_TEST_MAX_CALLS")))
    if environment.get("LIVE_TEST_MAX_IMAGE_CALLS") is not None and environment.get("LIVE_TEST_MAX_IMAGE_CALLS").strip():
        image_values.append(_env_limit("LIVE_TEST_MAX_IMAGE_CALLS", environment.get("LIVE_TEST_MAX_IMAGE_CALLS")))
    if environment.get("LIVE_TEST_MAX_CASES") is not None and environment.get("LIVE_TEST_MAX_CASES").strip():
        case_values.append(_env_limit("LIVE_TEST_MAX_CASES", environment.get("LIVE_TEST_MAX_CASES")))
    if args.get("max_calls") is not None:
        call_values.append(_positive_int(args["max_calls"], "--max-calls"))
    if args.get("max_image_calls") is not None:
        image_values.append(_positive_int(args["max_image_calls"], "--max-image-calls"))
    if args.get("max_cases") is not None:
        case_values.append(_positive_int(args["max_cases"], "--max-cases"))
    return RunBudget(max_usd, min(call_values), min(image_values), min(case_values))


def configured_worst_case(case: Case, text_policy: Any, image_policy: Any | None) -> tuple[int, int, int]:
    calls = images = cost = 0
    for stage, count in case.live_budget["calls_by_stage"].items():
        if not count: continue
        policy = image_policy if stage == "image_rendering" else text_policy
        if policy is None: raise AcceptanceError("image pricing is required for a case with image calls")
        phase = "image_rendering" if stage == "image_rendering" else stage
        _, _, worst = policy.worst_case(phase)
        calls += count; cost += count * worst
    images = case.live_budget["image_calls"]
    return calls, images, cost


def case_fits_remaining(*, case_calls: int, case_image_calls: int, case_cost_micro_usd: int,
                        remaining_calls: int, remaining_image_calls: int,
                        remaining_cases: int, remaining_micro_usd: int) -> bool:
    """Admit the complete case envelope atomically, before its first stage call."""
    values = (case_calls, case_image_calls, case_cost_micro_usd, remaining_calls,
              remaining_image_calls, remaining_cases, remaining_micro_usd)
    if any(type(value) is not int or value < 0 for value in values):
        raise AcceptanceError("case admission values must be nonnegative integers")
    return (remaining_cases >= 1 and case_calls <= remaining_calls
            and case_image_calls <= remaining_image_calls
            and case_cost_micro_usd <= remaining_micro_usd)


@dataclass
class RunWorkspace:
    root: Path
    run_id: str
    started_at: str
    case_root: Path

    @classmethod
    def create(cls, root: Path) -> "RunWorkspace":
        started = utc_now()
        run_id = started.replace(":", "").replace("-", "") + "-" + secrets.token_hex(4)
        path = root / run_id
        path.mkdir(parents=True, exist_ok=False)
        (path / "cases").mkdir()
        return cls(path, run_id, started, path / "cases")

    def case_attempt(self, case_id: str, attempt: int) -> Path:
        path = self.case_root / case_id / f"attempt-{attempt:02d}"
        path.mkdir(parents=True, exist_ok=False)
        return path


def initialize_acceptance_database(path: Path) -> None:
    """Initialize a fresh current schema and development catalog in this run only."""
    from database.current import initialize_database
    from detection.configuration import load_manifest
    from detection.store import DetectionStore
    from workflow.development import configure_development_catalog
    from workflow.store import WorkflowStore
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("xb"):
        pass
    initialize_database(path)
    root = Path(__file__).resolve().parents[1]
    manifest = load_manifest(root / "config" / "releases" / "detection.json")
    manifest["release_name"] = "acceptance-fixture"
    with DetectionStore(path) as store:
        store.apply_manifest(manifest)
    with WorkflowStore(path) as store:
        configure_development_catalog(store)


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n")


def evaluate_hard_invariants(stage_case: StageCase, execution: StageExecution) -> StageEvaluation:
    findings: list[Finding] = []
    if execution.status in {Status.ERROR, Status.FAIL}:
        findings.append(Finding(stage_case.parent_case_id, execution.stage, execution.status,
                                execution.error_category, "stage_execution_failed", execution.error or "stage failed"))
    elif not execution.output:
        findings.append(Finding(stage_case.parent_case_id, execution.stage, Status.WARN,
                                Category.CONTRACT, "no_stage_output", "No stage output was captured."))
    else:
        findings.append(Finding(stage_case.parent_case_id, execution.stage, Status.PASS,
                                Category.CONTRACT, "stage_output_present", "Stage produced inspectable output."))
    status = execution.status if findings and findings[0].status in {Status.ERROR, Status.FAIL} else (Status.WARN if any(f.status == Status.WARN for f in findings) else Status.PASS)
    return StageEvaluation(status, tuple(findings))


def result_dict(stage_case: StageCase, execution: StageExecution, evaluation: StageEvaluation) -> dict[str, Any]:
    return {"schema_version": 1, "case_id": stage_case.parent_case_id, "attempt": stage_case.attempt,
            "stage": execution.stage, "start_stage": stage_case.case.start_stage,
            "end_stage": stage_case.case.end_stage, "executed_stages": list(execution.executed_stages),
            "status": evaluation.status.value,
            "model_id": execution.model_id, "calls": execution.calls,
            "image_calls": execution.image_calls,
            "estimated_cost_usd": str(Decimal(execution.estimated_cost_micro_usd) / Decimal(1_000_000)),
            "output": execution.output,
            "findings": [{**asdict(f), "status": f.status.value, "category": f.category.value} for f in evaluation.findings]}
