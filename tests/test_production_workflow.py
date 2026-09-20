"""Offline v4 production/delivery boundary tests; no provider calls."""

from __future__ import annotations

from copy import deepcopy
from argparse import ArgumentParser
from contextlib import redirect_stderr
from datetime import timedelta
from decimal import Decimal
from hashlib import sha256
from io import StringIO
from pathlib import Path
from unittest.mock import patch
from types import SimpleNamespace
import json
import runpy
import tempfile
import unittest

from PIL import Image

from database.current import (
    SchemaError,
    connect,
    initialize_database,
    initialize_database,
    validate_database,
)
from detection.configuration import load_manifest
from detection.store import DetectionStore
from workflow import (
    CredentialedPostingAgent,
    DeliveryError,
    GeminiAdaptationWorker,
    GeminiIntakeWorker,
    InstagramDeliveryAdapter,
    ModelBudgetPolicy,
    R2CleanupWorker,
    WORKFLOW_PIPELINES,
    WorkflowStore,
    XDeliveryAdapter,
)
from common.gemini import GeminiUsage
from workflow.store import canonical, digest, now
from workflow.maintenance import MaintenanceService, StorageMonitor
from workflow.readiness import CapabilityReadinessMonitor


ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "config" / "releases" / "detection.json"


class FakeGeminiClient:
    model = "fake-gemini"

    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []
        self.last_usage = GeminiUsage(10, 5, 15, self.model)

    def generate_json(self, prompt, schema, *, temperature):
        self.calls.append({"prompt": prompt, "schema": schema, "temperature": temperature})
        return deepcopy(self.responses.pop(0))


class FakeDeliveryAdapter:
    def __init__(self, *, fail_final: bool = False):
        self.fail_final = fail_final
        self.staged = []
        self.published = []

    def stage(self, context, record):
        self.staged.append(deepcopy(context))
        record(resource_type="x_media", remote_id="778899", asset_ordinal=1,
               status="ready", safe_metadata={})
        return {"media_id": "778899"}

    def publish(self, context, staged):
        self.published.append((deepcopy(context), deepcopy(staged)))
        if self.fail_final:
            raise DeliveryError("transport", "response was lost", True, "x_create_post")
        return "1122334455"


class RecordingTransport:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def request_json(self, method, url, **values):
        self.calls.append((method, url, deepcopy(values)))
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return deepcopy(response)


class FakeRelay:
    def __init__(self):
        self.staged = []
        self.deleted = []

    def stage(self, context, asset, *, key=None):
        key = key or f"instagram-transient/{context['post_record_id']}/{context['attempt_number']}/{asset['ordinal']}-fixture.jpg"
        self.staged.append((key, asset["sha256"]))
        public_url = "https://media.example.com/" + key
        return key, public_url

    def delete(self, key):
        self.deleted.append(key)


class FailingRelay(FakeRelay):
    def stage(self, context, asset, *, key=None):
        self.staged.append((key, asset["sha256"]))
        raise DeliveryError("r2", "head response was lost", True, "r2_head")


class ReadinessRelay:
    def probe(self):
        return {"put": True, "head": True, "public_get": True, "delete": True}


class ProductionWorkflowTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.path = Path(self.temporary.name) / "development.db"
        initialize_database(self.path)
        with DetectionStore(self.path) as store:
            store.apply_manifest(load_manifest(MANIFEST))
        initialize_database(self.path)

    def configuration(self, *, platforms=("instagram", "x"), max_posts_per_day=1,
                      min_post_interval_minutes=1200):
        destinations = []
        for platform in platforms:
            if platform == "instagram":
                config = {
                    "graph_api_version": "v24.0", "r2_account_id": "account",
                    "r2_bucket_name": "bucket", "r2_public_domain": "https://media.example.com",
                    "adapter_version": "meta_instagram_carousel_v1",
                }
                provider = "123456"
                secret_ref = "INSTAGRAM_ACCESS_TOKEN"
            else:
                config = {
                    "api_origin": "https://api.x.com", "media_upload_path": "/2/media/upload",
                    "create_post_path": "/2/tweets", "adapter_version": "x_static_post_delivery_v1",
                    "image_max_bytes": 5_000_000,
                }
                provider = "654321"
                secret_ref = "X_USER_ACCESS_TOKEN"
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
            "content_format": ("instagram_static_carousel_v2"
                               if item["platform"] == "instagram" else "x_static_post_v1"),
        } for pipeline in WORKFLOW_PIPELINES for item in destinations]
        return {
            "policy_version": "production_configuration_v1", "approved_by": "test",
            "approved_at": "2026-09-13T00:00:00+00:00", "profile_approved": True,
            "renderer_profile": {"profile_version": "static_social_delivery_profiles_v1",
                                 "template_version": "static_social_template_v1",
                                 "font_path": "/fixture/font.ttf", "font_sha256": "f" * 64},
            "destinations": destinations, "bindings": bindings,
        }

    def configure(self, store, *, platforms=("instagram", "x"), max_posts_per_day=1,
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

    def test_r2_dev_catalog_acceptance_preserves_https_origin_boundary(self):
        public_domain = runpy.run_path(str(ROOT / "scripts" / "configure_production.py"))["_public_domain"]
        with WorkflowStore(self.path, catalog_kind="production") as store:
            for invalid in (
                "http://pub-fixture.r2.dev", "https://user:password@pub-fixture.r2.dev",
                "https://pub-fixture.r2.dev/path", "https://pub-fixture.r2.dev?token=value",
                "https://pub-fixture.r2.dev#fragment",
            ):
                with self.subTest(origin=invalid):
                    with redirect_stderr(StringIO()), self.assertRaises(SystemExit):
                        public_domain(ArgumentParser(), invalid)
                    value = self.configuration(platforms=("instagram",))
                    value["destinations"][0]["config"]["r2_public_domain"] = invalid
                    with self.assertRaises(ValueError):
                        store.register_production_configuration(value)
                    self.assertEqual(store.connection.execute(
                        "SELECT COUNT(*) FROM production_configurations"
                    ).fetchone()[0], 0)
            origin = public_domain(ArgumentParser(), "https://pub-fixture.r2.dev/")
            self.assertEqual(origin, "https://pub-fixture.r2.dev")
            value = self.configuration(platforms=("instagram",))
            value["destinations"][0]["config"]["r2_public_domain"] = origin
            store.register_production_configuration(value)
            self.assertEqual(store.connection.execute(
                "SELECT COUNT(*) FROM social_destinations WHERE platform='x'"
            ).fetchone()[0], 0)
            readiness = store.connection.execute("SELECT status FROM capability_readiness").fetchone()[0]
            self.assertNotEqual(readiness, "ready")

    def create_review(self, store, platform="x", *, stop_at_adaptation=False):
        sequence = int(store.connection.execute(
            "SELECT COUNT(*)+1 FROM content_threads"
        ).fetchone()[0])
        binding = store.connection.execute(
            "SELECT b.*,c.pipeline_id FROM output_bindings b JOIN pipeline_capabilities c "
            "ON c.pipeline_capability_id=b.pipeline_capability_id "
            "WHERE c.pipeline_id='english' AND b.platform=?", (platform,),
        ).fetchone()
        moment = "2026-09-13T00:00:00+00:00"
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
            "reason,angle_json,evidence_json,output_assessments_json,created_at) "
            "VALUES (?,'english','selected','fixture','fixture','{}','[]','[]',?)",
            (decision_id, moment),
        ).lastrowid
        job_id = store.connection.execute(
            "INSERT INTO content_jobs(determination_route_id,brief_revision_id,pipeline_id,content_identity,"
            "recipe_json,output_plan_json,priority,created_at) VALUES (?,?,'english',?,'{}','[]',50,?)",
            (route_id, revision_id, digest({"job": platform, "sequence": sequence}), moment),
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
        adaptation_id = store.connection.execute(
            "INSERT INTO adaptation_runs(output_request_id,run_number,status,attempt_limit,created_at,"
            "completed_at) VALUES (?,1,?,1,?,?)",
            (output_id, "pending" if stop_at_adaptation else "succeeded", moment,
             None if stop_at_adaptation else moment),
        ).lastrowid
        if stop_at_adaptation:
            store.connection.commit()
            return adaptation_id
        count = 5 if platform == "instagram" else 1
        profile = "static_instagram_delivery_v1" if platform == "instagram" else "static_x_delivery_v1"
        width, height = (1080, 1350) if platform == "instagram" else (1200, 675)
        visual = {"schema_version": "static_social_visual_v1", "renderer": "html_playwright_v1",
                  "profile_id": profile, "width": width, "height": height,
                  "units": [{"role": "hook", "title": "Title", "body": "Body", "claim_ids": []}]
                           * count, "review_only": False}
        package = {"schema_version": "output_adaptation_v1", "platform": platform,
                   "account": binding["account"], "format": binding["content_format"],
                   "public_text": "Approved immutable copy", "private_tags": ["one", "two"],
                   "hashtags": [], "alt_text": "Accessible description", "claim_mappings": [],
                   "visual_spec": visual, "delivery_ready": True}
        package["caption" if platform == "instagram" else "post_text"] = "Approved immutable copy"
        if platform == "instagram":
            package["cta"] = None
        package_id = store.connection.execute(
            "INSERT INTO content_packages(output_request_id,adaptation_run_id,package_json,content_hash,"
            "visual_spec_json,created_at) VALUES (?,?,?,?,?,?)",
            (output_id, adaptation_id, canonical(package), digest(package), canonical(visual), moment),
        ).lastrowid
        render_id = store.connection.execute(
            "INSERT INTO render_runs(content_package_id,run_number,status,attempt_limit,created_at) "
            "VALUES (?,1,'claimed',1,?)", (package_id, moment),
        ).lastrowid
        store.connection.execute(
            "UPDATE render_runs SET claim_owner='test-render',claimed_at=?,lease_expires_at=?,"
            "claim_version=1,attempt_count=1 WHERE render_run_id=?",
            (moment, "2099-01-01T00:00:00+00:00", render_id),
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
        manifest = {"schema_version": "render_manifest_v1", "renderer": "html_playwright_v1",
                    "profile_id": profile, "content_hash": digest(package),
                    "browser_version": "fixture", "pillow_version": "fixture",
                    "review_only": False, "assets": assets}
        store.connection.commit()
        run = store.connection.execute("SELECT * FROM render_runs WHERE render_run_id=?", (render_id,)).fetchone()
        review_id = store.complete_render(run, manifest, assets)
        return review_id

    def test_current_schema_supports_production_and_is_idempotent(self):
        self.assertFalse(initialize_database(self.path))
        with connect(self.path) as connection:
            validate_database(connection)
            self.assertEqual(connection.execute("PRAGMA user_version").fetchone()[0], 6)
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM schema_migrations").fetchone()[0], 1)
            self.assertEqual(connection.execute("PRAGMA foreign_key_check").fetchall(), [])

    def test_production_catalog_is_blocked_until_readiness_is_current(self):
        with WorkflowStore(self.path, catalog_kind="production") as store:
            store.register_production_configuration(self.configuration())
            self.assertFalse(any(output["ready"] for item in store.catalog() for output in item["outputs"]))
            for row in store.connection.execute("SELECT social_destination_id FROM social_destinations"):
                store.record_destination_readiness(
                    row[0], status="ready", reasons=[], facts={"fixture": True},
                    valid_for=timedelta(days=1),
                )
            catalog = store.catalog()
            self.assertEqual(len(catalog), 5)
            self.assertTrue(all(len(item["outputs"]) == 2 for item in catalog))
            self.assertTrue(all(output["ready"] for item in catalog for output in item["outputs"]))

    def test_post_now_revalidates_exact_assets_and_can_cancel_pre_final(self):
        with WorkflowStore(self.path, catalog_kind="production") as store:
            self.configure(
                store, platforms=("x",), max_posts_per_day=2,
                min_post_interval_minutes=0,
            )
            review_id = self.create_review(store, "x")
            version = store.connection.execute(
                "SELECT row_version FROM review_requests WHERE review_request_id=?", (review_id,),
            ).fetchone()[0]
            record_id = store.authorize_post_now(review_id, row_version=version, command_id="post-x")
            self.assertEqual(record_id, store.authorize_post_now(
                review_id, row_version=version, command_id="post-x"
            ))
            record = store.connection.execute(
                "SELECT * FROM post_records WHERE post_record_id=?", (record_id,),
            ).fetchone()
            self.assertEqual(record["status"], "pending")
            store.cancel_delivery(record_id, row_version=record["row_version"], command_id="cancel-x")
            self.assertEqual(store.connection.execute(
                "SELECT status FROM post_records WHERE post_record_id=?", (record_id,),
            ).fetchone()[0], "cancelled")

    def test_post_now_refuses_tampered_reviewed_asset(self):
        with WorkflowStore(self.path, catalog_kind="production") as store:
            self.configure(store, platforms=("x",))
            review_id = self.create_review(store, "x")
            asset = store.connection.execute(
                "SELECT local_path FROM render_assets WHERE asset_role='delivery_jpeg'"
            ).fetchone()[0]
            Path(asset).write_bytes(b"tampered")
            version = store.connection.execute(
                "SELECT row_version FROM review_requests WHERE review_request_id=?", (review_id,),
            ).fetchone()[0]
            with self.assertRaisesRegex(ValueError, "hash|size"):
                store.authorize_post_now(review_id, row_version=version, command_id="tampered")
            self.assertEqual(store.connection.execute("SELECT COUNT(*) FROM post_requests").fetchone()[0], 0)

    def test_posting_success_and_ambiguous_final_failure_are_distinct(self):
        with WorkflowStore(self.path, catalog_kind="production") as store:
            self.configure(
                store, platforms=("x",), max_posts_per_day=2,
                min_post_interval_minutes=0,
            )
            first = self.create_review(store, "x")
            version = store.connection.execute(
                "SELECT row_version FROM review_requests WHERE review_request_id=?", (first,),
            ).fetchone()[0]
            first_record = store.authorize_post_now(first, row_version=version, command_id="publish")
            success = FakeDeliveryAdapter()
            self.assertEqual(CredentialedPostingAgent(store, x=success).run_once(), first_record)
            published = store.connection.execute(
                "SELECT status,external_post_id FROM post_records WHERE post_record_id=?", (first_record,),
            ).fetchone()
            self.assertEqual((published["status"], published["external_post_id"]),
                             ("published", "1122334455"))
            self.assertEqual(len(success.published), 1)

            second = self.create_review(store, "x")
            version = store.connection.execute(
                "SELECT row_version FROM review_requests WHERE review_request_id=?", (second,),
            ).fetchone()[0]
            second_record = store.authorize_post_now(second, row_version=version, command_id="unknown")
            failure = FakeDeliveryAdapter(fail_final=True)
            self.assertEqual(CredentialedPostingAgent(store, x=failure).run_once(), second_record)
            self.assertEqual(store.connection.execute(
                "SELECT status FROM post_records WHERE post_record_id=?", (second_record,),
            ).fetchone()[0], "publication_unknown")
            self.assertEqual(store.connection.execute(
                "SELECT COUNT(*) FROM reconciliation_requests WHERE post_record_id=?", (second_record,),
            ).fetchone()[0], 0)
            reconciliation_id = store.request_publication_reconciliation(
                second_record, command_id="reconcile-unknown",
            )
            self.assertGreater(reconciliation_id, 0)
            self.assertIsNone(CredentialedPostingAgent(store, x=failure).run_once())
            self.assertEqual(len(failure.published), 1)

    def test_committed_final_marker_blocks_cancel_and_requires_human_reconciliation(self):
        with WorkflowStore(self.path, catalog_kind="production") as store:
            self.configure(store, platforms=("x",), min_post_interval_minutes=0)
            review_id = self.create_review(store, "x")
            version = store.connection.execute(
                "SELECT row_version FROM review_requests WHERE review_request_id=?", (review_id,),
            ).fetchone()[0]
            record_id = store.authorize_post_now(
                review_id, row_version=version, command_id="marker-post",
            )
            record = store.claim("post_records", "post_record_id", "marker-worker")
            context = store.prepare_post_attempt(record)
            store.mark_attempt_ready(context["post_attempt_id"])
            store.mark_final_publication_request(context)
            current_version = store.connection.execute(
                "SELECT row_version FROM post_records WHERE post_record_id=?", (record_id,),
            ).fetchone()[0]
            with self.assertRaisesRegex(ValueError, "reconcile"):
                store.cancel_delivery(
                    record_id, row_version=current_version, command_id="too-late-cancel",
                )
            store.fail_post_attempt(
                context, category="transport", detail="response lost", retryable=True,
                after_final_marker=True,
            )
            reconciliation_id = store.request_publication_reconciliation(
                record_id, command_id="marker-reconcile",
            )
            request = store.claim(
                "reconciliation_requests", "reconciliation_request_id", "reconcile-worker",
            )
            check_id = store.record_reconciliation_check(
                request, outcome="confirmed_not_published", query_version="fixture",
                evidence={"fixture": True},
            )
            current = store.connection.execute(
                "SELECT row_version FROM reconciliation_requests "
                "WHERE reconciliation_request_id=?", (reconciliation_id,),
            ).fetchone()[0]
            store.resolve_publication_unknown(
                reconciliation_id, reconciliation_check_id=check_id,
                decision="leave_unknown", note="Provider evidence is still inconclusive.",
                row_version=current, command_id="leave-unknown",
            )
            self.assertEqual(store.connection.execute(
                "SELECT status FROM reconciliation_requests WHERE reconciliation_request_id=?",
                (reconciliation_id,),
            ).fetchone()[0], "resolved")
            self.assertEqual(store.connection.execute(
                "SELECT status FROM post_records WHERE post_record_id=?", (record_id,),
            ).fetchone()[0], "publication_unknown")

    def test_final_marker_rechecks_destination_readiness_and_live_lease(self):
        with WorkflowStore(self.path, catalog_kind="production") as store:
            self.configure(
                store, platforms=("x",), max_posts_per_day=2,
                min_post_interval_minutes=0,
            )
            review_id = self.create_review(store, "x")
            version = store.connection.execute(
                "SELECT row_version FROM review_requests WHERE review_request_id=?", (review_id,),
            ).fetchone()[0]
            store.authorize_post_now(review_id, row_version=version, command_id="stale-ready")
            record = store.claim("post_records", "post_record_id", "stale-ready-worker")
            context = store.prepare_post_attempt(record)
            store.mark_attempt_ready(context["post_attempt_id"])
            with store.transaction():
                store.connection.execute(
                    "UPDATE capability_readiness SET valid_until='2000-01-01T00:00:00+00:00'"
                )
            with self.assertRaisesRegex(RuntimeError, "readiness expired"):
                store.mark_final_publication_request(context)
            self.assertIsNone(store.connection.execute(
                "SELECT final_publication_request_sent_at FROM post_attempts WHERE post_attempt_id=?",
                (context["post_attempt_id"],),
            ).fetchone()[0])
            current_version = store.connection.execute(
                "SELECT row_version FROM post_records WHERE post_record_id=?",
                (context["post_record_id"],),
            ).fetchone()[0]
            store.cancel_delivery(
                context["post_record_id"], row_version=current_version,
                command_id="readiness-cancel-wins",
            )
            store.fail_post_attempt(
                context, category="final_marker", detail="readiness expired",
                retryable=False, after_final_marker=False,
            )
            self.assertEqual(store.connection.execute(
                "SELECT status FROM post_records WHERE post_record_id=?",
                (context["post_record_id"],),
            ).fetchone()[0], "cancelled")

            destination = store.connection.execute(
                "SELECT social_destination_id FROM social_destinations"
            ).fetchone()[0]
            store.record_destination_readiness(
                destination, status="ready", reasons=[], facts={"fixture": True},
                valid_for=timedelta(days=1),
            )
            second_review = self.create_review(store, "x")
            second_version = store.connection.execute(
                "SELECT row_version FROM review_requests WHERE review_request_id=?", (second_review,),
            ).fetchone()[0]
            store.authorize_post_now(
                second_review, row_version=second_version, command_id="stale-lease",
            )
            second = store.claim("post_records", "post_record_id", "stale-lease-worker")
            second_context = store.prepare_post_attempt(second)
            store.mark_attempt_ready(second_context["post_attempt_id"])
            with store.transaction():
                store.connection.execute(
                    "UPDATE post_records SET lease_expires_at='2000-01-01T00:00:00+00:00' "
                    "WHERE post_record_id=?", (second_context["post_record_id"],),
                )
            with self.assertRaisesRegex(RuntimeError, "claim is stale"):
                store.mark_final_publication_request(second_context)
            store.fail_post_attempt(
                second_context, category="final_marker", detail="lease expired",
                retryable=False, after_final_marker=False,
            )
            self.assertEqual(store.connection.execute(
                "SELECT status FROM post_records WHERE post_record_id=?",
                (second_context["post_record_id"],),
            ).fetchone()[0], "publishing")
            self.assertIsNone(store.connection.execute(
                "SELECT final_publication_request_sent_at FROM post_attempts WHERE post_attempt_id=?",
                (second_context["post_attempt_id"],),
            ).fetchone()[0])
            recovered = store.claim("post_records", "post_record_id", "recovery-worker")
            self.assertEqual(recovered["post_record_id"], second_context["post_record_id"])
            self.assertGreater(recovered["claim_version"], second_context["claim_version"])

    def test_x_adapter_uploads_alt_text_then_exact_post(self):
        image = Path(self.temporary.name) / "x.jpg"
        image.write_bytes(b"jpeg-fixture")
        transport = RecordingTransport([
            {"data": {"id": "101"}}, {"data": {"id": "101"}},
            {"data": {"id": "202", "text": "Approved immutable copy"}},
        ])
        records = []
        context = {
            "secret_ref": "X_USER_ACCESS_TOKEN",
            "destination_config": {"api_origin": "https://api.x.com",
                                   "media_upload_path": "/2/media/upload",
                                   "create_post_path": "/2/tweets"},
            "assets": [{"path": str(image), "bytes": len(image.read_bytes()),
                        "sha256": sha256(image.read_bytes()).hexdigest()}],
            "package": {"alt_text": "Accessible description", "post_text": "Approved immutable copy"},
        }
        with patch.dict("os.environ", {"X_USER_ACCESS_TOKEN": "secret"}):
            adapter = XDeliveryAdapter(transport=transport)
            staged = adapter.stage(context, lambda **value: records.append(value) or 1)
            self.assertEqual(adapter.publish(context, staged), "202")
        self.assertEqual([call[1] for call in transport.calls], [
            "https://api.x.com/2/media/upload", "https://api.x.com/2/media/metadata",
            "https://api.x.com/2/tweets",
        ])
        self.assertEqual(transport.calls[1][2]["json_body"]["metadata"]["alt_text"]["text"],
                         "Accessible description")
        self.assertEqual(transport.calls[2][2]["json_body"]["text"], "Approved immutable copy")

    def test_model_budget_is_reserved_before_call_and_settled_from_usage(self):
        policy = ModelBudgetPolicy(
            "fixture-model", Decimal("1"), Decimal("2"), 500_000, 1_000_000,
            1_000_000, {"intake": (100, 50), "determination": (100, 50),
                        "generation": (100, 50), "adaptation": (100, 50)},
        )
        with WorkflowStore(self.path, model_budget_policy=policy) as store:
            store.create_human_idea("A complete idea for admission.", command_id="budget")
            claim = store.claim("intake_requests", "intake_request_id", "budget-test")
            invocation = store.begin_model_invocation(
                phase="intake", table="intake_requests", key="intake_request_id", row=claim,
                request_version="fixture", prompt_version="fixture", schema_version="fixture",
                request_value={"safe": True}, model_id="fixture-model",
            )
            reservation = store.connection.execute(
                "SELECT status,worst_case_micro_usd,price_snapshot_hash FROM gemini_budget_reservations "
                "WHERE model_invocation_id=?", (invocation,),
            ).fetchone()
            self.assertEqual((reservation["status"], reservation["worst_case_micro_usd"]),
                             ("reserved", 200))
            self.assertEqual(reservation["price_snapshot_hash"], policy.fingerprint)
            store.finish_model_invocation(
                invocation, outcome="succeeded",
                usage=SimpleNamespace(input_tokens=10, output_tokens=5, total_tokens=15,
                                      model="fixture-model"),
                response_value={"ok": True},
            )
            settled = store.connection.execute(
                "SELECT status,settled_micro_usd FROM gemini_budget_reservations "
                "WHERE model_invocation_id=?", (invocation,),
            ).fetchone()
            self.assertEqual((settled["status"], settled["settled_micro_usd"]), ("settled", 20))

    def test_daily_model_budget_refusal_is_audited_and_deferred_without_a_call(self):
        policy = ModelBudgetPolicy(
            "fixture-model", Decimal("1"), Decimal("2"), 50, 100, 1_000,
            {"intake": (100, 50), "determination": (100, 50),
             "generation": (100, 50), "adaptation": (100, 50)},
        )
        client = FakeGeminiClient([{
            "editorial_goal": "Teach a phrase.", "topic": "break the ice",
            "coverage_kind": "language_subject", "canonical_target": "break the ice",
            "revision_scope": "whole_brief", "audience": "learners",
            "desired_outcome": "teach", "constraints": {},
            "source_context": "A local idea.", "open_questions": [],
        }])
        with WorkflowStore(self.path, model_budget_policy=policy) as store:
            request_id = store.create_human_idea(
                "Teach break the ice.", command_id="budget-block",
            )
            self.assertIsNone(GeminiIntakeWorker(store, client).run_once())
            request = store.connection.execute(
                "SELECT status,next_attempt_at,failure_detail FROM intake_requests "
                "WHERE intake_request_id=?", (request_id,),
            ).fetchone()
            self.assertEqual(request["status"], "retry_wait")
            self.assertIn("daily Gemini hard limit", request["failure_detail"])
            self.assertGreater(request["next_attempt_at"], now())
            self.assertEqual(client.calls, [])
            self.assertEqual(store.connection.execute(
                "SELECT outcome FROM model_invocations"
            ).fetchone()[0], "blocked")

    def test_production_adaptation_retries_only_metadata_from_checkpointed_body(self):
        first = {
            "post_text": "A focused practical lesson.",
            "visual_unit": {"role": "hook", "title": "Break the ice",
                            "body": "Ease the first awkward moment.", "claim_ids": []},
            "public_text_claim_ids": [], "private_tags": ["duplicate", "duplicate"],
            "hashtags": [], "alt_text": "A simple lesson card.",
        }
        metadata = {
            "private_tags": ["education", "language"], "hashtags": [],
            "alt_text": "A lesson card explaining how to ease an awkward first meeting.",
        }
        client = FakeGeminiClient([first, metadata])
        with WorkflowStore(self.path, catalog_kind="production") as store:
            self.configure(store, platforms=("x",))
            run_id = self.create_review(store, "x", stop_at_adaptation=True)
            package_id = GeminiAdaptationWorker(store, client, production=True).run_once()
            self.assertIsNotNone(package_id)
            run = store.connection.execute(
                "SELECT status,adapted_body_json,metadata_json FROM adaptation_runs "
                "WHERE adaptation_run_id=?", (run_id,),
            ).fetchone()
            self.assertEqual(run["status"], "succeeded")
            self.assertEqual(json.loads(run["adapted_body_json"])["post_text"], first["post_text"])
            self.assertEqual(json.loads(run["metadata_json"]), metadata)
            invocations = store.connection.execute(
                "SELECT prompt_version,outcome FROM model_invocations ORDER BY model_invocation_id"
            ).fetchall()
            self.assertEqual([row["outcome"] for row in invocations], ["schema_failed", "succeeded"])
            self.assertIn("metadata_retry", invocations[1]["prompt_version"])
            self.assertEqual(len(client.calls), 2)

    def test_instagram_r2_failure_keeps_audited_cleanup_target(self):
        relay = FailingRelay()
        with WorkflowStore(self.path, catalog_kind="production") as store:
            self.configure(store, platforms=("instagram",))
            review_id = self.create_review(store, "instagram")
            version = store.connection.execute(
                "SELECT row_version FROM review_requests WHERE review_request_id=?", (review_id,),
            ).fetchone()[0]
            record_id = store.authorize_post_now(
                review_id, row_version=version, command_id="instagram-stage-failure",
            )
            adapter = InstagramDeliveryAdapter(relay_factory=lambda _: relay)
            with patch.dict("os.environ", {"INSTAGRAM_ACCESS_TOKEN": "secret"}):
                self.assertEqual(
                    CredentialedPostingAgent(store, instagram=adapter).run_once(), record_id,
                )
            self.assertEqual(store.connection.execute(
                "SELECT status FROM post_records WHERE post_record_id=?", (record_id,),
            ).fetchone()[0], "retry_wait")
            resource = store.connection.execute(
                "SELECT status,remote_id FROM publication_resources"
            ).fetchone()
            self.assertEqual(resource["status"], "cleanup_pending")
            self.assertTrue(resource["remote_id"].startswith("instagram-transient/"))
            self.assertEqual(store.connection.execute(
                "SELECT COUNT(*) FROM delivery_cleanup_tasks WHERE status='pending'"
            ).fetchone()[0], 1)

    def test_live_readiness_uses_injected_provider_fakes_and_persists_results(self):
        transport = RecordingTransport([
            {"id": "123456", "username": "fixture_ig"},
            {"data": {"id": "654321", "username": "fixture_x"}},
        ])
        with WorkflowStore(self.path, catalog_kind="production") as store:
            store.register_production_configuration(self.configuration())
            monitor = CapabilityReadinessMonitor(
                store, transport=transport, relay_factory=lambda _: ReadinessRelay(),
            )
            with patch.dict("os.environ", {
                "INSTAGRAM_ACCESS_TOKEN": "secret", "X_USER_ACCESS_TOKEN": "secret",
                "R2_ACCESS_KEY_ID": "key", "R2_SECRET_ACCESS_KEY": "secret",
            }):
                results = monitor.run(live=True, confirm_r2_probe=True)
            self.assertEqual([item["status"] for item in results], ["ready", "ready"])
            self.assertEqual(len(transport.calls), 2)
            cached = monitor.run(live=True, confirm_r2_probe=True, only_due=True)
            self.assertTrue(all(item["cached"] for item in cached))
            self.assertEqual(len(transport.calls), 2)
            self.assertEqual(store.connection.execute(
                "SELECT COUNT(*) FROM capability_readiness_checks WHERE status='ready'"
            ).fetchone()[0], 2)

    def test_storage_state_only_gates_downstream_work(self):
        with WorkflowStore(self.path, enforce_storage=True) as store:
            store.create_human_idea("Planning is allowed.", command_id="missing-storage")
            self.assertFalse(store._storage_action_allowed('model'))
            with store.transaction():
                store.connection.execute(
                    "INSERT INTO storage_samples(state,free_bytes,total_bytes,database_bytes,wal_bytes,"
                    "artifact_bytes,backup_bytes,summary_json,sampled_at) "
                    "VALUES ('storage_warning',10,100,1,0,0,0,?,?)",
                    (canonical({"raw_state": "storage_warning"}), now()),
                )
            request_id = store.create_human_idea(
                "This human idea can wait under warning.", command_id="warning-storage",
            )
            self.assertIsNotNone(store.claim("intake_requests", "intake_request_id", "worker"))
            self.assertFalse(store._storage_action_allowed('model'))
            self.assertEqual(store.connection.execute(
                "SELECT status FROM intake_requests WHERE intake_request_id=?", (request_id,),
            ).fetchone()[0], "pending")

    def test_storage_sample_and_online_backup_restore_are_audited(self):
        backup_root = Path(self.temporary.name) / "backups"
        artifact_root = Path(self.temporary.name) / "artifacts"
        artifact_root.mkdir()
        with WorkflowStore(self.path) as store:
            sample_id = StorageMonitor(store, artifact_root, backup_root).run_once()
            self.assertGreater(sample_id, 0)
            service = MaintenanceService(store, backup_root)
            self.assertTrue(service.acquire())
            try:
                backup = service.backup()
                self.assertTrue(backup.is_file())
                service.checkpoint()
                service.verify_restore(backup)
            finally:
                service.close()
            statuses = store.connection.execute(
                "SELECT kind,status FROM maintenance_runs ORDER BY maintenance_run_id"
            ).fetchall()
            self.assertEqual([(row["kind"], row["status"]) for row in statuses], [
                ("sqlite_backup", "succeeded"), ("wal_checkpoint", "succeeded"),
                ("restore_verify", "succeeded"),
            ])

    def test_instagram_adapter_stages_ordered_children_and_publishes_parent(self):
        relay = FakeRelay()
        responses = []
        for ordinal in range(1, 6):
            responses += [{"id": str(ordinal)}, {"id": str(ordinal), "status_code": "FINISHED"}]
        responses += [{"id": "99"}, {"id": "99", "status_code": "FINISHED"}, {"id": "100"}]
        transport = RecordingTransport(responses)
        context = {
            "secret_ref": "INSTAGRAM_ACCESS_TOKEN", "provider_account_id": "123456",
            "destination_config": {
                "graph_api_version": "v24.0",
                "r2_public_domain": "https://media.example.com",
            },
            "post_record_id": 1, "attempt_number": 1,
            "assets": [{"ordinal": number, "sha256": str(number) * 64} for number in range(1, 6)],
            "package": {"caption": "Exact approved caption"},
        }
        records = []
        with patch.dict("os.environ", {"INSTAGRAM_ACCESS_TOKEN": "secret"}):
            adapter = InstagramDeliveryAdapter(
                transport=transport, relay_factory=lambda config: relay, pause=lambda _: None,
            )
            staged = adapter.stage(context, lambda **value: records.append(value) or len(records))
            self.assertEqual(adapter.publish(context, staged), "100")
        parent_call = transport.calls[-3]
        self.assertEqual(parent_call[2]["form"]["children"], "1,2,3,4,5")
        self.assertEqual(parent_call[2]["form"]["caption"], "Exact approved caption")
        self.assertEqual(transport.calls[-1][1],
                         "https://graph.facebook.com/v24.0/123456/media_publish")
        self.assertEqual(len([
            item for item in records if item.get("resource_type") == "r2_object"
        ]), 5)
        self.assertEqual(len([item for item in records if "resource_id" in item]), 11)


if __name__ == "__main__":
    unittest.main()
