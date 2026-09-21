"""Deterministic archetype-first VisualPlanRun worker."""
from __future__ import annotations

from typing import Any, Mapping
import json

from .store import WorkflowStore
from .workers import local_operation
from .visual_registry import (ARCHETYPES, DOMAIN_AFFINITY, PLATFORM_POLICY, PRESETS,
                              REGISTRY_RELEASE, brand_policy_for_account,
                              is_production_eligible, registry_fingerprint,
                              validate_intent)
from .visual_expression import validate_expression_units


class VisualPlanner:
    def __init__(self, store: WorkflowStore, *, instance_id: str = "visual-planner-deterministic", production: bool = False):
        self.store, self.instance_id, self.production = store, instance_id, production

    def run_once(self) -> int | None:
        run = self.store.claim("visual_plan_runs", "visual_plan_run_id", self.instance_id, lease_seconds=600)
        return None if run is None else self._process(run)

    @local_operation("visual_plan_runs", "visual_plan_run_id")
    def _process(self, run: Any) -> int | None:
        row = self.store.connection.execute(
            "SELECT cp.content_package_id,cp.package_json,cp.visual_intent_json,o.platform,o.account,"
            "j.pipeline_id FROM content_packages cp JOIN output_requests o ON o.output_request_id=cp.output_request_id "
            "JOIN canonical_contents c ON c.canonical_content_id=o.canonical_content_id "
            "JOIN content_jobs j ON j.content_job_id=c.content_job_id WHERE cp.content_package_id=?",
            (run["content_package_id"],),
        ).fetchone()
        if row is None:
            raise ValueError("visual plan references a missing ContentPackage")
        package, intent = json.loads(row["package_json"]), validate_intent(json.loads(row["visual_intent_json"]))
        units = package.get("visual_units")
        if not isinstance(units, list):
            raise ValueError("package has no bounded visual units")
        forced = None
        if run["fallback_from_visual_recipe_id"] is not None:
            prior = self.store.connection.execute("SELECT recipe_json FROM visual_recipes WHERE visual_recipe_id=?", (run["fallback_from_visual_recipe_id"],)).fetchone()
            if prior is None:
                raise ValueError("fallback source recipe is missing")
            prior_recipe = json.loads(prior["recipe_json"])
            forced = ARCHETYPES.get(prior_recipe.get("archetype_id"), {}).get("fallback_archetype_id")
            if not forced:
                raise ValueError("registered recipe has no fallback archetype")
        recipe, provenance = choose_recipe(intent, platform=row["platform"], pipeline=row["pipeline_id"], account=row["account"], unit_count=len(units), unit_roles=[unit["role"] for unit in units], production=self.production, history=self._history(row["platform"], row["account"]), force_archetype=forced, fallback=bool(forced))
        if recipe["archetype_id"] == "expression_breakdown_v1":
            validate_expression_units(units)
        return self.store.create_visual_recipe(run, recipe, provenance)

    def _history(self, platform: str, account: str) -> list[dict[str, Any]]:
        rows = self.store.connection.execute(
            "SELECT vr.recipe_json FROM visual_recipes vr JOIN content_packages cp ON cp.content_package_id=vr.content_package_id "
            "JOIN output_requests o ON o.output_request_id=cp.output_request_id WHERE o.platform=? AND o.account=? "
            "ORDER BY vr.visual_recipe_id DESC LIMIT 12", (platform, account)).fetchall()
        return [json.loads(row[0]) for row in rows]


def _resolve_safe_variant(archetype_id: str, intent: Mapping[str, Any]) -> dict[str, Any]:
    """Resolve one bounded variant; it never reaches outside this archetype."""
    archetype = ARCHETYPES[archetype_id]
    theme = archetype["default_theme_id"]
    if intent["tone"] == "serious" and "dark_neutral_v1" in archetype["theme_ids"]:
        theme = "dark_neutral_v1"
    elif intent["tone"] == "minimal" and "minimal_white_v1" in archetype["theme_ids"]:
        theme = "minimal_white_v1"
    elif intent["tone"] == "friendly" and "soft_blue_v1" in archetype["theme_ids"]:
        theme = "soft_blue_v1"
    density = intent["density"] if intent["density"] in archetype["density_ids"] else archetype["default_density"]
    components = dict(archetype["required_components"])
    if archetype["optional_components"] and intent["emphasis_targets"]:
        name = sorted(archetype["optional_components"])[0]
        components[name] = archetype["optional_components"][name][0]
    return {"archetype_id": archetype_id, "family_id": archetype["family_id"],
            "composition_id": archetype["default_composition_id"], "theme_id": theme,
            "typography_id": archetype["default_typography_id"], "density": density,
            "components": components, "decorations": list(archetype["default_decorations"]),
            "image_treatment": archetype["default_image_treatment"]}


def _semantic_score(archetype: Mapping[str, Any], intent: Mapping[str, Any]) -> int:
    primary = intent["primary_structure"]
    if primary in archetype["semantic_features"]:
        base = 40
    elif archetype["family_id"] == "editorial_v1":
        base = 12
    else:
        base = 0
    return base + 4 * len(set(intent["emphasis_targets"]) & archetype["semantic_features"])


def _diversity_adjustment(history: list[Mapping[str, Any]], selected: Mapping[str, Any]) -> int:
    # Bounded soft penalties preserve semantic fit over novelty.
    def penalty(key: str, value: Any, amount: int) -> int:
        return -min(amount * 3, amount * sum(item.get(key) == value for item in history))
    return (penalty("archetype_id", selected["archetype_id"], 3)
            + penalty("preset_id", selected.get("preset_id"), 2)
            + penalty("theme_id", selected["theme_id"], 1)
            + penalty("composition_id", selected["composition_id"], 1))


def _brand_compatible(selected: Mapping[str, Any], brand_policy: Mapping[str, Any]) -> bool:
    return (selected["theme_id"] in brand_policy["themes"]
            and selected["typography_id"] in brand_policy["typography"]
            and all(item in brand_policy["decorations"] for item in selected["decorations"])
            and selected["components"].get("footer", brand_policy["footer"]) == brand_policy["footer"])


def choose_recipe(intent: dict[str, Any], *, platform: str, pipeline: str, account: str, unit_count: int, production: bool, history: list[dict[str, Any]], unit_roles: list[str] | None = None, force_archetype: str | None = None, fallback: bool = False) -> tuple[dict[str, Any], dict[str, Any]]:
    """Select an archetype/preset first, then a deterministic safe resolution."""
    policy = PLATFORM_POLICY.get(platform)
    brand_policy_id, brand_policy = brand_policy_for_account(account)
    if policy is None or not policy["minimum"] <= unit_count <= policy["maximum"]:
        raise ValueError("platform visual policy rejects this package shape")
    if intent["image_need"] == "required":
        raise ValueError("no registered archetype supports required images")
    if unit_roles is None:
        unit_roles = ["hook"] + ["explanation"] * max(0, unit_count - 2) + (["takeaway"] if unit_count > 1 else [])
    if len(unit_roles) != unit_count:
        raise ValueError("visual unit roles do not match package shape")
    candidates: list[tuple[int, str, str, dict[str, Any], dict[str, int]]] = []
    for archetype_id, archetype in ARCHETYPES.items():
        if force_archetype is not None and archetype_id != force_archetype:
            continue
        if platform not in archetype["platforms"] or archetype["family_id"] not in policy["families"] or intent["density"] not in archetype["density_ids"]:
            continue
        if archetype.get("expected_roles") and unit_roles != archetype["expected_roles"]:
            continue
        if archetype["lifecycle"] in {"deprecated", "experimental"}:
            continue
        selected = _resolve_safe_variant(archetype_id, intent)
        if not _brand_compatible(selected, brand_policy):
            continue
        if production and not is_production_eligible(selected):
            continue
        semantic = _semantic_score(archetype, intent)
        affinity = DOMAIN_AFFINITY.get(pipeline, {}).get(archetype["family_id"], 0)
        # English is the pilot affinity. The archetype itself remains available to
        # every domain when its bounded six-slide grammar and semantics fit.
        if archetype_id == "expression_breakdown_v1" and pipeline == "english" and intent["primary_structure"] == "cards":
            affinity += 12
        quality = 8 if archetype["lifecycle"] == "curated" else 4
        diversity = _diversity_adjustment(history, selected)
        source = "curated_archetype" if archetype["lifecycle"] == "curated" else "experimental_dynamic"
        candidates.append((semantic + affinity + quality + diversity, archetype_id, source, selected, {"semantic_fit": semantic, "domain_affinity": affinity, "quality": quality, "diversity_adjustment": diversity}))
        # Presets are exact, curated resolutions of the same candidate archetype.
        for preset_id, preset in PRESETS.items():
            if preset["archetype_id"] != archetype_id or preset["density"] != intent["density"] or preset["lifecycle"] != "curated":
                continue
            preset_selected = dict(preset)
            if not _brand_compatible(preset_selected, brand_policy) or (production and not is_production_eligible(preset_selected)):
                continue
            preset_selected["preset_id"] = preset_id
            preset_diversity = _diversity_adjustment(history, preset_selected)
            candidates.append((semantic + affinity + quality + 2 + preset_diversity, f"{archetype_id}:{preset_id}", "curated_preset", preset_selected, {"semantic_fit": semantic, "domain_affinity": affinity, "quality": quality + 2, "diversity_adjustment": preset_diversity}))
    if not candidates:
        raise ValueError("no curated archetype is compatible with this package")
    score, candidate_id, source, selected, parts = sorted(candidates, key=lambda item: (-item[0], item[1]))[0]
    preset_id = selected.pop("preset_id", None)
    if fallback:
        source, preset_id = "fallback", None
    archetype = ARCHETYPES[selected["archetype_id"]]
    variants = archetype.get("expected_layouts") or [archetype["unit_layout_variants"][role][0] for role in unit_roles]
    unit_layouts = [{"ordinal": ordinal, "variant": variant} for ordinal, variant in enumerate(variants, start=1)]
    recipe = {"schema_version": "visual_recipe_v4", "registry_release": REGISTRY_RELEASE,
              "registry_fingerprint": registry_fingerprint(), "source": source, "archetype_id": selected["archetype_id"], "preset_id": preset_id,
              **{key: selected[key] for key in ("family_id", "composition_id", "theme_id", "typography_id", "density", "components", "decorations", "image_treatment")},
              "unit_layouts": unit_layouts}
    provenance = {"strategy": "deterministic_archetype_scoring_v2", "candidate_count": len(candidates), "selected_candidate_id": candidate_id, "selected_archetype_id": recipe["archetype_id"], "selected_preset_id": preset_id, "score": {**parts, "total": score}, "platform": platform, "account": account, "brand_policy_id": brand_policy_id}
    return recipe, provenance
