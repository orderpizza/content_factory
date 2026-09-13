"""Offline boundary tests for opt-in Gemini Intake and Determination."""

from __future__ import annotations

from copy import deepcopy
from http.server import ThreadingHTTPServer
from pathlib import Path
from threading import Thread
from types import ModuleType, SimpleNamespace
from unittest.mock import patch
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import Request, urlopen
import json
import runpy
import sys
import tempfile
import unittest

from common.gemini import GeminiUsage, VertexGeminiClient
from database.migrations import migrate_detection_dashboard, migrate_editorial_workflow
from detection.configuration import load_manifest
from detection.store import DetectionStore
from workflow import (
    GeminiAdaptationWorker,
    GeminiDeterminationWorker,
    GeminiIntakeWorker,
    GeminiPipelineRunner,
    StaticVisualRenderer,
    WORKFLOW_PIPELINES,
    WorkflowStore,
)
from workflow.gemini_determination import DETERMINATION_SCHEMA
from workflow.gemini_generation import DOMAIN_FIELDS, generation_schema
from workflow.gemini_intake import BRIEF_FIELDS, INTAKE_SCHEMA


ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "config" / "releases" / "detection-dashboard-v1.json"


class FakeGeminiClient:
    model = "fake-gemini"

    def __init__(self, response):
        self.response = response
        self.calls = []
        self.last_usage = GeminiUsage(120, 80, 200, self.model)

    def generate_json(self, prompt, schema, *, temperature):
        self.calls.append({"prompt": prompt, "schema": schema, "temperature": temperature})
        return deepcopy(self.response)


def brief(target: str = "break the ice") -> dict:
    return {
        "editorial_goal": f"Teach {target} in a useful context.",
        "topic": target,
        "coverage_kind": "language_subject",
        "canonical_target": target,
        "revision_scope": "whole_brief",
        "audience": "intermediate English learners",
        "desired_outcome": "teach",
        "constraints": {"contexts": ["business meetings"]},
        "source_context": "The human requested a practical language lesson.",
        "open_questions": [],
    }


class GeminiWorkflowTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.path = Path(self.temporary.name) / "content.db"
        migrate_detection_dashboard(self.path)
        with DetectionStore(self.path) as store:
            store.apply_manifest(load_manifest(MANIFEST))
        migrate_editorial_workflow(self.path)

    def register_catalog(self, store: WorkflowStore) -> None:
        for pipeline in WORKFLOW_PIPELINES:
            store.register_capability(
                pipeline,
                enabled=True,
                generation_ready=True,
                outputs=[
                    {
                        "platform": "instagram",
                        "account": f"fixture_{pipeline}",
                        "content_format": "instagram_static_carousel_v2",
                        "ready": True,
                        "safe_reason": "Gemini workflow test fixture",
                    },
                    {
                        "platform": "x",
                        "account": f"fixture_{pipeline}",
                        "content_format": "x_static_post_v1",
                        "ready": True,
                        "safe_reason": "Gemini workflow test fixture",
                    },
                ],
            )

    def create_determination_request(
        self, store: WorkflowStore, *, target: str = "break the ice", command_id: str = "idea"
    ) -> None:
        store.create_human_idea(f"Teach {target} in business meetings.", command_id=command_id)
        result = GeminiIntakeWorker(store, FakeGeminiClient(brief(target))).run_once()
        self.assertIsNotNone(result)

    @staticmethod
    def decision(
        catalog: list[dict], *, outcome: str = "accepted", selected_pipeline: str = "english"
    ) -> dict:
        routes = []
        for pipeline in WORKFLOW_PIPELINES:
            selected = outcome == "accepted" and pipeline == selected_pipeline
            routes.append({
                "pipeline_id": pipeline,
                "disposition": "selected" if selected else "skipped",
                "fit": "strong teaching fit" if selected else "weak domain fit",
                "reason": (
                    "The idea directly teaches an English expression."
                    if selected else "This domain would not add distinct reader value."
                ),
                "angle": ({
                    "angle_kind": "expression_in_context",
                    "canonical_target": "break the ice: business meetings",
                    "audience": "intermediate English learners",
                    "thesis": "Use the expression to describe easing initial social tension.",
                    "reader_value": "Apply the idiom naturally in a first meeting.",
                } if selected else None),
                "outputs": (
                    next(item for item in catalog if item["pipeline_id"] == pipeline)["outputs"]
                    if selected else []
                ),
            })
        return {
            "outcome": outcome,
            "opportunity_value": "A focused, practical teaching opportunity.",
            "rationale": "The request has clear audience value and a natural English-domain fit.",
            "warnings": [],
            "routes": routes,
        }

    @staticmethod
    def canonical_response(pipeline: str) -> dict:
        values = {
            "english": {
                "target_kind": "idiom", "target": "break the ice",
                "plain_meaning": "Make an unfamiliar social situation feel easier.",
                "nuance": "It focuses on easing initial tension.",
                "register_and_region": "Neutral conversational English.",
                "usage_notes": ["Use it when people are meeting or feel awkward."],
                "avoid_misuse": ["Do not use it for literal ice unless making a joke."],
            },
            "ai_tools": {
                "product_or_feature": "AI meeting assistant",
                "change_summary": "A hypothetical assistant workflow for meeting preparation.",
                "as_of_context": "Conceptual example; no current product claim.",
                "availability_scope": "No availability claim is made.",
                "capabilities": ["Draft a neutral opening question."],
                "use_cases": ["Prepare for a first team meeting."],
                "limitations": ["A human must review tone and accuracy."],
            },
            "personal_finance": {
                "event_or_topic": "First-meeting spending expectations",
                "as_of_context": "General educational scenario, not current market data.",
                "jurisdiction_or_population": "General adult audience.",
                "mechanism": "Set a small budget before a social business meeting.",
                "consumer_implications": ["A preset limit can reduce impulsive spending."],
                "uncertainty": "Individual circumstances differ.",
                "watch_points": ["Check whether an expense is reimbursable."],
                "disclaimer": "Educational information, not individualized financial advice.",
            },
            "business_side_hustle": {
                "customer_problem": "New groups can struggle to start productive conversation.",
                "opportunity_hypothesis": "A facilitation prompt pack may help meeting hosts.",
                "mechanism": "Test structured opening prompts with a small group.",
                "examples": ["A prompt card for a client workshop."],
                "prerequisites": ["Access to willing test participants."],
                "costs_and_risks": ["Prompts may feel generic without audience research."],
                "validation_actions": ["Interview five meeting facilitators."],
            },
            "psychology_behavior": {
                "observed_behavior": "People often hesitate in an unfamiliar group.",
                "context": "A first business meeting.",
                "concept": "Social uncertainty.",
                "possible_mechanism": "A low-stakes prompt may reduce ambiguity.",
                "alternative_explanations": ["Participants may simply need more time."],
                "example": "A host asks a neutral question before the agenda.",
                "practical_implications": ["Make participation optional."],
                "qualification": "This is a general interpretation, not a diagnosis.",
            },
        }
        return {
            "hook": f"A useful {pipeline} angle",
            "context": "A practical, carefully qualified explanation.",
            "key_points": ["Start with the audience need.", "Use a concrete example."],
            "examples": ["A fictional first-meeting scenario."],
            "takeaway": "Use the idea deliberately and review it before publication.",
            "cta": None,
            "claims": [{
                "claim_id": f"{pipeline}.example.1",
                "text": "The scenario is illustrative rather than a verified event.",
                "claim_kind": "generated_example",
                "evidence_reference_ids": [],
                "qualification": "Fictional example.",
            }],
            "domain_payload": values[pipeline],
        }

    @staticmethod
    def adaptation_response(platform: str, claim_id: str = "english.example.1") -> dict:
        common = {
            "private_tags": ["education", "review fixture"],
            "hashtags": ["#english", "#learning"] if platform == "instagram" else [],
            "alt_text": "A clean educational card explaining an idea.",
            "public_text_claim_ids": [claim_id],
        }
        if platform == "instagram":
            return {
                **common,
                "caption_summary": "Learn the meaning, nuance, and use of this expression.",
                "cta": "Save this for your next meeting.",
                "visual_units": [
                    {"role": "hook", "title": "Break the ice", "body": "A natural way to ease a first meeting.", "claim_ids": []},
                    {"role": "explanation", "title": "What it means", "body": "Make an unfamiliar social situation feel easier.", "claim_ids": []},
                    {"role": "example", "title": "At work", "body": "The host opened with a friendly, low-stakes question.", "claim_ids": [claim_id]},
                    {"role": "example", "title": "Notice the nuance", "body": "The focus is the first awkward moment, not the whole relationship.", "claim_ids": []},
                    {"role": "takeaway", "title": "Try it deliberately", "body": "Use the idiom when someone helps a new group relax.", "claim_ids": []},
                ],
            }
        return {
            **common,
            "post_text": "Break the ice describes easing the initial tension in an unfamiliar social situation.",
            "visual_unit": {
                "role": "hook", "title": "Break the ice",
                "body": "Ease the first awkward moment—not the literal ice.",
                "claim_ids": [],
            },
        }

    def prepare_english_canonical(self, store: WorkflowStore, *, command_id: str = "production") -> int:
        self.register_catalog(store)
        self.create_determination_request(store, command_id=command_id)
        catalog = json.loads(store.connection.execute(
            "SELECT input_snapshot_json FROM determination_requests WHERE status='pending' "
            "ORDER BY determination_request_id LIMIT 1"
        ).fetchone()[0])["catalog"]
        GeminiDeterminationWorker(
            store, FakeGeminiClient(self.decision(catalog, selected_pipeline="english"))
        ).run_once()
        canonical_id = GeminiPipelineRunner(
            store, FakeGeminiClient(self.canonical_response("english"))
        ).run_once()
        self.assertIsNotNone(canonical_id)
        return canonical_id

    def prepare_packages(self, store: WorkflowStore, *, command_id: str = "packages") -> list[int]:
        self.prepare_english_canonical(store, command_id=command_id)
        instagram = GeminiAdaptationWorker(
            store, FakeGeminiClient(self.adaptation_response("instagram"))
        ).run_once()
        x_package = GeminiAdaptationWorker(
            store, FakeGeminiClient(self.adaptation_response("x"))
        ).run_once()
        self.assertIsNotNone(instagram)
        self.assertIsNotNone(x_package)
        return [instagram, x_package]

    def test_gemini_intake_produces_valid_brief(self):
        client = FakeGeminiClient(brief())
        with WorkflowStore(self.path) as store:
            store.create_human_idea(
                "Teach the idiom break the ice in business meetings.", command_id="intake-valid"
            )
            revision_id = GeminiIntakeWorker(store, client).run_once()
            self.assertIsNotNone(revision_id)
            revision = store.connection.execute(
                "SELECT brief_json FROM brief_revisions WHERE revision_id=?", (revision_id,)
            ).fetchone()
            frozen = json.loads(revision["brief_json"])
            self.assertEqual(set(BRIEF_FIELDS), set(frozen))
            self.assertEqual(frozen["canonical_target"], "break the ice")
            self.assertIs(client.calls[0]["schema"], INTAKE_SCHEMA)
            self.assertIn("Do not select or recommend a domain pipeline", client.calls[0]["prompt"])
            usage = store.connection.execute(
                "SELECT outcome,input_tokens,output_tokens,total_tokens FROM model_invocations"
            ).fetchone()
            self.assertEqual(tuple(usage), ("succeeded", 120, 80, 200))

    def test_gemini_runner_registration_is_complete_and_idempotent(self):
        register = runpy.run_path(str(ROOT / "scripts" / "run_workflow.py"))[
            "register_gemini_placeholder_capabilities"
        ]
        with WorkflowStore(self.path) as store:
            register(store)
            register(store)
            catalog = store.catalog()
            self.assertEqual({item["pipeline_id"] for item in catalog}, set(WORKFLOW_PIPELINES))
            self.assertTrue(all(item["enabled"] and item["generation_ready"] for item in catalog))
            self.assertTrue(all(len(item["outputs"]) == 2 for item in catalog))
            self.assertTrue(all(
                output["account"] == f"fixture_{item['pipeline_id']}"
                for item in catalog for output in item["outputs"]
            ))

    def test_gemini_intake_triggers_clarification(self):
        client = FakeGeminiClient({"open_questions": ["What topic?"]})
        with WorkflowStore(self.path) as store:
            request_id = store.create_human_idea("Maybe something", command_id="clarify")
            self.assertIsNone(GeminiIntakeWorker(store, client).run_once())
            request = store.connection.execute(
                "SELECT status FROM intake_requests WHERE intake_request_id=?", (request_id,)
            ).fetchone()
            self.assertEqual(request["status"], "needs_clarification")
            self.assertEqual(store.connection.execute("SELECT COUNT(*) FROM brief_revisions").fetchone()[0], 0)
            self.assertEqual(
                store.connection.execute(
                    "SELECT body FROM thread_messages WHERE author_kind='intake_agent'"
                ).fetchone()[0],
                "What topic?",
            )

    def test_gemini_determination_produces_valid_routes_and_job(self):
        with WorkflowStore(self.path) as store:
            self.register_catalog(store)
            self.create_determination_request(store)
            catalog = json.loads(store.connection.execute(
                "SELECT input_snapshot_json FROM determination_requests"
            ).fetchone()[0])["catalog"]
            client = FakeGeminiClient(self.decision(catalog))
            decision_id = GeminiDeterminationWorker(store, client).run_once()
            self.assertIsNotNone(decision_id)
            routes = store.connection.execute(
                "SELECT pipeline_id,disposition,reason,angle_json FROM determination_routes "
                "WHERE determination_decision_id=? ORDER BY pipeline_id",
                (decision_id,),
            ).fetchall()
            self.assertEqual(len(routes), 5)
            self.assertEqual(sum(route["disposition"] == "selected" for route in routes), 1)
            self.assertTrue(all(route["reason"] for route in routes))
            selected = next(route for route in routes if route["disposition"] == "selected")
            self.assertIsNotNone(selected["angle_json"])
            self.assertEqual(store.connection.execute("SELECT COUNT(*) FROM content_jobs").fetchone()[0], 1)
            self.assertIs(client.calls[0]["schema"], DETERMINATION_SCHEMA)
            self.assertIn("all five domain", client.calls[0]["prompt"])

    def test_gemini_determination_rejects_low_value_idea_without_jobs(self):
        with WorkflowStore(self.path) as store:
            self.register_catalog(store)
            self.create_determination_request(store)
            catalog = json.loads(store.connection.execute(
                "SELECT input_snapshot_json FROM determination_requests"
            ).fetchone()[0])["catalog"]
            response = self.decision(catalog, outcome="not_recommended")
            response["opportunity_value"] = "Too vague to justify content production."
            response["rationale"] = "None of the domains can add sufficient reader value."
            decision_id = GeminiDeterminationWorker(store, FakeGeminiClient(response)).run_once()
            self.assertIsNotNone(decision_id)
            self.assertEqual(store.connection.execute("SELECT COUNT(*) FROM content_jobs").fetchone()[0], 0)
            routes = store.connection.execute(
                "SELECT disposition,reason FROM determination_routes WHERE determination_decision_id=?",
                (decision_id,),
            ).fetchall()
            self.assertEqual(len(routes), 5)
            self.assertTrue(all(route["disposition"] == "skipped" and route["reason"] for route in routes))

    def test_schema_validation_fails_claim_without_persisting_garbage(self):
        mutations = {
            "missing_route": lambda response: response["routes"].pop(),
            "wrong_route_count": lambda response: response["routes"].append(deepcopy(response["routes"][0])),
            "selected_without_angle": lambda response: response["routes"][0].update({"angle": None}),
        }
        with WorkflowStore(self.path) as store:
            self.register_catalog(store)
            for index, (name, mutate) in enumerate(mutations.items(), start=1):
                with self.subTest(case=name):
                    target = f"break the ice variation {index}"
                    self.create_determination_request(
                        store, target=target, command_id=f"bad-{index}"
                    )
                    request = store.connection.execute(
                        "SELECT * FROM determination_requests WHERE status='pending' "
                        "ORDER BY determination_request_id LIMIT 1"
                    ).fetchone()
                    catalog = json.loads(request["input_snapshot_json"])["catalog"]
                    response = self.decision(catalog)
                    response["routes"][0]["angle"]["canonical_target"] = target
                    mutate(response)
                    self.assertIsNone(
                        GeminiDeterminationWorker(store, FakeGeminiClient(response)).run_once()
                    )
                    failed = store.connection.execute(
                        "SELECT status FROM determination_requests WHERE determination_request_id=?",
                        (request["determination_request_id"],),
                    ).fetchone()
                    self.assertEqual(failed["status"], "failed")
            self.assertEqual(store.connection.execute("SELECT COUNT(*) FROM determination_decisions").fetchone()[0], 0)
            self.assertEqual(store.connection.execute("SELECT COUNT(*) FROM content_jobs").fetchone()[0], 0)

    def test_gemini_generation_validates_every_domain_and_fans_out_outputs(self):
        with WorkflowStore(self.path) as store:
            self.register_catalog(store)
            for index, pipeline in enumerate(WORKFLOW_PIPELINES, start=1):
                with self.subTest(pipeline=pipeline):
                    target = f"generation fixture {pipeline} {index}"
                    self.create_determination_request(
                        store, target=target, command_id=f"generate-{pipeline}"
                    )
                    request = store.connection.execute(
                        "SELECT input_snapshot_json FROM determination_requests "
                        "WHERE status='pending' ORDER BY determination_request_id LIMIT 1"
                    ).fetchone()
                    catalog = json.loads(request["input_snapshot_json"])["catalog"]
                    GeminiDeterminationWorker(
                        store,
                        FakeGeminiClient(self.decision(catalog, selected_pipeline=pipeline)),
                    ).run_once()
                    client = FakeGeminiClient(self.canonical_response(pipeline))
                    canonical_id = GeminiPipelineRunner(store, client).run_once()
                    self.assertIsNotNone(canonical_id)
                    canonical = json.loads(store.connection.execute(
                        "SELECT canonical_json FROM canonical_contents WHERE canonical_content_id=?",
                        (canonical_id,),
                    ).fetchone()[0])
                    self.assertEqual(canonical["pipeline_id"], pipeline)
                    self.assertEqual(set(canonical["domain_payload"]), set(DOMAIN_FIELDS[pipeline]))
                    self.assertEqual(
                        set(client.calls[0]["schema"]["properties"]["domain_payload"]["required"]),
                        set(DOMAIN_FIELDS[pipeline]),
                    )
                    self.assertIn("platform-neutral canonical", client.calls[0]["prompt"])
                    output_count = store.connection.execute(
                        "SELECT COUNT(*) FROM output_requests WHERE canonical_content_id=?",
                        (canonical_id,),
                    ).fetchone()[0]
                    self.assertEqual(output_count, 2)
                    job_recipe = json.loads(store.connection.execute(
                        "SELECT recipe_json FROM content_jobs WHERE content_job_id=("
                        "SELECT content_job_id FROM canonical_contents WHERE canonical_content_id=?)",
                        (canonical_id,),
                    ).fetchone()[0])
                    self.assertIn("source_context", job_recipe)

            invocations = store.connection.execute(
                "SELECT outcome,total_tokens FROM model_invocations WHERE phase='generation'"
            ).fetchall()
            self.assertEqual(len(invocations), len(WORKFLOW_PIPELINES))
            self.assertTrue(all(row["outcome"] == "succeeded" and row["total_tokens"] == 200 for row in invocations))

    def test_gemini_generation_rejects_wrong_domain_payload(self):
        with WorkflowStore(self.path) as store:
            self.register_catalog(store)
            self.create_determination_request(store, target="invalid generation", command_id="bad-generation")
            catalog = json.loads(store.connection.execute(
                "SELECT input_snapshot_json FROM determination_requests WHERE status='pending'"
            ).fetchone()[0])["catalog"]
            GeminiDeterminationWorker(
                store, FakeGeminiClient(self.decision(catalog, selected_pipeline="english"))
            ).run_once()
            response = self.canonical_response("english")
            del response["domain_payload"]["plain_meaning"]
            self.assertIsNone(GeminiPipelineRunner(store, FakeGeminiClient(response)).run_once())
            run = store.connection.execute("SELECT status FROM generation_runs").fetchone()
            invocation = store.connection.execute(
                "SELECT outcome FROM model_invocations WHERE phase='generation'"
            ).fetchone()
            self.assertEqual(run["status"], "failed")
            self.assertEqual(invocation["outcome"], "schema_failed")
            self.assertEqual(store.connection.execute("SELECT COUNT(*) FROM canonical_contents").fetchone()[0], 0)

    def test_generation_schema_rejects_unknown_pipeline(self):
        with self.assertRaisesRegex(ValueError, "unsupported workflow pipeline"):
            generation_schema("unknown")

    def test_gemini_adaptation_creates_independent_validated_packages(self):
        with WorkflowStore(self.path) as store:
            canonical_id = self.prepare_english_canonical(store, command_id="adapt-valid")
            instagram_client = FakeGeminiClient(self.adaptation_response("instagram"))
            instagram_id = GeminiAdaptationWorker(store, instagram_client).run_once()
            x_client = FakeGeminiClient(self.adaptation_response("x"))
            x_id = GeminiAdaptationWorker(store, x_client).run_once()
            self.assertIsNotNone(instagram_id)
            self.assertIsNotNone(x_id)
            packages = store.connection.execute(
                "SELECT p.package_json FROM content_packages p JOIN output_requests o "
                "ON o.output_request_id=p.output_request_id "
                "WHERE o.canonical_content_id=? ORDER BY o.output_request_id",
                (canonical_id,),
            ).fetchall()
            self.assertEqual(len(packages), 2)
            instagram, x_package = [json.loads(row[0]) for row in packages]
            self.assertEqual(len(instagram["visual_spec"]["units"]), 5)
            self.assertEqual(instagram["visual_spec"]["profile_id"], "static_instagram_review_v1")
            self.assertEqual(x_package["visual_spec"]["profile_id"], "static_x_review_v1")
            self.assertFalse(instagram["delivery_ready"])
            self.assertFalse(x_package["delivery_ready"])
            self.assertIn("synthetic_destination_review_only", instagram_client.calls[0]["prompt"])
            self.assertEqual(
                store.connection.execute(
                    "SELECT COUNT(*) FROM render_runs WHERE status='pending'"
                ).fetchone()[0],
                2,
            )

    def test_gemini_adaptation_rejects_unmapped_canonical_claim(self):
        with WorkflowStore(self.path) as store:
            self.prepare_english_canonical(store, command_id="adapt-bad")
            response = self.adaptation_response("instagram")
            response["public_text_claim_ids"] = []
            response["visual_units"][2]["claim_ids"] = []
            self.assertIsNone(GeminiAdaptationWorker(store, FakeGeminiClient(response)).run_once())
            run = store.connection.execute(
                "SELECT status FROM adaptation_runs ORDER BY adaptation_run_id LIMIT 1"
            ).fetchone()
            invocation = store.connection.execute(
                "SELECT outcome FROM model_invocations WHERE phase='adaptation'"
            ).fetchone()
            self.assertEqual(run["status"], "failed")
            self.assertEqual(invocation["outcome"], "schema_failed")
            self.assertEqual(store.connection.execute("SELECT COUNT(*) FROM content_packages").fetchone()[0], 0)

    def test_static_renderer_produces_exact_review_assets_for_both_platforms(self):
        artifact_root = Path(self.temporary.name) / "artifacts"
        with WorkflowStore(self.path) as store:
            package_ids = self.prepare_packages(store, command_id="render-valid")
            before = {
                row["content_package_id"]: row["package_json"]
                for row in store.connection.execute(
                    "SELECT content_package_id,package_json FROM content_packages"
                ).fetchall()
            }
            first_review = StaticVisualRenderer(store, artifact_root).run_once()
            second_review = StaticVisualRenderer(store, artifact_root).run_once()
            self.assertIsNotNone(first_review)
            self.assertIsNotNone(second_review)
            reviews = store.connection.execute(
                "SELECT content_package_id,status FROM review_requests ORDER BY review_request_id"
            ).fetchall()
            self.assertEqual([row["content_package_id"] for row in reviews], package_ids)
            self.assertTrue(all(row["status"] == "awaiting_review" for row in reviews))
            asset_counts = store.connection.execute(
                "SELECT r.content_package_id,COUNT(*) count FROM render_assets a "
                "JOIN render_runs r ON r.render_run_id=a.render_run_id "
                "GROUP BY r.content_package_id ORDER BY r.content_package_id"
            ).fetchall()
            self.assertEqual([row["count"] for row in asset_counts], [15, 3])
            for row in store.connection.execute(
                "SELECT local_path,width,height,mime_type FROM render_assets "
                "WHERE asset_role='delivery_jpeg'"
            ).fetchall():
                path = Path(row["local_path"])
                self.assertTrue(path.is_file())
                from PIL import Image
                with Image.open(path) as image:
                    self.assertEqual(image.format, "JPEG")
                    self.assertEqual(image.size, (row["width"], row["height"]))
            asset_id = store.connection.execute(
                "SELECT render_asset_id FROM render_assets "
                "WHERE asset_role='delivery_jpeg' ORDER BY render_asset_id LIMIT 1"
            ).fetchone()[0]
            handler = runpy.run_path(str(ROOT / "scripts" / "serve_dashboard.py"))[
                "DashboardHandler"
            ]
            handler.database_path = str(self.path)
            handler.artifact_root = artifact_root.resolve()
            server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
            thread = Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                base = f"http://127.0.0.1:{server.server_address[1]}"
                with urlopen(base + "/", timeout=5) as response:
                    self.assertIn("img-src 'self' data:", response.headers["Content-Security-Policy"])
                with urlopen(base + f"/asset?render_asset_id={asset_id}", timeout=5) as response:
                    self.assertEqual(response.headers.get_content_type(), "image/jpeg")
                    self.assertGreater(len(response.read()), 1000)
            finally:
                server.shutdown()
                server.server_close()
                thread.join(timeout=5)
            after = {
                row["content_package_id"]: row["package_json"]
                for row in store.connection.execute(
                    "SELECT content_package_id,package_json FROM content_packages"
                ).fetchall()
            }
            self.assertEqual(before, after)

    def test_dashboard_http_command_enforces_csrf_and_only_creates_intake_handoff(self):
        handler = runpy.run_path(str(ROOT / "scripts" / "serve_dashboard.py"))[
            "DashboardHandler"
        ]
        handler.database_path = str(self.path)
        handler.artifact_root = (Path(self.temporary.name) / "artifacts").resolve()
        handler.csrf_token = "dashboard-test-token"
        server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
        thread = Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            url = f"http://127.0.0.1:{server.server_address[1]}/commands"
            data = urlencode({
                "csrf_token": "dashboard-test-token",
                "command_kind": "new_idea",
                "command_id": "dashboard-http-idea",
                "body": "Teach a useful phrase in a business meeting.",
            }).encode("utf-8")
            request = Request(
                url,
                data=data,
                headers={"Content-Type": "application/x-www-form-urlencoded"},
            )
            with urlopen(request, timeout=5) as response:
                page = response.read().decode("utf-8")
                self.assertIn("Idea accepted as Intake request #1", page)

            bad = Request(
                url,
                data=urlencode({
                    "csrf_token": "wrong",
                    "command_kind": "new_idea",
                    "command_id": "dashboard-http-bad",
                    "body": "This must not persist.",
                }).encode("utf-8"),
                headers={"Content-Type": "application/x-www-form-urlencoded"},
            )
            with self.assertRaises(HTTPError) as raised:
                urlopen(bad, timeout=5)
            self.assertEqual(raised.exception.code, 400)
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=5)

        with WorkflowStore(self.path) as store:
            self.assertEqual(store.connection.execute("SELECT COUNT(*) FROM content_threads").fetchone()[0], 1)
            self.assertEqual(store.connection.execute("SELECT COUNT(*) FROM intake_requests").fetchone()[0], 1)
            self.assertEqual(store.connection.execute("SELECT COUNT(*) FROM brief_revisions").fetchone()[0], 0)
            self.assertEqual(store.connection.execute("SELECT COUNT(*) FROM model_invocations").fetchone()[0], 0)

    def test_vertex_client_uses_json_schema_and_records_usage_without_network(self):
        calls = []

        class GenerateContentConfig:
            def __init__(self, **values):
                self.values = values

        response = SimpleNamespace(
            text='{"ok": true}',
            usage_metadata=SimpleNamespace(
                prompt_token_count=3, candidates_token_count=2, total_token_count=5
            ),
        )
        fake_genai = ModuleType("google.genai")
        fake_genai.types = SimpleNamespace(GenerateContentConfig=GenerateContentConfig)

        class Client:
            def __init__(self, **values):
                calls.append(("client", values))
                self.models = SimpleNamespace(generate_content=self.generate_content)

            def generate_content(self, **values):
                calls.append(("generate", values))
                return response

        fake_genai.Client = Client
        fake_google = ModuleType("google")
        fake_google.genai = fake_genai
        with patch.dict(sys.modules, {"google": fake_google, "google.genai": fake_genai}):
            client = VertexGeminiClient(project="fixture-project", location="fixture-location", model="fixture-model")
            result = client.generate_json("prompt", {"type": "object"}, temperature=0.3)
        self.assertEqual(result, {"ok": True})
        self.assertEqual(client.last_usage, GeminiUsage(3, 2, 5, "fixture-model"))
        self.assertEqual(calls[0][1]["project"], "fixture-project")
        self.assertEqual(calls[1][1]["config"].values["response_mime_type"], "application/json")


if __name__ == "__main__":
    unittest.main()
