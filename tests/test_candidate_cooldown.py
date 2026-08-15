import tempfile
import unittest
from pathlib import Path

from common.models import TrendCandidate
from database.sqlite import Database


class CandidateCooldownTests(unittest.TestCase):
    def test_candidate_is_eligible_then_hidden_during_cooldown(self):
        with tempfile.TemporaryDirectory() as directory:
            database = Database(Path(directory) / "content.db")
            database.initialize()
            candidate_id = database.upsert_candidate(TrendCandidate("topic", 0.8, "EMERGING"), "2026-01-01T00:00:00+00:00")
            self.assertEqual(len(database.eligible_candidates("2026-01-01T00:00:00+00:00")), 1)
            database.set_candidate_cooldown(candidate_id, "2026-01-02T00:00:00+00:00")
            self.assertEqual(len(database.eligible_candidates("2026-01-01T12:00:00+00:00")), 0)
            self.assertEqual(len(database.eligible_candidates("2026-01-03T00:00:00+00:00")), 1)
            database.close()
