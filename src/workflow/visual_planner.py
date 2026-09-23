"""Persist the one approved Gemini visual profile for each active domain."""
from __future__ import annotations

from typing import Any
import json

from .active_visual_profiles import active_recipe, validate_intent
from .visual_explainers import validate_domain_units
from .store import WorkflowStore
from .workers import local_operation


class VisualPlanner:
    """Create an immutable active-domain recipe; no generic selector or fallback exists."""

    def __init__(self, store: WorkflowStore, *, instance_id: str = "visual-planner-gemini-profile", production: bool = False):
        self.store, self.instance_id, self.production = store, instance_id, production

    def run_once(self) -> int | None:
        run = self.store.claim("visual_plan_runs", "visual_plan_run_id", self.instance_id, lease_seconds=600)
        return None if run is None else self._process(run)

    @local_operation("visual_plan_runs", "visual_plan_run_id")
    def _process(self, run: Any) -> int | None:
        row = self.store.connection.execute(
            "SELECT cp.content_package_id,cp.package_json,cp.visual_intent_json,j.pipeline_id "
            "FROM content_packages cp JOIN output_requests o ON o.output_request_id=cp.output_request_id "
            "JOIN canonical_contents c ON c.canonical_content_id=o.canonical_content_id "
            "JOIN content_jobs j ON j.content_job_id=c.content_job_id WHERE cp.content_package_id=?",
            (run["content_package_id"],),
        ).fetchone()
        if row is None:
            raise ValueError("visual plan references a missing ContentPackage")
        package = json.loads(row["package_json"])
        validate_intent(json.loads(row["visual_intent_json"]))
        units = package.get("visual_units")
        if not isinstance(units, list):
            raise ValueError("package has no bounded visual units")
        validate_domain_units(units, row["pipeline_id"], strict_english=True)
        if run["fallback_from_visual_recipe_id"] is not None:
            raise ValueError("active Gemini rendering has no visual fallback")
        recipe = active_recipe(row["pipeline_id"], [unit["role"] for unit in units])
        provenance = {
            "strategy": "explicit_domain_archetype_v1",
            "pipeline_id": row["pipeline_id"],
            "candidate_count": 1,
            "selected_archetype_id": recipe["archetype_id"],
            "selected_preset_id": None,
            "source": "gemini_domain_profile",
        }
        return self.store.create_visual_recipe(run, recipe, provenance)
