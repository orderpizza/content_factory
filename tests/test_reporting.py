import tempfile
import unittest
from pathlib import Path

from common.models import TopicSnapshot
from database.sqlite import Database
from intelligence.reporting import format_report, ranked_candidates, select_candidates


class ReportingTests(unittest.TestCase):
    def test_ranks_topics_and_formats_evidence(self):
        with tempfile.TemporaryDirectory() as directory:
            database = Database(Path(directory) / "content.db")
            database.initialize()
            database.save_topic_snapshot(TopicSnapshot("steady", "2026-01-01", 10, 1, 1, ["rss"]))
            database.save_topic_snapshot(TopicSnapshot("steady", "2026-01-02", 11, 1, 1, ["rss"]))
            database.save_topic_snapshot(TopicSnapshot("rising", "2026-01-01", 10, 1, 1, ["rss"]))
            database.save_topic_snapshot(TopicSnapshot("rising", "2026-01-02", 40, 2, 2, ["rss", "wikimedia"]))
            candidates = ranked_candidates(database)
            report = format_report(candidates)
            database.close()

        self.assertEqual(candidates[0].topic, "rising")
        self.assertIn("sources: rss, wikimedia", report)
        self.assertIn("velocity=", report)

    def test_selection_applies_score_threshold_and_top_n(self):
        with tempfile.TemporaryDirectory() as directory:
            database = Database(Path(directory) / "content.db")
            database.initialize()
            for topic, activity in (("low", 11), ("medium", 20), ("high", 80)):
                database.save_topic_snapshot(TopicSnapshot(topic, "2026-01-01", 10, 1, 1, ["rss"]))
                database.save_topic_snapshot(TopicSnapshot(topic, "2026-01-02", activity, 1, 1, ["rss"]))
            selected = select_candidates(database, minimum_score=0.30, top_n=1)
            database.close()

        self.assertEqual(len(selected), 1)
        self.assertEqual(selected[0].topic, "high")
