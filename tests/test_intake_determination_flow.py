import json
import tempfile
import unittest
from pathlib import Path

from common.models import TrendCandidate
from dashboard import render_dashboard
from database.sqlite import Database
from determination.service import DeterminationService, ThresholdCandidateEvaluator
from intake.service import DeterministicIntakeEvaluator, IdeaIntakeService


class IntakeDeterminationFlowTests(unittest.TestCase):
    def test_selected_candidate_flows_through_intake_and_visible_determination(self):
        with tempfile.TemporaryDirectory() as directory:
            database = Database(Path(directory) / "content.db")
            database.initialize()
            created_at = "2026-01-01T00:00:00+00:00"
            run_id = database.start_detection_run(created_at)
            candidate_id = database.upsert_candidate(
                TrendCandidate("break the ice", 0.8, "EMERGING", {"momentum": 0.8}, ["rss"]),
                created_at,
            )
            snapshot = {
                "candidate": {"candidate_id": candidate_id, "topic": "break the ice", "score": 0.8},
                "evidence": [{"source": "rss", "url": "https://example.test/break-the-ice"}],
                "history": [],
            }
            intake_id = database.create_trend_intake_if_absent(candidate_id, run_id, snapshot, created_at)
            duplicate = database.create_trend_intake_if_absent(candidate_id, run_id, snapshot, created_at)

            determination_request_id = IdeaIntakeService(DeterministicIntakeEvaluator()).consume_next_request(database)
            decision_id = DeterminationService(
                evaluator=ThresholdCandidateEvaluator(0.25)
            ).consume_next_request(database)
            revision = database.connection.execute("SELECT * FROM brief_revisions").fetchone()
            request = database.connection.execute("SELECT * FROM determination_requests").fetchone()
            decision = database.connection.execute("SELECT * FROM determination_decisions").fetchone()
            routes = database.connection.execute(
                "SELECT * FROM determination_routes WHERE decision_id = ? ORDER BY pipeline_id", (decision_id,)
            ).fetchall()
            job = database.connection.execute("SELECT * FROM content_jobs").fetchone()
            html = render_dashboard(database)
            database.close()

        self.assertIsNotNone(intake_id)
        self.assertIsNone(duplicate)
        self.assertIsNotNone(determination_request_id)
        self.assertEqual(request["determination_request_id"], determination_request_id)
        self.assertEqual(revision["revision_id"], request["revision_id"])
        self.assertEqual(decision["decision_id"], decision_id)
        self.assertEqual(decision["status"], "accepted")
        self.assertEqual(len(routes), 5)
        self.assertEqual([route["disposition"] for route in routes].count("selected"), 1)
        self.assertEqual(job["determination_request_id"], determination_request_id)
        self.assertEqual(json.loads(revision["brief_json"])["topic"], "break the ice")
        self.assertIn("Frozen Brief Revisions", html)
        self.assertIn("Five-domain Route Assessments", html)
        self.assertIn("break the ice", html)

    def test_not_recommended_request_persists_all_route_stopping_reasons(self):
        with tempfile.TemporaryDirectory() as directory:
            database = Database(Path(directory) / "content.db")
            database.initialize()
            candidate_id = database.upsert_candidate(
                TrendCandidate("quiet topic", 0.1, "EMERGING"), "2026-01-01T00:00:00+00:00"
            )
            run_id = database.start_detection_run("2026-01-01T00:00:00+00:00")
            database.create_trend_intake_if_absent(candidate_id, run_id, {
                "candidate": {"candidate_id": candidate_id, "topic": "quiet topic", "score": 0.1},
                "evidence": [], "history": [],
            }, "2026-01-01T00:00:00+00:00")
            IdeaIntakeService().consume_next_request(database)
            DeterminationService(evaluator=ThresholdCandidateEvaluator(0.25)).consume_next_request(database)
            decision = database.connection.execute("SELECT * FROM determination_decisions").fetchone()
            route_count = database.connection.execute(
                "SELECT COUNT(*) AS count FROM determination_routes WHERE decision_id = ?", (decision["decision_id"],)
            ).fetchone()["count"]
            job_count = database.connection.execute("SELECT COUNT(*) AS count FROM content_jobs").fetchone()["count"]
            database.close()

        self.assertEqual(decision["status"], "not_recommended")
        self.assertEqual(route_count, 5)
        self.assertEqual(job_count, 0)
