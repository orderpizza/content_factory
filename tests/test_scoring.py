import unittest

from common.models import TopicSnapshot
from intelligence.scoring import TrendScorer


class TrendScorerTests(unittest.TestCase):
    def test_scores_growth_and_explains_sources(self):
        candidate = TrendScorer().score("topic", [
            TopicSnapshot("topic", "2026-01-01T00:00:00+00:00", 10, 1, 1, ["rss"]),
            TopicSnapshot("topic", "2026-01-02T00:00:00+00:00", 11, 1, 1, ["rss"]),
            TopicSnapshot("topic", "2026-01-03T00:00:00+00:00", 12, 1, 1, ["rss"]),
            TopicSnapshot("topic", "2026-01-04T00:00:00+00:00", 40, 2, 2, ["rss", "wikimedia"]),
        ])

        self.assertEqual(candidate.lifecycle_stage, "EMERGING")
        self.assertGreater(candidate.score, 0.5)
        self.assertEqual(candidate.supporting_sources, ["rss", "wikimedia"])
        self.assertIn("velocity", candidate.score_breakdown)
        self.assertIn("baseline_growth", candidate.score_breakdown)

    def test_new_topic_is_marked_new(self):
        candidate = TrendScorer().score("topic", [TopicSnapshot("topic", "2026-01-01T00:00:00+00:00", 10, 1, 1, ["rss"])])

        self.assertEqual(candidate.lifecycle_stage, "NEW")
