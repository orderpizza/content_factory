"""Run persisted planning workers, or opt into Gemini review generation.

Deterministic default workers exercise planning boundaries only.
--gemini --planning-only stops at jobs. --gemini --review-preview produces
English Gemini review slides; unsupported domains stop explicitly at rendering.
"""

from __future__ import annotations

from argparse import ArgumentParser
from pathlib import Path
import os
import sys
import time
import math

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from common.environment import load_environment_file
from common.gemini import GeminiConfigurationError, configured_model
from common.timestamps import utc_now
from database.current import SchemaError
from workflow import (
    DeterminationWorker,
    GeminiAdaptationWorker,
    GeminiDeterminationWorker,
    GeminiIntakeWorker,
    GeminiPipelineRunner,
    IdeaIntakeWorker,
    ModelBudgetConfigurationError,
    ModelBudgetPolicy,
    VisualPlanner,
    WorkflowStore,
)
from workflow.maintenance import StorageMonitor
from workflow.development import configure_development_catalog
from workflow.gemini_image_renderer import DispatchVisualRenderer

ROOT = Path(__file__).resolve().parents[1]


_RUNTIME_TYPES = {
    "IdeaIntakeWorker": ("idea_intake", "brief_revision"),
    "GeminiIntakeWorker": ("idea_intake", "brief_revision"),
    "DeterminationWorker": ("determination", "determination_decision"),
    "GeminiDeterminationWorker": ("determination", "determination_decision"),
    "GeminiPipelineRunner": ("pipeline_runner", "canonical_content"),
    "GeminiAdaptationWorker": ("adaptation", "content_package"),
    "VisualPlanner": ("visual_planner", "visual_recipe"),
    "DispatchVisualRenderer": ("visual_renderer", "review_request"),
    "StorageMonitor": ("storage_monitor", "storage_sample"),
}


def _run_pass(workers: tuple[object, ...]) -> None:
    for worker in workers:
        store = worker.store
        class_name = worker.__class__.__name__
        worker_type, result_type = _RUNTIME_TYPES.get(
            class_name, (class_name.casefold(), "result")
        )
        instance_id = str(getattr(worker, "instance_id", worker_type))
        started_at = utc_now()
        store.heartbeat(worker_type, instance_id, "polling", "poll started")
        worker.last_operation = None
        try:
            result = worker.run_once()
        except Exception as error:
            store.heartbeat(
                worker_type, instance_id, "failed",
                f"poll raised {type(error).__name__}",
            )
            if worker_type == 'storage_monitor':
                # Observability must not become an indirect planning gate.
                from common.operation_log import emit
                emit('storage', 'sample_failed', status='failed', error_type=type(error).__name__)
                continue
            raise
        message = (
            "no output (idle, clarification, cancellation or failure; see dashboard)"
            if result is None else result
        )
        operation = getattr(worker, "last_operation", None)
        if result is None and operation:
            state = operation["status"]
            message = f'{operation["table"]} #{operation["id"]}: {state} — {operation["reason"]}'
            store.record_worker_result(worker_type, instance_id, operation["table"], operation["id"],
                                       started_at=started_at, summary=message,
                                       status="failed" if state == "failed" else "completed")
            store.heartbeat(worker_type, instance_id, state, message,
                            claim_type=operation["table"], claim_id=operation["id"])
        elif result is None:
            store.heartbeat(
                worker_type, instance_id, "idle",
                "no output; inspect persisted stage state for clarification or failure",
            )
        else:
            result_id = int(result)
            # Storage samples already provide their own append-only history; do
            # not duplicate the same cached sample on every five-second pass.
            if worker_type != "storage_monitor":
                store.record_worker_result(
                    worker_type, instance_id, result_type, result_id,
                    started_at=started_at, summary=f"produced {result_type} #{result_id}",
                )
            store.heartbeat(
                worker_type, instance_id, "completed", f"produced {result_type} #{result_id}",
                claim_type=result_type, claim_id=result_id,
            )
        print(f"{worker.__class__.__name__}: {message}")


def main() -> None:
    load_environment_file(ROOT / ".env")
    parser = ArgumentParser(description=__doc__)
    parser.add_argument("--database", default=os.getenv("CONTENT_FACTORY_DB_PATH", str(ROOT / "data" / "development.db")))
    parser.add_argument("--artifacts", default=os.getenv("CONTENT_FACTORY_ARTIFACT_ROOT", str(ROOT / "data" / "artifacts")))
    parser.add_argument("--backups", default=os.getenv("CONTENT_FACTORY_BACKUP_ROOT"))
    parser.add_argument("-gemini", "--gemini", action="store_true", help="use Gemini for Intake and Determination only")
    parser.add_argument(
        "--review-preview",
        action="store_true",
        help="also use Gemini for content/adaptation and render real local review assets",
    )
    parser.add_argument("-poll", "--poll", action="store_true", help="keep polling until interrupted")
    parser.add_argument("--poll-interval", type=float, default=5.0, metavar="SECONDS")
    parser.add_argument("--planning-only", action="store_true", help="stop at ContentJobs; no generation, rendering or posting")
    args = parser.parse_args()
    from common.operation_log import configure_logging
    configure_logging('workflow')
    if not math.isfinite(args.poll_interval) or args.poll_interval <= 0:
        parser.error("--poll-interval must be greater than zero")
    if args.planning_only and (args.review_preview):
        parser.error("--planning-only cannot compose downstream workers")
    if args.review_preview and not args.gemini:
        parser.error("--review-preview requires --gemini")
    try:
        budget_policy = ModelBudgetPolicy.from_environment(configured_model()) if args.gemini else None
        with WorkflowStore(args.database, model_budget_policy=budget_policy, enforce_storage=True) as store:
            configure_development_catalog(store)
            intake_worker = GeminiIntakeWorker(store) if args.gemini else IdeaIntakeWorker(store)
            determination_worker = (
                GeminiDeterminationWorker(store) if args.gemini else DeterminationWorker(store)
            )
            workers = (intake_worker, determination_worker)
            if args.review_preview:
                workers += (
                    GeminiPipelineRunner(store), GeminiAdaptationWorker(store),
                    VisualPlanner(store), DispatchVisualRenderer(store, args.artifacts),
                )
            workers = (StorageMonitor(store, args.artifacts, args.backups or ROOT / "data/backups"),) + workers
            if not args.poll:
                _run_pass(workers)
                return
            print(f"Polling every {args.poll_interval:g} seconds; press Ctrl+C to stop.")
            try:
                while True:
                    _run_pass(workers)
                    time.sleep(args.poll_interval)
            except KeyboardInterrupt:
                print("Workflow poller stopped.")
    except (
        GeminiConfigurationError, ModelBudgetConfigurationError,
        SchemaError, RuntimeError, ValueError,
    ) as error:
        raise SystemExit(f"Workflow worker refused: {error}")


if __name__ == "__main__":
    main()
