import gzip
import json
import tempfile
import unittest
from pathlib import Path

from database.sqlite import Database
from intelligence.sources import Observation


class RetentionTests(unittest.TestCase):
    def test_archives_summarizes_and_removes_old_observations(self):
        with tempfile.TemporaryDirectory() as directory:
            database = Database(Path(directory) / "content.db")
            database.initialize()
            database.save_observation(Observation("topic", "Headline", "rss", 10, 5, "https://example.test", {"x": 1}, "item-1"), "2025-01-02T00:00:00+00:00")
            database.save_observation(Observation("topic", "Headline 2", "rss", 20, 5, "https://example.test/2", {}, "item-2"), "2025-01-03T00:00:00+00:00")
            counts = database.archive_and_cleanup("2025-02-01T00:00:00+00:00", Path(directory) / "archive")
            remaining = database.connection.execute("SELECT COUNT(*) AS count FROM trend_observations").fetchone()["count"]
            summary = database.connection.execute("SELECT * FROM trend_history").fetchone()
            archive = next((Path(directory) / "archive").glob("*.jsonl.gz"))
            with gzip.open(archive, "rt", encoding="utf-8") as handle:
                archived = [json.loads(line) for line in handle]
            database.close()

        self.assertEqual(counts["trend_observations"], 2)
        self.assertEqual(remaining, 0)
        self.assertEqual(summary["observation_count"], 2)
        self.assertEqual(len(archived), 2)
