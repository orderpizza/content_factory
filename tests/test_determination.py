import unittest
import json
import tempfile
from pathlib import Path

from common.models import Trend, TrendCandidate
from database.sqlite import Database
from determination.service import DeterminationService


class DeterminationTests(unittest.TestCase):
    def setUp(self):
        self.service = DeterminationService(minimum_score=0.25)

    def test_promising_trend_becomes_content_job(self):
        trend = Trend("topic", "A useful topic", "fixture", score=0.8, id=12)

        job = self.service.determine(trend)

        self.assertIsNotNone(job)
        self.assertEqual(job.trend_id, 12)
        self.assertEqual(job.pipeline_id, "o2_english_instagram")
        self.assertEqual(job.target_platform, "instagram")
        self.assertEqual(job.target_account, "o2_english")
        self.assertEqual(job.topic, "topic")
        self.assertEqual(job.status, "pending")

    def test_low_scoring_trend_is_rejected(self):
        trend = Trend("topic", "A quiet topic", "fixture", score=0.1, id=12)

        self.assertIsNone(self.service.determine(trend))

    def test_unpersisted_trend_cannot_create_job(self):
        trend = Trend("topic", "A topic", "fixture", score=0.8)

        with self.assertRaises(ValueError):
            self.service.determine(trend)

    def test_claimed_handoff_becomes_persisted_recipe_and_job(self):
        with tempfile.TemporaryDirectory() as directory:
            database = Database(Path(directory) / "content.db")
            database.initialize()
            run_id = database.start_detection_run("2026-01-01T00:00:00+00:00")
            candidate_id = database.upsert_candidate(TrendCandidate("topic", 0.8, "EMERGING"), "2026-01-01T00:00:00+00:00")
            handoff_id = database.create_handoff_if_absent(candidate_id, run_id, {
                "candidate": {"candidate_id": candidate_id, "topic": "topic", "score": 0.8},
                "evidence": [{"url": "https://example.test/topic"}],
            }, "2026-01-01T00:00:00+00:00")

            job = self.service.consume_next_handoff(database)
            decision = database.connection.execute("SELECT * FROM determination_decisions WHERE handoff_id = ?", (handoff_id,)).fetchone()
            handoff = database.connection.execute("SELECT status FROM determination_handoffs WHERE handoff_id = ?", (handoff_id,)).fetchone()
            database.close()

        self.assertEqual(job.pipeline_id, "o2_english_instagram")
        self.assertEqual(job.target_platform, "instagram")
        self.assertEqual(job.determination_handoff_id, handoff_id)
        self.assertEqual(decision["status"], "accepted")
        self.assertEqual(json.loads(decision["recipe_json"])["content_format"], "instagram_idiom_carousel")
        self.assertEqual(handoff["status"], "completed")
