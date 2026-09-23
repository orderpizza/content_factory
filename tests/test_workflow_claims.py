"""Workflow claims; offline tests use temporary databases and fake providers."""

from database.current import initialize_database
from detection.configuration import load_manifest
from detection.store import DetectionStore
from pathlib import Path
from workflow import DeterminationWorker, IdeaIntakeWorker, VisualPlanner, WorkflowStore
from workflow.workers import AdaptationWorker, PipelineRunner, VisualRenderer
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]


class WorkflowClaimTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / "fixture.db"
        self.manifest = load_manifest(ROOT / "config/releases/detection.json")
        initialize_database(self.path)
        with DetectionStore(self.path) as store:
            store.apply_manifest(self.manifest)

    def route(self, store):
        return store.register_capability("english", enabled=True, generation_ready=True, outputs=[{
            "platform": "instagram", "account": "fixture", "content_format": "instagram_static_carousel_v2", "ready": True,
        }])

    def human(self, store):
        request = store.create_human_idea("Explain a useful learning habit", command_id="idea")
        row = store.connection.execute("SELECT * FROM intake_requests WHERE intake_request_id=?", (request,)).fetchone()
        return row["thread_id"]

    def test_expired_claim_cannot_finalize_without_reassignment(self):
        with WorkflowStore(self.path) as store:
            self.human(store)
            row = store.claim("intake_requests", "intake_request_id", "old")
            with store.connection:
                store.connection.execute("UPDATE intake_requests SET lease_expires_at='2000-01-01T00:00:00'")
            with self.assertRaisesRegex(RuntimeError, "stale claim"):
                store.clarify_intake(row, "Must not persist")
            self.assertEqual(store.connection.execute("SELECT COUNT(*) FROM thread_messages").fetchone()[0], 1)

    def test_expired_local_claim_is_recovered_with_fencing_and_attempt_limit(self):
        with WorkflowStore(self.path) as store:
            self.human(store)
            old = store.claim("intake_requests", "intake_request_id", "old")
            with store.connection:
                store.connection.execute("UPDATE intake_requests SET lease_expires_at='2000-01-01T00:00:00'")
            new = store.claim("intake_requests", "intake_request_id", "new")
            self.assertGreater(new["claim_version"], old["claim_version"])
            with self.assertRaises(RuntimeError):
                store.clarify_intake(old, "stale")
            with store.connection:
                store.connection.execute("UPDATE intake_requests SET lease_expires_at='2000-01-01T00:00:00',attempt_count=attempt_limit")
            self.assertIsNone(store.claim("intake_requests", "intake_request_id", "last"))
            self.assertEqual(store.connection.execute("SELECT status FROM intake_requests").fetchone()[0], "failed")

    def test_model_history_prevents_automatic_claim_retry(self):
        with WorkflowStore(self.path) as store:
            self.human(store)
            row = store.claim("intake_requests", "intake_request_id", "old")
            with store.connection:
                store.connection.execute("UPDATE intake_requests SET lease_expires_at='2000-01-01T00:00:00'")
                store.connection.execute(
                    "INSERT INTO model_invocations(phase,entity_type,entity_id,attempt_ordinal,request_version,prompt_version,schema_version,request_hash,outcome,started_at) "
                    "VALUES ('intake','intake_request',?,1,'fixture','fixture','fixture',?,'started','2000-01-01T00:00:00')",
                    (row["intake_request_id"], "a" * 64),
                )
            self.assertIsNone(store.claim("intake_requests", "intake_request_id", "new"))
            self.assertEqual(store.connection.execute("SELECT status FROM intake_requests").fetchone()[0], "failed")

    def test_closed_thread_cancellation_commits_without_creating_children(self):
        with WorkflowStore(self.path) as store:
            thread = self.human(store)
            worker = IdeaIntakeWorker(store)
            row = store.claim("intake_requests", "intake_request_id", worker.instance_id)
            with store.connection:
                store.connection.execute("UPDATE content_threads SET status='cancelled' WHERE thread_id=?", (thread,))
            self.assertIsNone(worker._process(row))
            self.assertEqual(store.connection.execute("SELECT status FROM intake_requests").fetchone()[0], "cancelled")
            self.assertEqual(store.connection.execute("SELECT COUNT(*) FROM brief_revisions").fetchone()[0], 0)

    def test_cancellation_fences_every_downstream_finalizer(self):
        stages = [
            ("determination_requests", "determination_request_id", DeterminationWorker, "determination_decisions"),
            ("generation_runs", "generation_run_id", PipelineRunner, "canonical_contents"),
            ("visual_plan_runs", "visual_plan_run_id", VisualPlanner, "visual_recipes"),
            ("adaptation_runs", "adaptation_run_id", AdaptationWorker, "content_packages"),
            ("render_runs", "render_run_id", lambda s: VisualRenderer(s, Path(self.tmp.name) / "assets"), "review_requests"),
        ]
        with WorkflowStore(self.path) as store:
            self.route(store)
            thread = self.human(store)
            IdeaIntakeWorker(store).run_once()
            for table, key, factory, children in stages:
                with self.subTest(table=table):
                    worker = factory(store)
                    row = store.claim(table, key, worker.instance_id)
                    with store.connection:
                        store.connection.execute("UPDATE content_threads SET status='cancelled' WHERE thread_id=?", (thread,))
                    # Exercise the finalizer directly, without filesystem work.
                    if table == "render_runs":
                        result = store.complete_render(row, {}, {})
                    else:
                        result = worker._process(row)
                    self.assertIsNone(result)
                    self.assertEqual(store.connection.execute(f"SELECT status FROM {table} WHERE {key}=?", (row[key],)).fetchone()[0], "cancelled")
                    self.assertEqual(store.connection.execute(f"SELECT COUNT(*) FROM {children}").fetchone()[0], 0)
                    # Fixture-only restoration to advance the next independent boundary.
                    with store.connection:
                        store.connection.execute("UPDATE content_threads SET status='open' WHERE thread_id=?", (thread,))
                        store.connection.execute(f"UPDATE {table} SET status='pending' WHERE {key}=?", (row[key],))
                    worker.run_once()
