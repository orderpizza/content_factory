"""Offline smoke-readiness and workflow-runtime visibility tests."""

from __future__ import annotations
from contextlib import redirect_stdout
from database.current import initialize_database
from detection.configuration import load_manifest
from detection.store import DetectionStore
from io import StringIO
from pathlib import Path
from workflow import GeminiAdaptationWorker, GeminiPipelineRunner, VisualPlanner, WorkflowStore, inspect_smoke_readiness
from workflow.delivery import PublicationReconciliationWorker, R2CleanupWorker
from workflow.static_renderer import StaticVisualRenderer
from workflow.workers import AdaptationWorker, PipelineRunner, VisualRenderer
import runpy
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "config" / "releases" / "detection.json"
_run_pass = runpy.run_path(str(ROOT / "scripts" / "run_workflow.py"))["_run_pass"]


def dependencies_ready():
    return {
        "google_genai": (True, "fixture SDK is importable"),
        "pillow": (True, "fixture image processor is installed"),
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
        self.database = self.root / "development.db"
        self.artifacts = self.root / "artifacts"
        self.backups = self.root / "backups"

    def initialize(self) -> None:
        initialize_database(self.database)
        with DetectionStore(self.database) as store:
            store.apply_manifest(load_manifest(MANIFEST))

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
            "GEMINI_IMAGE_INPUT_COST_PER_MILLION_USD": "1",
            "GEMINI_IMAGE_OUTPUT_COST_PER_MILLION_USD": "1",
        }

    def test_preview_preflight_requires_only_local_gemini_and_renderer_inputs(self):
        self.initialize()
        report = inspect_smoke_readiness(
            self.database, self.artifacts,
            mode="preview", environment=self.environment(),
            dependency_probe=dependencies_ready,
        )
        self.assertEqual(report["status"], "ready")
        self.assertFalse(report["network_calls_made"])
        self.assertNotIn("production_configuration", {
            item["check"] for item in report["checks"]
        })


    def test_workflow_pass_updates_heartbeat_without_idle_run_spam(self):
        self.initialize()
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
            VisualPlanner(store),
            VisualRenderer(store, self.artifacts),
            StaticVisualRenderer(store, self.artifacts),
            R2CleanupWorker(store),
            PublicationReconciliationWorker(store),
        )
        for worker in workers:
            worker.run_once()
        self.assertEqual(len(store.calls), len(workers))
        self.assertTrue(all(call[1].get("lease_seconds") == 600 for call in store.calls))


if __name__ == "__main__":
    unittest.main()
