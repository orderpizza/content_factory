"""Evaluate closed contracts and only obvious conservation violations."""
from __future__ import annotations

import json
import re
from typing import Any

from acceptance.framework import Category, Finding, StageCase, StageEvaluation, Status


def _text(value: Any) -> str:
    if isinstance(value, dict): return " ".join(_text(v) for v in value.values())
    if isinstance(value, list): return " ".join(_text(v) for v in value)
    return value if isinstance(value, str) else ""


def _norm(value: str) -> str:
    return " ".join(re.findall(r"[\w'-]+", value.casefold()))


def _contains_unqualified_term(text: str, term: str) -> bool:
    """Return true only when a guard term is not visibly marked as unknown."""
    normalized_term = _norm(term)
    for match in re.finditer(re.escape(normalized_term), text):
        window = text[max(0, match.start() - 96):min(len(text), match.end() + 96)]
        if not re.search(r"\b(no|not|without|unknown|unstated|unspecified|omitted|missing|lacks?|lack)\b", window):
            return True
    return False


def _finding(case: StageCase, stage: str, status: Status, category: Category, code: str, message: str) -> Finding:
    return Finding(case.parent_case_id, stage, status, category, code, message)


def _conservation(case: StageCase, output: dict[str, Any]) -> list[Finding]:
    findings: list[Finding] = []
    adapted = output.get("adaptation", {}).get("package", output)
    text = _norm(_text(adapted))
    for item in case.case.conservation:
        kind, value = item["kind"], item["value"]
        terms = value if isinstance(value, list) else [value]
        present = [_norm(term) in text for term in terms]
        if kind in {"exact_identifier", "normalized_phrase", "required_concept_terms"} and not all(present):
            findings.append(_finding(case, case.case.end_stage or case.case.stage, Status.FAIL, Category.SEMANTIC, f"conservation_{kind}_missing", "Declared critical term is absent from the inspectable downstream artifact."))
        elif kind in {"qualification", "scope", "epistemic_strength", "evidence_reference", "claim_lineage"} and not all(present):
            findings.append(_finding(case, case.case.end_stage or case.case.stage, Status.WARN, Category.SEMANTIC, f"conservation_{kind}_review", "Declared qualification needs human review; lexical equivalence is not treated as semantic certainty."))
    return findings


def evaluate_pipeline(case: StageCase, execution: Any) -> StageEvaluation:
    if execution.status != Status.PASS:
        return StageEvaluation(execution.status, (_finding(case, execution.stage, execution.status, execution.error_category, "stage_execution_failed", execution.error or "stage failed"),))
    output, exp, findings = execution.output, case.case.expectations, []
    intake = output.get("intake")
    if "intake" in exp and intake:
        allowed_statuses = exp["intake"].get("statuses", [intake["status"]])
        if intake["status"] not in allowed_statuses:
            findings.append(_finding(case, "intake", Status.FAIL, Category.CONTRACT, "unexpected_intake_status", "Intake status differs from the declared case contract."))
        preserved = exp["intake"].get("must_preserve", [])
        if intake.get("brief"):
            brief_text = _norm(_text(intake["brief"]))
            for term in preserved:
                if _norm(term) not in brief_text:
                    findings.append(_finding(case, "intake", Status.WARN, Category.SEMANTIC, "intake_context_review", "Marked input context is not lexically visible in the frozen brief and needs human review."))
    determination = output.get("determination")
    if "determination" in exp and determination:
        routes = {item["pipeline_id"]: item["disposition"] for item in determination["routes"]}
        for domain in exp["determination"].get("required_selected", []):
            if routes.get(domain) != "selected": findings.append(_finding(case, "determination", Status.FAIL, Category.CONTRACT, "required_route_not_selected", f"{domain} was not selected."))
        for domain in exp["determination"].get("forbidden_selected", []):
            if routes.get(domain) == "selected": findings.append(_finding(case, "determination", Status.FAIL, Category.CONTRACT, "forbidden_route_selected", f"{domain} was selected."))
        outcome = exp["determination"].get("outcome")
        if outcome and determination["outcome"] != outcome: findings.append(_finding(case, "determination", Status.FAIL, Category.CONTRACT, "unexpected_outcome", "Determination outcome differs from the declared case contract."))
    plan = output.get("editorial_planning", {}).get("plan")
    if "editorial" in exp and plan:
        if plan["lane"] not in exp["editorial"].get("lanes", [plan["lane"]]): findings.append(_finding(case, "editorial_planning", Status.FAIL, Category.CONTRACT, "invalid_lane", "Selected lane is outside the case expectation."))
        n = len(plan["candidates"])
        if n < exp["editorial"].get("min_candidates", 2) or n > exp["editorial"].get("max_candidates", 4): findings.append(_finding(case, "editorial_planning", Status.FAIL, Category.CONTRACT, "candidate_count", "Editorial candidate count is outside bounds."))
    canonical = output.get("generation", {}).get("canonical")
    if "canonical" in exp and canonical:
        canonical_text = _norm(_text(canonical))
        for term in exp["canonical"].get("must_preserve", []):
            if _norm(term) not in canonical_text:
                findings.append(_finding(case, "generation", Status.FAIL, Category.SEMANTIC, "canonical_term_missing", "Declared canonical term is absent."))
        for term in exp["canonical"].get("forbidden_terms", []):
            if _contains_unqualified_term(canonical_text, term):
                findings.append(_finding(case, "generation", Status.FAIL, Category.SEMANTIC, "canonical_forbidden_term_present", "A term excluded by the frozen-evidence case is present in canonical content."))
        kinds = {claim.get("claim_kind") for claim in canonical.get("claims", [])}
        for kind in exp["canonical"].get("required_claim_kinds", []):
            if kind not in kinds:
                findings.append(_finding(case, "generation", Status.FAIL, Category.CONTRACT, "canonical_claim_kind_missing", "Declared claim kind is absent."))
        if exp["canonical"].get("require_evidence_refs") and any(not claim.get("evidence_reference_ids") for claim in canonical.get("claims", []) if claim.get("claim_kind") == "source_bound_fact"):
            findings.append(_finding(case, "generation", Status.FAIL, Category.LINEAGE, "source_bound_claim_without_evidence", "A source-bound canonical claim lacks frozen evidence lineage."))
    recipe = output.get("visual_selection", {}).get("recipe")
    if recipe and canonical:
        from workflow.active_visual_profiles import ARCHETYPES
        archetype = ARCHETYPES.get(recipe.get("archetype_id"))
        if archetype is None or archetype.domain != canonical.get("pipeline_id"):
            findings.append(_finding(case, "visual_selection", Status.FAIL, Category.VISUAL, "invalid_selected_archetype", "Selected visual archetype is not in the canonical domain catalog."))
    package = output.get("adaptation", {}).get("package")
    adaptation_exp = exp.get("adaptation", exp.get("carousel", {}))
    if adaptation_exp and package:
        count = len(package["visual_units"])
        if not adaptation_exp.get("min_slides", count) <= count <= adaptation_exp.get("max_slides", count): findings.append(_finding(case, "adaptation", Status.FAIL, Category.CONTRACT, "slide_bounds", "Adaptation slide count is outside declared bounds."))
        roles = [unit["role"] for unit in package["visual_units"]]
        expected_roles = adaptation_exp.get("required_roles")
        if expected_roles and roles != expected_roles:
            findings.append(_finding(case, "adaptation", Status.FAIL, Category.CONTRACT, "visual_roles", "Adaptation visual-unit roles differ from the declared contract."))
        canonical_ids = {claim["claim_id"] for claim in canonical.get("claims", [])} if canonical else set()
        mapped_ids = {mapping["claim_id"] for mapping in package.get("claim_mappings", [])}
        if canonical_ids and canonical_ids != mapped_ids:
            findings.append(_finding(case, "adaptation", Status.FAIL, Category.LINEAGE, "claim_lineage_incomplete", "Public package does not map every upstream canonical claim."))
    rendered = output.get("image_rendering")
    if rendered:
        manifest = rendered.get("manifest")
        review = rendered.get("review_request")
        if rendered.get("status") != "succeeded" or not manifest or not review:
            findings.append(_finding(case, "image_rendering", Status.FAIL, Category.CONTRACT, "review_render_incomplete", "Image rendering did not create a persisted complete ReviewRequest."))
        else:
            plan = manifest.get("storyboard_plan", {})
            boards = manifest.get("boards", [manifest.get("storyboard")])
            slides = manifest.get("slides", [])
            expected_ordinals = list(range(1, int(plan.get("total_slides", 0)) + 1))
            if [slide.get("ordinal") for slide in slides] != expected_ordinals:
                findings.append(_finding(case, "image_rendering", Status.FAIL, Category.LINEAGE, "global_slide_order", "Manifest final-slide ordinals do not match the StoryboardPlan."))
            if any((slide.get("final", {}).get("filename") is None or slide.get("source_rectangle") is None) for slide in slides):
                findings.append(_finding(case, "image_rendering", Status.FAIL, Category.LINEAGE, "slide_provenance_missing", "A final slide lacks a source rectangle or final artifact reference."))
            for board in boards:
                if not board or not board.get("raw", {}).get("sha256") or not board.get("prompt_sha256"):
                    findings.append(_finding(case, "image_rendering", Status.FAIL, Category.LINEAGE, "board_provenance_missing", "A board lacks raw-image or prompt provenance."))
                    break
                split = board.get("split", {})
                normalization = split.get("normalization", {})
                if normalization.get("final_width") != 1080 or normalization.get("final_height") != 1350:
                    findings.append(_finding(case, "image_rendering", Status.FAIL, Category.CONTRACT, "final_dimensions", "Rendered slides are not normalized to 1080×1350."))
                    break
            findings.append(_finding(case, "image_rendering", Status.WARN, Category.VISUAL, "human_visual_review_required", "Structural checks passed; inspect the generated boards and final slides in gallery.html for text fidelity and visual quality."))
    findings.extend(_conservation(case, output))
    findings.append(_finding(case, execution.stage, Status.PASS, Category.CONTRACT, "production_handoffs_completed", "Requested production handoffs completed with inspectable persisted artifacts."))
    status = Status.FAIL if any(f.status == Status.FAIL for f in findings) else Status.WARN if any(f.status == Status.WARN for f in findings) else Status.PASS
    return StageEvaluation(status, tuple(findings))
