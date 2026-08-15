import unittest

from common.models import Trend
from determination.service import DeterminationService


class DeterminationTests(unittest.TestCase):
    def setUp(self):
        self.service = DeterminationService(minimum_score=0.25)

    def test_promising_trend_becomes_content_job(self):
        trend = Trend("topic", "A useful topic", "fixture", score=0.8, id=12)

        job = self.service.determine(trend)

        self.assertIsNotNone(job)
        self.assertEqual(job.trend_id, 12)
        self.assertEqual(job.pipeline_id, "poc_pipeline")
        self.assertEqual(job.topic, "topic")
        self.assertEqual(job.status, "pending")

    def test_low_scoring_trend_is_rejected(self):
        trend = Trend("topic", "A quiet topic", "fixture", score=0.1, id=12)

        self.assertIsNone(self.service.determine(trend))

    def test_unpersisted_trend_cannot_create_job(self):
        trend = Trend("topic", "A topic", "fixture", score=0.8)

        with self.assertRaises(ValueError):
            self.service.determine(trend)
