import tempfile
import unittest
from pathlib import Path

from common.models import TopicSnapshot
from database.sqlite import Database


class ScoutHealthTests(unittest.TestCase):
    def test_source_health_is_persisted(self):
        with tempfile.TemporaryDirectory() as directory:
            database = Database(Path(directory) / "content.db")
            database.initialize()
            health_id = database.save_source_health("fixture", "2026-01-01T00:00:00+00:00", False, 3, "timeout")
            row = database.connection.execute("SELECT * FROM source_health WHERE id = ?", (health_id,)).fetchone()
            database.close()

        self.assertEqual(row["source"], "fixture")
        self.assertEqual(row["success"], 0)
        self.assertEqual(row["attempts"], 3)
        self.assertEqual(row["error"], "timeout")
