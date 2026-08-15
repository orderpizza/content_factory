import tempfile
import unittest
from pathlib import Path

from common.models import TopicSnapshot
from database.sqlite import Database
from intelligence.reporting import format_report, ranked_candidates


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
