"""Offline smoke-readiness and workflow-runtime visibility tests."""

from __future__ import annotations

from contextlib import redirect_stdout
from datetime import timedelta
from hashlib import sha256
from io import StringIO
from pathlib import Path
import json
import runpy
import tempfile
import unittest

from database.migrations import (
    migrate_detection_dashboard,
    migrate_detection_safety,
    migrate_editorial_workflow,
    migrate_production_workflow,
)
from detection.configuration import load_manifest
from detection.store import DetectionStore
from workflow import (
    AdaptationWorker,
    GeminiAdaptationWorker,
    GeminiPipelineRunner,
    PipelineRunner,
    PublicationReconciliationWorker,
    R2CleanupWorker,
    StaticVisualRenderer,
    VisualRenderer,
    WORKFLOW_PIPELINES,
    WorkflowStore,
    inspect_smoke_readiness,
)
from workflow.maintenance import MaintenanceService, StorageMonitor
from workflow.store import now


ROOT = Path(__file__).resolve().parents[1]
NORMALIZED_MANIFEST = ROOT / "config" / "releases" / "detection-normalized-v3.json"
FIXTURE_MANIFEST = ROOT / "config" / "releases" / "detection-dashboard-v1.json"
_run_pass = runpy.run_path(str(ROOT / "scripts" / "run_workflow.py"))["_run_pass"]


def dependencies_ready():
    return {
        "google_genai": (True, "fixture SDK is importable"),
        "playwright_chromium": (True, "fixture browser is installed"),
    }


class _RuntimeFixtureWorker:
    instance_id = "runtime-fixture"

    def __init__(self, store: WorkflowStore, result: int | None):
        self.store = store
        self.result = result

    def run_once(self) -> int | None:
        return self.result


class _ClaimRecorder:
    model_budget_policy = None

    def __init__(self):
        self.calls = []

    def claim(self, *args, **kwargs):
        self.calls.append((args, kwargs))
        return None


class SmokeReadinessTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.database = self.root / "content.db"
        self.artifacts = self.root / "artifacts"
        self.backups = self.root / "backups"

    def migrate(self, *, production: bool) -> None:
        migrate_detection_dashboard(self.database)
        migrate_editorial_workflow(self.database)
        if production:
            migrate_detection_safety(self.database)
        with DetectionStore(self.database) as store:
            store.apply_manifest(load_manifest(
                NORMALIZED_MANIFEST if production else FIXTURE_MANIFEST
            ))
        if production:
            migrate_production_workflow(self.database)

    def production_configuration(self, font: Path) -> dict:
        font_hash = sha256(font.read_bytes()).hexdigest()
        destination = {
            "destination_key": "x:smoke",
            "platform": "x",
            "account_key": "smoke",
            "provider_account_id": "654321",
            "secret_ref": "X_USER_ACCESS_TOKEN",
            "enabled": True,
            "config": {
                "api_origin": "https://api.x.com",
                "media_upload_path": "/2/media/upload",
                "create_post_path": "/2/tweets",
                "adapter_version": "x_static_post_delivery_v1",
                "image_max_bytes": 5_000_000,
            },
            "posting_policy": {
                "timezone": "Asia/Seoul",
                "max_posts_per_day": 1,
                "min_post_interval_minutes": 1200,
                "authorization_ttl_hours": 48,
            },
        }
        return {
            "policy_version": "production_configuration_v1",
            "approved_by": "test-owner",
            "approved_at": now(),
            "profile_approved": True,
            "renderer_profile": {
                "profile_version": "static_social_delivery_profiles_v1",
                "template_version": "static_social_template_v1",
                "font_path": str(font.resolve()),
                "font_sha256": font_hash,
            },
            "destinations": [destination],
            "bindings": [
                {
                    "pipeline_id": pipeline,
                    "destination_key": destination["destination_key"],
                    "content_format": "x_static_post_v1",
                }
                for pipeline in WORKFLOW_PIPELINES
            ],
        }

    @staticmethod
    def environment() -> dict[str, str]:
        return {
            "GOOGLE_CLOUD_PROJECT": "fixture-project",
            "GEMINI_MODEL": "fixture-model",
            "GEMINI_INPUT_COST_PER_MILLION_USD": "0.10",
            "GEMINI_OUTPUT_COST_PER_MILLION_USD": "0.40",
            "GEMINI_DAILY_WARNING_USD": "1.00",
            "GEMINI_DAILY_HARD_LIMIT_USD": "2.00",
            "GEMINI_JOB_HARD_LIMIT_USD": "0.50",
            "X_USER_ACCESS_TOKEN": "secret-value-must-not-appear",
        }

    def test_preview_preflight_requires_only_local_gemini_and_renderer_inputs(self):
        self.migrate(production=False)
        report = inspect_smoke_readiness(
            self.database, self.artifacts, None,
            mode="preview", environment={"GOOGLE_CLOUD_PROJECT": "fixture-project"},
            dependency_probe=dependencies_ready,
        )
        self.assertEqual(report["status"], "ready")
        self.assertFalse(report["network_calls_made"])
        self.assertNotIn("production_configuration", {
            item["check"] for item in report["checks"]
        })

    def test_delivery_preflight_closes_local_gates_and_never_exposes_secrets(self):
        self.migrate(production=True)
        font = self.root / "font.ttf"
        font.write_bytes(b"fixture-font")
        with WorkflowStore(self.database, catalog_kind="production") as store:
            store.register_production_configuration(self.production_configuration(font))
            destination_id = int(store.connection.execute(
                "SELECT social_destination_id FROM social_destinations"
            ).fetchone()[0])
            store.record_destination_readiness(
                destination_id, status="ready", reasons=[], facts={"fixture": True},
                valid_for=timedelta(hours=1),
            )
            service = MaintenanceService(store, self.backups)
            service.backup()
            StorageMonitor(store, self.artifacts, self.backups).run_once()

        report = inspect_smoke_readiness(
            self.database, self.artifacts, self.backups,
            mode="delivery", environment=self.environment(),
            dependency_probe=dependencies_ready,
        )
        self.assertEqual(report["status"], "ready")
        encoded = json.dumps(report)
        self.assertNotIn("secret-value-must-not-appear", encoded)
        self.assertIn("x_secrets", {item["check"] for item in report["checks"]})

        missing = self.environment()
        del missing["X_USER_ACCESS_TOKEN"]
        blocked = inspect_smoke_readiness(
            self.database, self.artifacts, self.backups,
            mode="delivery", environment=missing,
            dependency_probe=dependencies_ready,
        )
        self.assertEqual(blocked["status"], "blocked")
        self.assertTrue(any(
            item["check"] == "x_secrets" and item["status"] == "blocked"
            for item in blocked["checks"]
        ))

    def test_workflow_pass_updates_heartbeat_without_idle_run_spam(self):
        self.migrate(production=False)
        with WorkflowStore(self.database) as store:
            worker = _RuntimeFixtureWorker(store, 42)
            with redirect_stdout(StringIO()):
                _run_pass((worker,))
            heartbeat = store.connection.execute(
                "SELECT * FROM worker_heartbeats WHERE instance_id='runtime-fixture'"
            ).fetchone()
            self.assertEqual(heartbeat["state"], "completed")
            self.assertEqual(heartbeat["claim_id"], 42)
            self.assertEqual(store.connection.execute(
                "SELECT COUNT(*) FROM worker_runs"
            ).fetchone()[0], 1)

            worker.result = None
            with redirect_stdout(StringIO()):
                _run_pass((worker,))
            heartbeat = store.connection.execute(
                "SELECT * FROM worker_heartbeats WHERE instance_id='runtime-fixture'"
            ).fetchone()
            self.assertEqual(heartbeat["state"], "idle")
            self.assertEqual(store.connection.execute(
                "SELECT COUNT(*) FROM worker_runs"
            ).fetchone()[0], 1)

    def test_long_local_stages_use_the_contract_ten_minute_initial_lease(self):
        store = _ClaimRecorder()
        workers = (
            PipelineRunner(store),
            GeminiPipelineRunner(store, client=object()),
            AdaptationWorker(store),
            GeminiAdaptationWorker(store, client=object()),
            VisualRenderer(store, self.artifacts),
            StaticVisualRenderer(store, self.artifacts),
            R2CleanupWorker(store),
            PublicationReconciliationWorker(store, transport=object()),
        )
        for worker in workers:
            worker.run_once()
        self.assertEqual(len(store.calls), len(workers))
        self.assertTrue(all(call[1].get("lease_seconds") == 600 for call in store.calls))


if __name__ == "__main__":
    unittest.main()
