"""Run or poll the persisted workflow workers.

The default workers are local placeholders. ``--gemini`` opts human Idea Intake
and Determination into Vertex Gemini; detected trends already arrive at
Determination with a source-backed brief. ``--review-preview`` additionally enables
Gemini canonical generation/adaptation and real local static rendering.
``--production`` switches to the immutable real-destination catalog and
delivery profiles; ``--delivery`` additionally runs credentialed posting and
R2 cleanup. Every public post still requires a dashboard Post now command.
"""

from __future__ import annotations

from argparse import ArgumentParser
from pathlib import Path
import os
import sys
import time
import math
from datetime import datetime, timezone

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from common.environment import load_environment_file
from common.gemini import GeminiConfigurationError, configured_model
from database.current import SchemaError, validate_database
from workflow import (
    WORKFLOW_PIPELINES,
    AdaptationWorker,
    CredentialedPostingAgent,
    DeterminationWorker,
    GeminiAdaptationWorker,
    GeminiDeterminationWorker,
    GeminiIntakeWorker,
    GeminiPipelineRunner,
    IdeaIntakeWorker,
    ModelBudgetConfigurationError,
    ModelBudgetPolicy,
    PipelineRunner,
    PublicationReconciliationWorker,
    PostingAgent,
    R2CleanupWorker,
    StaticVisualRenderer,
    VisualRenderer,
    WorkflowStore,
)
from workflow.maintenance import StorageMonitor

ROOT = Path(__file__).resolve().parents[1]


def _placeholder_outputs(pipeline: str) -> list[dict[str, object]]:
    reason = "auto-registered placeholder for Gemini evaluation"
    return [
        {
            "platform": "instagram",
            "account": f"fixture_{pipeline}",
            "content_format": "instagram_static_carousel_v2",
            "ready": True,
            "safe_reason": reason,
        },
        {
            "platform": "x",
            "account": f"fixture_{pipeline}",
            "content_format": "x_static_post_v1",
            "ready": True,
            "safe_reason": reason,
        },
    ]


def register_gemini_placeholder_capabilities(store: WorkflowStore) -> None:
    """Idempotently expose five synthetic domains to Gemini Determination."""
    for pipeline in WORKFLOW_PIPELINES:
        try:
            store.register_capability(
                pipeline,
                enabled=True,
                generation_ready=True,
                outputs=_placeholder_outputs(pipeline),
            )
        except ValueError:
            # Immutable fixture registration rejects changed input. Validate the
            # complete catalog below instead of mutating the prior definition.
            pass
    catalog = {item["pipeline_id"]: item for item in store.catalog()}
    if set(catalog) != set(WORKFLOW_PIPELINES):
        raise ValueError("Gemini workflow requires all five placeholder capabilities")
    for pipeline in WORKFLOW_PIPELINES:
        capability = catalog[pipeline]
        expected = {
            (item["platform"], item["account"], item["content_format"])
            for item in _placeholder_outputs(pipeline)
        }
        actual = {
            (item["platform"], item["account"], item["content_format"])
            for item in capability["outputs"]
            if item["ready"]
        }
        if not capability["enabled"] or not capability["generation_ready"] or actual != expected:
            raise ValueError(
                f"existing immutable fixture for {pipeline} conflicts with the Gemini placeholder catalog"
            )


_RUNTIME_TYPES = {
    "IdeaIntakeWorker": ("idea_intake", "brief_revision"),
    "GeminiIntakeWorker": ("idea_intake", "brief_revision"),
    "DeterminationWorker": ("determination", "determination_decision"),
    "GeminiDeterminationWorker": ("determination", "determination_decision"),
    "PipelineRunner": ("pipeline_runner", "canonical_content"),
    "GeminiPipelineRunner": ("pipeline_runner", "canonical_content"),
    "AdaptationWorker": ("adaptation", "content_package"),
    "GeminiAdaptationWorker": ("adaptation", "content_package"),
    "VisualRenderer": ("visual_renderer", "review_request"),
    "StaticVisualRenderer": ("visual_renderer", "review_request"),
    "PostingAgent": ("posting_agent", "post_record"),
    "CredentialedPostingAgent": ("posting_agent", "post_record"),
    "R2CleanupWorker": ("cleanup", "delivery_cleanup_task"),
    "PublicationReconciliationWorker": ("publication_reconciliation", "reconciliation_request"),
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
        started_at = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
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
    parser.add_argument(
        "--production", action="store_true",
        help="use real destinations, priced Gemini admission, and delivery-ready profiles",
    )
    parser.add_argument(
        "--delivery", action="store_true",
        help="run credentialed Posting/R2 cleanup workers; requires --production and Post now authorization",
    )
    parser.add_argument("-poll", "--poll", action="store_true", help="keep polling until interrupted")
    parser.add_argument("--poll-interval", type=float, default=5.0, metavar="SECONDS")
    parser.add_argument("--planning-only", action="store_true", help="stop at ContentJobs; no generation, rendering or posting")
    args = parser.parse_args()
    from common.operation_log import configure_logging
    configure_logging('workflow')
    if not math.isfinite(args.poll_interval) or args.poll_interval <= 0:
        parser.error("--poll-interval must be greater than zero")
    if args.planning_only and (args.review_preview or args.production or args.delivery):
        parser.error("--planning-only cannot compose downstream workers")
    if args.review_preview and not args.gemini:
        parser.error("--review-preview requires --gemini")
    if args.production and not (args.gemini and args.review_preview):
        parser.error("--production requires --gemini --review-preview")
    if args.delivery and not args.production:
        parser.error("--delivery requires --production")
    if args.production and not args.backups:
        parser.error("--production requires --backups or CONTENT_FACTORY_BACKUP_ROOT")
    try:
        budget_policy = ModelBudgetPolicy.from_environment(configured_model()) if args.gemini else None
        store_context = (
            WorkflowStore(
                args.database,
                catalog_kind="production",
                model_budget_policy=budget_policy,
                enforce_storage=True,
            )
            if args.production else WorkflowStore(args.database, model_budget_policy=budget_policy, enforce_storage=True)
        )
        with store_context as store:
            if args.production:
                validate_database(store.connection)
                catalog = store.catalog()
                if len(catalog) != len(WORKFLOW_PIPELINES):
                    raise ValueError("production catalog must register all five domains")
            elif args.gemini:
                register_gemini_placeholder_capabilities(store)
            intake_worker = GeminiIntakeWorker(store) if args.gemini else IdeaIntakeWorker(store)
            determination_worker = (
                GeminiDeterminationWorker(store) if args.gemini else DeterminationWorker(store)
            )
            workers = (intake_worker, determination_worker)
            if not args.planning_only:
                pipeline_worker = (
                    GeminiPipelineRunner(store) if args.review_preview else PipelineRunner(store)
                )
                adaptation_worker = (
                    GeminiAdaptationWorker(store, production=args.production)
                    if args.review_preview else AdaptationWorker(store)
                )
                renderer_worker = (
                    StaticVisualRenderer(store, args.artifacts, production=args.production)
                    if args.review_preview else VisualRenderer(store, args.artifacts)
                )
                workers = (
                    intake_worker, determination_worker, pipeline_worker,
                    adaptation_worker, renderer_worker,
                )
            workers = (StorageMonitor(store, args.artifacts, args.backups or ROOT / "data/backups"),) + workers
            if args.production:
                if args.delivery:
                    workers += (
                        CredentialedPostingAgent(store, artifact_root=args.artifacts), R2CleanupWorker(store),
                        PublicationReconciliationWorker(store),
                    )
            elif not args.planning_only:
                workers += (PostingAgent(store),)
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
