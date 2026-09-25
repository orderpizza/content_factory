"""Atomic lifecycle shared by the active Gemini review renderers only."""
from __future__ import annotations

from hashlib import sha256
from pathlib import Path
from typing import Any
import json
import os
import shutil
import tempfile
import time

import PIL

from .active_visual_profiles import validate_recipe
from .store import WorkflowStore
from .workers import local_operation


def _render_spec(package: Any) -> dict[str, Any]:
    if not isinstance(package, dict) or package.get("platform") != "instagram" or package.get("delivery_ready") is not False:
        raise ValueError("package/platform renderer safety mode does not match")
    units = package.get("visual_units")
    if not isinstance(units, list) or not 4 <= len(units) <= 14:
        raise ValueError("active Gemini review requires 4–14 bounded visual units")
    for unit in units:
        if not isinstance(unit, dict) or set(unit) != {"role", "title", "body", "claim_ids"}:
            raise ValueError("visual unit has an invalid shape")
        if unit["role"] not in {"hook", "explanation", "example", "takeaway"}:
            raise ValueError("visual unit role is unsupported")
        if not all(isinstance(unit[field], str) and unit[field] for field in ("title", "body")):
            raise ValueError("visual unit text is missing")
        if not isinstance(unit["claim_ids"], list):
            raise ValueError("visual unit claim mapping is invalid")
    return {"profile_id": "gemini_instagram_review_v1", "width": 1080, "height": 1350, "units": units}


class ActiveReviewRenderer:
    """Promote complete Gemini review assets atomically; never use HTML or fallback."""
    engine = "gemini_storyboard_designer_v1"

    def __init__(self, store: WorkflowStore, artifact_root: str | Path, *, instance_id: str):
        self.store = store
        self.artifact_root = Path(artifact_root).resolve()
        self.instance_id = instance_id
        self.production = False

    def run_once(self) -> int | None:
        run = self.store.claim("render_runs", "render_run_id", self.instance_id, lease_seconds=1800)
        return None if run is None else self._process(run)

    @local_operation("render_runs", "render_run_id")
    def _process(self, run: Any) -> int | None:
        package_row = self.store.connection.execute(
            "SELECT cp.package_json,cp.content_hash,vr.recipe_json FROM content_packages cp "
            "JOIN visual_recipes vr ON vr.visual_recipe_id=cp.visual_recipe_id AND vr.visual_recipe_id=? WHERE cp.content_package_id=?",
            (run["visual_recipe_id"], run["content_package_id"]),
        ).fetchone()
        if package_row is None:
            raise ValueError("render run references a missing ContentPackage")
        package = json.loads(package_row["package_json"])
        spec = _render_spec(package)
        recipe = validate_recipe(json.loads(package_row["recipe_json"]), production=False)
        from .active_visual_profiles import ARCHETYPES, validate_archetype_units
        from .storyboard_planner import validate_plan
        validate_archetype_units(package['visual_units'], recipe['archetype_id'])
        if package.get('schema_version') == 'output_adaptation_v4':
            from .content_contract import resolve_content_contract, semantic_qa
            canonical_row = self.store.connection.execute(
                'SELECT c.canonical_json FROM content_packages p JOIN output_requests o USING(output_request_id) '
                'JOIN canonical_contents c USING(canonical_content_id) WHERE p.content_package_id=?',
                (run['content_package_id'],)).fetchone()
            canonical = json.loads(canonical_row[0])
            contract = resolve_content_contract(canonical, recipe['archetype_id'])
            public_ids = [m['claim_id'] for m in package['claim_mappings'] if 'public_text' in m['placements']]
            qa = semantic_qa(package['visual_units'], canonical, contract, package['public_text'], public_ids)
            if package.get('content_contract') != contract or package.get('semantic_qa') != qa:
                raise ValueError('pre-render semantic evidence mismatch')
        plan_row = self.store.connection.execute('SELECT * FROM storyboard_plans WHERE storyboard_plan_id=? AND content_package_id=?',
            (run['storyboard_plan_id'], run['content_package_id'])).fetchone()
        if plan_row is None:
            raise ValueError('render requires committed storyboard plan')
        spec['storyboard_plan'] = validate_plan(dict(schema_version=plan_row['schema_version'],
            planner_version=plan_row['planner_version'], total_slides=plan_row['total_slides'],
            boards=json.loads(plan_row['boards_json'])), package['visual_units'], ARCHETYPES[recipe['archetype_id']].domain)
        self.artifact_root.mkdir(parents=True, exist_ok=True)
        final_directory = self.artifact_root / f"render-{run['render_run_id']}"
        if final_directory.exists():
            quarantine_root = self.artifact_root / "quarantine"
            quarantine_root.mkdir(parents=True, exist_ok=True)
            quarantine = quarantine_root / f"render-{run['render_run_id']}-uncommitted-{time.time_ns()}"
            final_directory.rename(quarantine)
            self.store.record_artifact_quarantine(int(run["render_run_id"]), final_directory, quarantine,
                                                  "promoted directory existed without a succeeded render record")
        temporary = Path(tempfile.mkdtemp(prefix=f"render-{run['render_run_id']}-", suffix=".tmp", dir=self.artifact_root))
        try:
            assets, engine_metadata = self._render_assets(run, package, spec, recipe, temporary)
            for path in temporary.iterdir():
                if path.is_file():
                    with path.open("rb") as handle:
                        os.fsync(handle.fileno())
            _fsync_directory(temporary)
            temporary.rename(final_directory)
            _fsync_directory(self.artifact_root)
            for asset in assets:
                asset["path"] = str(final_directory / Path(asset["path"]).name)
            manifest = {
                "schema_version": "render_manifest_v2", "renderer": self.engine,
                "profile_id": spec["profile_id"],
                "visual_recipe_hash": sha256(package_row["recipe_json"].encode("utf-8")).hexdigest(),
                "visual_profile_fingerprint": recipe["profile_fingerprint"],
                "content_hash": package_row["content_hash"],
                "pillow_version": PIL.__version__, "review_only": True,
                "storyboard_plan_id": run["storyboard_plan_id"],
                "storyboard_plan": spec["storyboard_plan"],
                "assets": assets, **engine_metadata,
            }
            return self.store.complete_render(run, manifest, assets)
        except Exception:
            if temporary.exists():
                shutil.rmtree(temporary)
            raise

    def _render_assets(self, run, package, spec, recipe, temporary):
        raise NotImplementedError


def _asset(path: Path, role: str, ordinal: int, width: int, height: int) -> dict[str, Any]:
    data = path.read_bytes()
    mime = {"preview_png": "image/png"}[role]
    return {"role": role, "ordinal": ordinal, "path": str(path), "mime": mime,
            "width": width, "height": height, "bytes": len(data), "sha256": sha256(data).hexdigest()}


def _fsync_directory(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
