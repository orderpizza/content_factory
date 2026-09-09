import tempfile
import unittest
import json
from pathlib import Path

from database.migrations import migrate_detection_dashboard, migrate_editorial_workflow
from detection.configuration import load_manifest
from detection.store import DetectionStore
from dashboard import render_workflow_trace
from workflow import AdaptationWorker, DeterminationWorker, IdeaIntakeWorker, PipelineRunner, PostingAgent, VisualRenderer, WorkflowStore


ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "config" / "releases" / "detection-dashboard-v1.json"


class WorkflowV2Tests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / "content.db"
        migrate_detection_dashboard(self.path)
        with DetectionStore(self.path) as store:
            store.apply_manifest(load_manifest(MANIFEST))
        self.assertTrue(migrate_editorial_workflow(self.path))

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
            self.assertEqual(len(routes), 5)
            self.assertEqual(sum(row[0] == "selected" for row in routes), 1)
            self.assertIn("Five domain routes", render_workflow_trace(store.connection))
            self.assertIsNotNone(PipelineRunner(store).run_once())
            self.assertIsNotNone(AdaptationWorker(store).run_once())
            review_id = VisualRenderer(store, Path(self.tmp.name) / "artifacts").run_once()
            self.assertIsNotNone(review_id)
            review = store.connection.execute("SELECT row_version FROM review_requests WHERE review_request_id=?", (review_id,)).fetchone()
            with self.assertRaisesRegex(ValueError, "disabled"):
                store.approve_review(review_id, row_version=review[0], command_id="approve-1")
            self.assertIsNone(PostingAgent(store).run_once())
            self.assertEqual(store.connection.execute("SELECT COUNT(*) FROM post_requests").fetchone()[0], 0)

    def test_unconfigured_domains_are_visible_as_explicit_skips(self):
        with WorkflowStore(self.path) as store:
            store.create_human_idea("A sufficiently specific but unconfigured idea", command_id="idea-2")
            IdeaIntakeWorker(store).run_once()
            decision_id = DeterminationWorker(store).run_once()
            outcome = store.connection.execute("SELECT outcome FROM determination_decisions WHERE determination_decision_id=?", (decision_id,)).fetchone()[0]
            routes = store.connection.execute("SELECT disposition,fit FROM determination_routes WHERE determination_decision_id=?", (decision_id,)).fetchall()
            self.assertEqual(outcome, "not_recommended")
            self.assertEqual(len(routes), 5)
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


if __name__ == "__main__":
    unittest.main()
