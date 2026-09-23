"""Delivery fixtures; offline tests use temporary databases and fake providers."""

from __future__ import annotations
from PIL import Image
from database.current import initialize_database
from datetime import timedelta
from detection.configuration import load_manifest
from detection.store import DetectionStore
from hashlib import sha256
from pathlib import Path
from workflow import WORKFLOW_PIPELINES
from workflow.active_visual_profiles import EXPRESSION_ROLES, active_recipe
from workflow.store import canonical, digest
import tempfile


ROOT = Path(__file__).resolve().parents[1]


MANIFEST = ROOT / "config" / "releases" / "detection.json"


class DeliveryFixture:
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.path = Path(self.temporary.name) / "development.db"
        initialize_database(self.path)
        with DetectionStore(self.path) as store:
            store.apply_manifest(load_manifest(MANIFEST))

    def configuration(self, *, platforms=("instagram",), max_posts_per_day=1,
                      min_post_interval_minutes=1200):
        destinations = []
        for platform in platforms:
            config = {"adapter_version": "unimplemented"}
            provider = "123456"
            secret_ref = "DELIVERY_TOKEN"
            destinations.append({
                "destination_key": f"{platform}:brand", "platform": platform,
                "account_key": "brand", "provider_account_id": provider,
                "secret_ref": secret_ref, "enabled": True, "config": config,
                "posting_policy": {"timezone": "Asia/Seoul",
                                   "max_posts_per_day": max_posts_per_day,
                                   "min_post_interval_minutes": min_post_interval_minutes,
                                   "authorization_ttl_hours": 48},
            })
        bindings = [{
            "pipeline_id": pipeline, "destination_key": item["destination_key"],
            "content_format": "instagram_static_carousel_v2",
        } for pipeline in WORKFLOW_PIPELINES for item in destinations]
        return {
            "policy_version": "production_configuration_v2", "approved_by": "test",
            "approved_at": "2026-09-13T00:00:00", "visual_configuration_approved": True,
            "destinations": destinations, "bindings": bindings,
        }

    def configure(self, store, *, platforms=("instagram",), max_posts_per_day=1,
                  min_post_interval_minutes=1200):
        store.register_production_configuration(self.configuration(
            platforms=platforms, max_posts_per_day=max_posts_per_day,
            min_post_interval_minutes=min_post_interval_minutes,
        ))
        for row in store.connection.execute("SELECT social_destination_id FROM social_destinations"):
            store.record_destination_readiness(
                row[0], status="ready", reasons=[], facts={"fixture": True},
                valid_for=timedelta(days=1),
            )

    def create_review(self, store, platform="instagram", *, stop_at_adaptation=False):
        sequence = int(store.connection.execute(
            "SELECT COUNT(*)+1 FROM content_threads"
        ).fetchone()[0])
        binding = store.connection.execute(
            "SELECT b.*,c.pipeline_id FROM output_bindings b JOIN pipeline_capabilities c "
            "ON c.pipeline_capability_id=b.pipeline_capability_id "
            "WHERE c.pipeline_id='english' AND b.platform=?", (platform,),
        ).fetchone()
        moment = "2026-09-13T00:00:00"
        thread_id = store.connection.execute(
            "INSERT INTO content_threads(origin,status,coverage_identity,created_at,updated_at) "
            "VALUES ('human','open',?,?,?)", (f"coverage:test:{platform}:{sequence}", moment, moment),
        ).lastrowid
        intake_id = store.connection.execute(
            "INSERT INTO intake_requests(thread_id,context_json,context_version,status,attempt_limit,"
            "created_at,completed_at) VALUES (?,'{}','fixture','completed',1,?,?)",
            (thread_id, moment, moment),
        ).lastrowid
        revision_id = store.connection.execute(
            "INSERT INTO brief_revisions(thread_id,revision_number,brief_json,source_snapshot_json,"
            "revision_reason,created_by,source_intake_request_id,created_at) "
            "VALUES (?,1,'{}','{}','initial','system',?,?)",
            (thread_id, intake_id, moment),
        ).lastrowid
        determination_request_id = store.connection.execute(
            "INSERT INTO determination_requests(revision_id,input_snapshot_json,input_fingerprint,status,"
            "attempt_limit,created_at,completed_at) VALUES (?,'{}',?,'completed',1,?,?)",
            (revision_id, "1" * 64, moment, moment),
        ).lastrowid
        decision_id = store.connection.execute(
            "INSERT INTO determination_decisions(determination_request_id,outcome,opportunity_value,"
            "rationale,warnings_json,coverage_identity,catalog_fingerprint,readiness_fingerprint,"
            "routing_policy_version,created_at) VALUES (?,'accepted','fixture','fixture','[]',?,?,?,?,?)",
            (determination_request_id, f"coverage:test:{platform}:{sequence}", "2" * 64, "3" * 64,
             "fixture", moment),
        ).lastrowid
        route_id = store.connection.execute(
            "INSERT INTO determination_routes(determination_decision_id,pipeline_id,disposition,fit,"
            "reason,evidence_json,output_assessments_json,created_at) "
            "VALUES (?,'english','selected','fixture','fixture','[]','[]',?)",
            (decision_id, moment),
        ).lastrowid
        editorial_run = store.connection.execute(
            "INSERT INTO editorial_plan_runs(determination_route_id,revision_id,pipeline_id,input_snapshot_json,input_fingerprint,status,attempt_limit,created_at) VALUES (?,?,'english','{}',?,'claimed',1,?)",
            (route_id, revision_id, '4'*64, moment),
        ).lastrowid
        editorial_id = store.connection.execute(
            "INSERT INTO editorial_plans(editorial_plan_run_id,determination_route_id,brief_revision_id,pipeline_id,lane,schema_version,planner_version,input_fingerprint,plan_json,created_at) VALUES (?,?,?,'english','evergreen','editorial_plan_v1','fixture',?,'{}',?)",
            (editorial_run,route_id,revision_id,'4'*64,moment),
        ).lastrowid
        job_id = store.connection.execute(
            "INSERT INTO content_jobs(editorial_plan_id,determination_route_id,brief_revision_id,pipeline_id,content_identity,"
            "recipe_json,output_plan_json,priority,created_at) VALUES (?,?,?,'english',?,'{}','[]',50,?)",
            (editorial_id, route_id, revision_id, digest({"job": platform, "sequence": sequence}), moment),
        ).lastrowid
        generation_id = store.connection.execute(
            "INSERT INTO generation_runs(content_job_id,run_number,status,attempt_limit,created_at,completed_at) "
            "VALUES (?,1,'succeeded',1,?,?)", (job_id, moment, moment),
        ).lastrowid
        canonical_value = {"hook": "A useful lesson", "claims": []}
        canonical_id = store.connection.execute(
            "INSERT INTO canonical_contents(content_job_id,generation_run_id,canonical_identity,"
            "canonical_json,canonical_hash,schema_version,created_at) VALUES (?,?,?,?,?,'fixture',?)",
            (job_id, generation_id, digest({"canonical": platform, "sequence": sequence}), canonical(canonical_value),
             digest(canonical_value), moment),
        ).lastrowid
        output_id = store.connection.execute(
            "INSERT INTO output_requests(canonical_content_id,output_binding_id,platform,account,"
            "content_format,output_identity,output_contract_version,input_json,created_at) "
            "VALUES (?,?,?,?,?,?,?,'{}',?)",
            (canonical_id, binding["output_binding_id"], platform, binding["account"],
             binding["content_format"], digest({"output": platform, "sequence": sequence}),
             binding["output_contract_version"], moment),
        ).lastrowid
        plan_id = store.connection.execute(
            "INSERT INTO visual_plan_runs(output_request_id,run_number,status,attempt_limit,created_at,completed_at) VALUES (?,1,'succeeded',1,?,?)",
            (output_id, moment, moment),
        ).lastrowid
        recipe = active_recipe("english", list(EXPRESSION_ROLES), account=binding["account"])
        provenance = {"strategy": "fixture_active_profile"}
        recipe_id = store.connection.execute(
            "INSERT INTO visual_recipes(output_request_id,visual_plan_run_id,recipe_json,recipe_hash,selection_provenance_json,created_at) VALUES (?,?,?,?,?,?)",
            (output_id, plan_id, canonical(recipe), digest(recipe), canonical(provenance), moment),
        ).lastrowid
        adaptation_id = store.connection.execute(
            "INSERT INTO adaptation_runs(output_request_id,visual_recipe_id,run_number,status,attempt_limit,created_at,"
            "completed_at) VALUES (?,?,1,?,1,?,?)",
            (output_id, recipe_id, "pending" if stop_at_adaptation else "succeeded", moment,
             None if stop_at_adaptation else moment),
        ).lastrowid
        if stop_at_adaptation:
            store.connection.commit()
            return adaptation_id
        count = 6
        profile = "gemini_instagram_review_v1"
        width, height = (1080, 1350)
        units = [{"role": role, "title": "Title", "body": "Body", "claim_ids": []}
                 for role in EXPRESSION_ROLES]
        cues = []
        package = {"schema_version": "output_adaptation_v3", "platform": platform,
                   "account": binding["account"], "format": binding["content_format"],
                   "public_text": "Approved immutable copy", "private_tags": ["one", "two"],
                   "hashtags": [], "alt_text": "Accessible description", "claim_mappings": [],
                   "visual_units": units, "visual_cues": cues, "archetype_id": recipe["archetype_id"], "delivery_ready": True}
        package["caption"] = "Approved immutable copy"
        if platform == "instagram":
            package["cta"] = None
        package_id = store.connection.execute(
            "INSERT INTO content_packages(output_request_id,adaptation_run_id,visual_recipe_id,package_json,content_hash,"
            "visual_cues_json,created_at) VALUES (?,?,?,?,?,?,?)",
            (output_id, adaptation_id, recipe_id, canonical(package), digest(package), canonical(cues), moment),
        ).lastrowid
        from workflow.storyboard_planner import make_plan
        plan = make_plan(6, 'english')
        storyboard_run = store.connection.execute("INSERT INTO storyboard_plan_runs(content_package_id,status,attempt_limit,created_at) VALUES (?,'succeeded',1,?)", (package_id, moment)).lastrowid
        storyboard_id = store.connection.execute("INSERT INTO storyboard_plans(storyboard_plan_run_id,content_package_id,output_request_id,visual_recipe_id,schema_version,planner_version,total_slides,boards_json,created_at) VALUES (?,?,?,?,?,?,6,?,?)", (storyboard_run, package_id, output_id, recipe_id, plan['schema_version'], plan['planner_version'], canonical(plan['boards']), moment)).lastrowid
        render_id = store.connection.execute(
            "INSERT INTO render_runs(storyboard_plan_id,content_package_id,visual_recipe_id,run_number,status,attempt_limit,created_at) "
            "VALUES (?,?,?,1,'claimed',1,?)", (storyboard_id, package_id, recipe_id, moment),
        ).lastrowid
        store.connection.execute(
            "UPDATE render_runs SET claim_owner='test-render',claimed_at=?,lease_expires_at=?,"
            "claim_version=1,attempt_count=1 WHERE render_run_id=?",
            (moment, "2099-01-01T00:00:00", render_id),
        )
        assets = []
        directory = Path(self.temporary.name) / f"assets-{platform}-{sequence}"
        directory.mkdir()
        for ordinal in range(1, count + 1):
            path = directory / f"{ordinal}.jpg"
            Image.new("RGB", (width, height), (245, 241, 232)).save(
                path, format="JPEG", quality=92, optimize=False, progressive=False
            )
            data = path.read_bytes()
            assets.append({"role": "delivery_jpeg", "ordinal": ordinal, "path": str(path.resolve()),
                           "mime": "image/jpeg", "width": width, "height": height,
                           "bytes": len(data), "sha256": sha256(data).hexdigest()})
        manifest = {"schema_version": "render_manifest_v1", "renderer": "gemini_storyboard_designer_v1",
                    "profile_id": profile, "content_hash": digest(package),
                    "pillow_version": "fixture",
                    "review_only": False, "assets": assets}
        store.connection.commit()
        run = store.connection.execute("SELECT * FROM render_runs WHERE render_run_id=?", (render_id,)).fetchone()
        review_id = store.complete_render(run, manifest, assets)
        return review_id
