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

    def test_selected_candidate_is_available_to_determination(self):
        with tempfile.TemporaryDirectory() as directory:
            database = Database(Path(directory) / "content.db")
            database.initialize()
            database.upsert_candidate(TrendCandidate("selected", 0.8, "EMERGING"), "2026-01-01T00:00:00+00:00")
            database.upsert_candidate(TrendCandidate("other", 0.7, "RISING"), "2026-01-01T00:00:00+00:00")
            database.mark_candidates_for_determination(["selected"], "2026-01-01T01:00:00+00:00")
            rows = database.eligible_candidates("2026-01-01T02:00:00+00:00")
            database.close()

        self.assertEqual([row["topic"] for row in rows], ["selected", "other"])
        self.assertEqual(rows[0]["status"], "pending_determination")
