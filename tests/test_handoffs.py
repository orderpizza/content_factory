import json
import tempfile
import unittest
from pathlib import Path

from common.models import TrendCandidate
from database.sqlite import Database


class HandoffTests(unittest.TestCase):
    def test_handoff_is_persisted_with_frozen_payload_and_deduplicated(self):
        with tempfile.TemporaryDirectory() as directory:
            database = Database(Path(directory) / "content.db")
            database.initialize()
            run_id = database.start_detection_run("2026-01-01T00:00:00+00:00")
            candidate_id = database.upsert_candidate(TrendCandidate("topic", 0.8, "EMERGING"), "2026-01-01T00:00:00+00:00")
            payload = {"candidate": {"topic": "topic"}, "evidence": [{"url": "https://example.test"}], "status": "pending"}
            first = database.create_handoff_if_absent(candidate_id, run_id, payload, "2026-01-01T00:00:00+00:00")
            duplicate = database.create_handoff_if_absent(candidate_id, run_id, payload, "2026-01-01T00:30:00+00:00")
            row = database.pending_handoffs()[0]
            database.close()

        self.assertIsNotNone(first)
        self.assertIsNone(duplicate)
        self.assertEqual(json.loads(row["payload_json"])["candidate"]["topic"], "topic")

    def test_handoff_claim_is_atomic(self):
        with tempfile.TemporaryDirectory() as directory:
            database = Database(Path(directory) / "content.db")
            database.initialize()
            run_id = database.start_detection_run("2026-01-01T00:00:00+00:00")
            candidate_id = database.upsert_candidate(TrendCandidate("topic", 0.8, "EMERGING"), "2026-01-01T00:00:00+00:00")
            handoff_id = database.create_handoff_if_absent(candidate_id, run_id, {}, "2026-01-01T00:00:00+00:00")
            first = database.claim_handoff(handoff_id, "2026-01-01T01:00:00+00:00")
            second = database.claim_handoff(handoff_id, "2026-01-01T01:00:01+00:00")
            database.complete_handoff(handoff_id, "2026-01-01T02:00:00+00:00")
            status = database.connection.execute("SELECT status FROM determination_handoffs WHERE handoff_id = ?", (handoff_id,)).fetchone()["status"]
            database.close()

        self.assertTrue(first)
        self.assertFalse(second)
        self.assertEqual(status, "completed")
