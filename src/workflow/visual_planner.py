"""Deterministic VisualPlanRun worker over the shared visual registry."""
from __future__ import annotations

from typing import Any
import json

from .store import WorkflowStore
from .workers import local_operation
from .visual_registry import (COMPOSITIONS, DOMAIN_AFFINITY, FAMILIES, PLATFORM_POLICY, PRESETS,
                              REGISTRY_RELEASE, THEMES, TYPOGRAPHY, brand_policy_for_account, validate_intent, registry_fingerprint)


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
        if row is None: raise ValueError("visual plan references a missing ContentPackage")
        package, intent = json.loads(row["package_json"]), validate_intent(json.loads(row["visual_intent_json"]))
        units = package.get("visual_units")
        if not isinstance(units, list): raise ValueError("package has no bounded visual units")
        forced = None
        if run["fallback_from_visual_recipe_id"] is not None:
            prior = self.store.connection.execute("SELECT recipe_json FROM visual_recipes WHERE visual_recipe_id=?", (run["fallback_from_visual_recipe_id"],)).fetchone()
            if prior is None: raise ValueError("fallback source recipe is missing")
            forced = COMPOSITIONS.get(json.loads(prior["recipe_json"])["composition_id"], {}).get("fallback")
            if not forced: raise ValueError("registered recipe has no fallback composition")
        recipe, provenance = choose_recipe(intent, platform=row["platform"], pipeline=row["pipeline_id"], account=row["account"], unit_count=len(units), production=self.production, history=self._history(row["platform"], row["account"]), force_composition=forced)
        if forced: recipe["source"] = "fallback"
        return self.store.create_visual_recipe(run, recipe, provenance)

    def _history(self, platform: str, account: str) -> list[dict[str, Any]]:
        rows = self.store.connection.execute(
            "SELECT vr.recipe_json FROM visual_recipes vr JOIN content_packages cp ON cp.content_package_id=vr.content_package_id "
            "JOIN output_requests o ON o.output_request_id=cp.output_request_id WHERE o.platform=? AND o.account=? "
            "ORDER BY vr.visual_recipe_id DESC LIMIT 12", (platform, account)).fetchall()
        return [json.loads(row[0]) for row in rows]


def choose_recipe(intent: dict[str, Any], *, platform: str, pipeline: str, account: str, unit_count: int, production: bool, history: list[dict[str, Any]], force_composition: str | None = None) -> tuple[dict[str, Any], dict[str, Any]]:
    policy = PLATFORM_POLICY.get(platform)
    brand_policy_id, brand_policy = brand_policy_for_account(account)
    if policy is None or not policy["minimum"] <= unit_count <= policy["maximum"]:
        raise ValueError("platform visual policy rejects this package shape")
    candidates: list[tuple[float, str, dict[str, Any], str | None]] = []
    required = {intent["primary_structure"], *intent["emphasis_targets"]}
    for composition_id, composition in COMPOSITIONS.items():
        if force_composition is not None and composition_id != force_composition:
            continue
        if platform not in composition["platforms"] or composition["family_id"] not in policy["families"] or intent["density"] not in composition["densities"]:
            continue
        lifecycle = composition["lifecycle"]
        if lifecycle == "deprecated" or (production and lifecycle != "curated"):
            continue
        if intent["image_need"] == "required":
            continue
        semantic = 40 if intent["primary_structure"] in composition["features"] else 12 if composition["family_id"] == "editorial_v1" else 0
        semantic += 4 * len(required & composition["features"])
        affinity = DOMAIN_AFFINITY.get(pipeline, {}).get(composition["family_id"], 0)
        diversity = -sum(4 for item in history if item.get("composition_id") == composition_id) - sum(2 for item in history if item.get("family_id") == composition["family_id"])
        score = semantic + affinity + (8 if lifecycle == "curated" else 4) + diversity
        preset_id = next((key for key, preset in PRESETS.items() if preset["composition_id"] == composition_id and preset["density"] == intent["density"] and (not production or preset["lifecycle"] == "curated")), None)
        candidates.append((score, composition_id, composition, preset_id))
    if not candidates:
        raise ValueError("no registered visual recipe is compatible with this package")
    score, composition_id, composition, preset_id = sorted(candidates, key=lambda item: (-item[0], item[1]))[0]
    if preset_id:
        selected = dict(PRESETS[preset_id]); source = "preset"
    else:
        selected = {"family_id": composition["family_id"], "composition_id": composition_id,
                    "theme_id": "minimal_white_v1", "typography_id": "friendly_sans_v1", "density": intent["density"],
                    "components": {"footer": "compact_brand_v1", "highlight": "accent_text_v1"}, "decorations": ["none_v1"], "image_treatment": "none_v1"}; source = "dynamic"
    # Tone maps only to registered IDs; it never exposes colors or fonts to adaptation.
    if intent["tone"] == "serious": selected["theme_id"] = "dark_neutral_v1"
    elif intent["tone"] == "minimal": selected["theme_id"] = "minimal_white_v1"
    if selected["theme_id"] not in brand_policy["themes"] or selected["typography_id"] not in brand_policy["typography"]:
        raise ValueError("brand policy rejects the selected registered visual capability")
    selected["decorations"] = [item for item in selected["decorations"] if item in brand_policy["decorations"]]
    recipe = {"schema_version": "visual_recipe_v1", "registry_release": REGISTRY_RELEASE,
              "registry_fingerprint": registry_fingerprint(), "source": source, "preset_id": preset_id,
              **{key: selected[key] for key in ("family_id", "composition_id", "theme_id", "typography_id", "density", "components", "decorations", "image_treatment")},
              "unit_layouts": [{"ordinal": ordinal, "variant": "default_v1"} for ordinal in range(1, unit_count + 1)]}
    provenance = {"strategy": "deterministic_visual_scoring_v1", "candidate_count": len(candidates), "selected_candidate_id": composition_id,
                  "score": {"semantic_fit": 40 if intent["primary_structure"] in composition["features"] else 12 if composition["family_id"] == "editorial_v1" else 0,
                            "domain_affinity": DOMAIN_AFFINITY.get(pipeline, {}).get(composition["family_id"], 0),
                            "quality": 8 if composition["lifecycle"] == "curated" else 4,
                            "diversity_adjustment": score - (40 if intent["primary_structure"] in composition["features"] else 12 if composition["family_id"] == "editorial_v1" else 0) - DOMAIN_AFFINITY.get(pipeline, {}).get(composition["family_id"], 0) - (8 if composition["lifecycle"] == "curated" else 4), "total": score},
                  "platform": platform, "account": account, "brand_policy_id": brand_policy_id}
    return recipe, provenance
