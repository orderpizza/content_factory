"""Workflow planning; offline tests use temporary databases and fake providers."""

from dashboard import render_workflow_trace
from database.current import initialize_database
from detection.configuration import load_manifest
from detection.store import DetectionStore
from pathlib import Path
from workflow import DeterminationWorker, IdeaIntakeWorker, VisualPlanner, WorkflowStore
from workflow.workers import AdaptationWorker, PipelineRunner, VisualRenderer
import json
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]


class HumanCommandTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / "fixture.db"
        self.manifest = load_manifest(ROOT / "config/releases/detection.json")
        initialize_database(self.path)
        with DetectionStore(self.path) as store:
            store.apply_manifest(self.manifest)

    def human(self, store):
        request = store.create_human_idea("Explain a useful learning habit", command_id="idea")
        row = store.connection.execute("SELECT * FROM intake_requests WHERE intake_request_id=?", (request,)).fetchone()
        return row["thread_id"]

    def version(self, store, thread):
        return store.connection.execute("SELECT row_version FROM content_threads WHERE thread_id=?", (thread,)).fetchone()[0]

    def test_command_versions_receipts_and_input_limits(self):
        with WorkflowStore(self.path) as store:
            thread = self.human(store)
            old = self.version(store, thread)
            IdeaIntakeWorker(store).run_once()
            self.assertGreater(self.version(store, thread), old)
            for version in (None, old):
                with self.assertRaises(ValueError):
                    store.continue_human_thread(thread, "Add a daily example", command_id="reply", expected_row_version=version)
            version = self.version(store, thread)
            reply = store.continue_human_thread(thread, "Add a daily example", command_id="reply", expected_row_version=version)
            self.assertEqual(reply, store.continue_human_thread(thread, "Add a daily example", command_id="reply", expected_row_version=version))
            with self.assertRaises(ValueError):
                store.continue_human_thread(thread, "Different input", command_id="reply", expected_row_version=version)
            with self.assertRaises(ValueError):
                store.create_human_idea("An idea", command_id=" ")

    def test_aggregate_conversation_limit_is_visible_failure_not_stranded_claim(self):
        with WorkflowStore(self.path) as store:
            thread = self.human(store)
            with store.connection:
                for sequence in range(2, 7):
                    message = store.connection.execute("INSERT INTO thread_messages(thread_id,sequence_number,author_kind,body,created_at) VALUES (?,?,'human',?,'2026-09-09T00:00:00')", (thread, sequence, "a" * 8000))
                store.connection.execute("UPDATE intake_requests SET context_json=?", (json.dumps({"kind": "human_conversation", "last_message_id": message.lastrowid}),))
            self.assertIsNone(IdeaIntakeWorker(store).run_once())
            row = store.connection.execute("SELECT status,failure_detail FROM intake_requests").fetchone()
            self.assertEqual(tuple(row), ("failed", "input_too_large"))
            self.assertIn("input_too_large", render_workflow_trace(store.connection))


MANIFEST = ROOT / "config" / "releases" / "detection.json"


class DeterministicWorkflowTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / "development.db"
        initialize_database(self.path)
        with DetectionStore(self.path) as store:
            store.apply_manifest(load_manifest(MANIFEST))

    def test_full_placeholder_lineage_and_disabled_delivery(self):
        with WorkflowStore(self.path) as store:
            store.register_capability("english", enabled=True, generation_ready=True, outputs=[{
                "platform": "instagram", "account": "fixture_english", "content_format": "instagram_static_carousel_v2", "ready": True,
            }])
            request_id = store.create_human_idea("Explain why a practical AI tool matters to ordinary users.", command_id="idea-1")
            self.assertEqual(request_id, store.create_human_idea("Explain why a practical AI tool matters to ordinary users.", command_id="idea-1"))
            self.assertIsNotNone(IdeaIntakeWorker(store).run_once())
            decision_id = DeterminationWorker(store).run_once()
            self.assertIsNotNone(decision_id)
            routes = store.connection.execute("SELECT disposition FROM determination_routes WHERE determination_decision_id=?", (decision_id,)).fetchall()
            self.assertEqual(len(routes), 3)
            self.assertEqual(sum(row[0] == "selected" for row in routes), 1)
            self.assertIn("Three domain routes", render_workflow_trace(store.connection))
            self.assertIsNotNone(PipelineRunner(store).run_once())
            self.assertIsNotNone(VisualPlanner(store).run_once())
            self.assertIsNotNone(AdaptationWorker(store).run_once())
            review_id = VisualRenderer(store, Path(self.tmp.name) / "artifacts").run_once()
            self.assertIsNotNone(review_id)
            review = store.connection.execute("SELECT row_version FROM review_requests WHERE review_request_id=?", (review_id,)).fetchone()
            self.assertEqual(
                store.approve_review(review_id, row_version=review[0], command_id="approve-1"),
                review_id,
            )
            self.assertEqual(
                store.connection.execute(
                    "SELECT status FROM review_requests WHERE review_request_id=?", (review_id,)
                ).fetchone()[0],
                "approved",
            )
            self.assertEqual(store.connection.execute("SELECT COUNT(*) FROM post_requests").fetchone()[0], 0)

    def test_unconfigured_domains_are_visible_as_explicit_skips(self):
        with WorkflowStore(self.path) as store:
            store.create_human_idea("A sufficiently specific but unconfigured idea", command_id="idea-2")
            IdeaIntakeWorker(store).run_once()
            decision_id = DeterminationWorker(store).run_once()
            outcome = store.connection.execute("SELECT outcome FROM determination_decisions WHERE determination_decision_id=?", (decision_id,)).fetchone()[0]
            routes = store.connection.execute("SELECT disposition,fit FROM determination_routes WHERE determination_decision_id=?", (decision_id,)).fetchall()
            self.assertEqual(outcome, "not_recommended")
            self.assertEqual(len(routes), 3)
            self.assertTrue(all(row[0] == "skipped" and row[1] == "not_evaluated" for row in routes))

    def test_human_can_answer_intake_clarification_and_refine_same_thread(self):
        with WorkflowStore(self.path) as store:
            first_request = store.create_human_idea("maybe", command_id="idea-short")
            self.assertIsNone(IdeaIntakeWorker(store).run_once())
            initial = store.connection.execute(
                "SELECT thread_id,status FROM intake_requests WHERE intake_request_id=?", (first_request,)
            ).fetchone()
            self.assertEqual(initial["status"], "needs_clarification")
            thread = store.connection.execute(
                "SELECT row_version FROM content_threads WHERE thread_id=?", (initial["thread_id"],)
            ).fetchone()
            reply = store.continue_human_thread(
                initial["thread_id"], "Explain a useful study habit for new English learners.",
                command_id="clarification-reply", expected_row_version=thread["row_version"],
            )
            self.assertEqual(reply, store.continue_human_thread(
                initial["thread_id"], "Explain a useful study habit for new English learners.",
                command_id="clarification-reply", expected_row_version=thread["row_version"],
            ))
            revision_one = IdeaIntakeWorker(store).run_once()
            first_brief = store.connection.execute(
                "SELECT * FROM brief_revisions WHERE revision_id=?", (revision_one,)
            ).fetchone()
            source = json.loads(first_brief["source_snapshot_json"])
            self.assertEqual(len(source["messages"]), 3)  # idea, Intake question, human reply

            revision_request = store.continue_human_thread(
                initial["thread_id"], "Make the tone encouraging and include a concrete daily example.",
                command_id="brief-refinement",
                expected_row_version=store.connection.execute("SELECT row_version FROM content_threads WHERE thread_id=?", (initial["thread_id"],)).fetchone()[0],
            )
            self.assertIsNotNone(revision_request)
            revision_two = IdeaIntakeWorker(store).run_once()
            second_brief = store.connection.execute(
                "SELECT * FROM brief_revisions WHERE revision_id=?", (revision_two,)
            ).fetchone()
            self.assertEqual(second_brief["parent_revision_id"], revision_one)
            self.assertEqual(json.loads(second_brief["brief_json"])["topic"], json.loads(first_brief["brief_json"])["topic"])
            self.assertIn("encouraging", json.loads(second_brief["brief_json"])["constraints"]["requested_changes"][-1])

    def test_dashboard_review_feedback_reenters_intake_without_authorizing_delivery(self):
        with WorkflowStore(self.path) as store:
            store.register_capability("english", enabled=True, generation_ready=True, outputs=[{
                "platform": "instagram", "account": "fixture_english",
                "content_format": "instagram_static_carousel_v2", "ready": True,
            }])
            store.create_human_idea("Teach a practical meeting phrase.", command_id="review-idea")
            IdeaIntakeWorker(store).run_once()
            DeterminationWorker(store).run_once()
            PipelineRunner(store).run_once()
            VisualPlanner(store).run_once()
            AdaptationWorker(store).run_once()
            review_id = VisualRenderer(store, Path(self.tmp.name) / "review-artifacts").run_once()
            review = store.connection.execute(
                "SELECT row_version FROM review_requests WHERE review_request_id=?", (review_id,)
            ).fetchone()
            html = render_workflow_trace(
                store.connection, interactive=True, csrf_token="test-token"
            )
            self.assertIn("Submit an idea", html)
            self.assertIn("Request changes", html)
            self.assertIn("test-token", html)

            request_id = store.request_review_changes(
                review_id,
                note="Use a more concrete workplace example.",
                row_version=review["row_version"],
                command_id="review-change",
            )
            self.assertEqual(request_id, store.request_review_changes(
                review_id,
                note="Use a more concrete workplace example.",
                row_version=review["row_version"],
                command_id="review-change",
            ))
            self.assertEqual(
                store.connection.execute(
                    "SELECT status FROM review_requests WHERE review_request_id=?", (review_id,)
                ).fetchone()[0],
                "changes_requested",
            )
            intake = store.connection.execute(
                "SELECT context_json,status FROM intake_requests WHERE intake_request_id=?", (request_id,)
            ).fetchone()
            self.assertEqual(intake["status"], "pending")
            self.assertEqual(json.loads(intake["context_json"])["revision_scope"], "output_request")
            self.assertEqual(store.connection.execute("SELECT COUNT(*) FROM post_requests").fetchone()[0], 0)
