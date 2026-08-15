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

    def test_candidate_can_be_claimed_once(self):
        with tempfile.TemporaryDirectory() as directory:
            database = Database(Path(directory) / "content.db")
            database.initialize()
            candidate_id = database.upsert_candidate(TrendCandidate("topic", 0.8, "EMERGING"), "2026-01-01T00:00:00+00:00")
            self.assertTrue(database.claim_candidate(candidate_id, "2026-01-01T01:00:00+00:00", "2026-01-02T01:00:00+00:00"))
            self.assertFalse(database.claim_candidate(candidate_id, "2026-01-01T01:00:01+00:00", "2026-01-02T01:00:01+00:00"))
            database.close()
