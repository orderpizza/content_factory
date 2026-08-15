import unittest

from intelligence.scoring import TopicSnapshot, TrendScorer


class TrendScorerTests(unittest.TestCase):
    def test_scores_growth_and_explains_sources(self):
        candidate = TrendScorer().score("topic", [
            TopicSnapshot("topic", "rss", 10, "2026-01-01T00:00:00+00:00"),
            TopicSnapshot("topic", "wikimedia", 20, "2026-01-02T00:00:00+00:00"),
            TopicSnapshot("topic", "rss", 40, "2026-01-03T00:00:00+00:00"),
        ])

        self.assertEqual(candidate.lifecycle_stage, "EMERGING")
        self.assertGreater(candidate.score, 0.5)
        self.assertEqual(candidate.supporting_sources, ["rss", "wikimedia"])
        self.assertIn("velocity", candidate.score_breakdown)

    def test_new_topic_is_marked_new(self):
        candidate = TrendScorer().score("topic", [TopicSnapshot("topic", "rss", 10, "2026-01-01T00:00:00+00:00")])

        self.assertEqual(candidate.lifecycle_stage, "NEW")
