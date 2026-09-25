"""Adaptation checkpoints; offline tests use temporary databases and fake providers."""

from __future__ import annotations
from common.gemini import GeminiUsage
from copy import deepcopy
from visual_fixtures import EXPRESSION_UNITS
from pathlib import Path
from workflow import GeminiAdaptationWorker, WorkflowStore
import delivery_fixtures
import json
import unittest


ROOT = Path(__file__).resolve().parents[1]


class FakeGeminiClient:
    model = "fake-gemini"

    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []
        self.last_usage = GeminiUsage(10, 5, 15, self.model)

    def generate_json(self, prompt, schema, *, temperature):
        self.calls.append({"prompt": prompt, "schema": schema, "temperature": temperature})
        return deepcopy(self.responses.pop(0))


class AdaptationCheckpointTests(delivery_fixtures.DeliveryFixture, unittest.TestCase):
    def test_delivery_adaptation_repairs_only_metadata_from_checkpointed_body(self):
        first = {
            "caption_summary": "A focused practical lesson.", "cta": None,
            "visual_units": deepcopy(EXPRESSION_UNITS),
            "visual_cues": [],
            "public_text_claim_ids": [], "private_tags": ["duplicate", "duplicate"],
            "hashtags": [], "alt_text": "A simple lesson card.",
        }
        first['visual_units'][1]['title'] = 'Ease the first moment'
        first['visual_units'][2]['title'] = 'A room waiting to talk'
        metadata = {
            "private_tags": ["education", "language"], "hashtags": [],
            "alt_text": "A lesson card explaining how to ease an awkward first meeting.",
        }
        from claim_fixtures import line_response
        line_response(first)
        client = FakeGeminiClient([first, metadata])
        with WorkflowStore(self.path, catalog_kind="production") as store:
            self.configure(store, platforms=("instagram",))
            run_id = self.create_review(store, "instagram", stop_at_adaptation=True)
            package_id = GeminiAdaptationWorker(store, client, production=True).run_once()
            self.assertIsNotNone(package_id)
            run = store.connection.execute(
                "SELECT status,adapted_body_json,metadata_json FROM adaptation_runs "
                "WHERE adaptation_run_id=?", (run_id,),
            ).fetchone()
            self.assertEqual(run["status"], "succeeded")
            self.assertEqual(json.loads(run["adapted_body_json"])["caption_summary"], first["caption_summary"])
            self.assertEqual(json.loads(run["metadata_json"]), metadata)
            invocations = store.connection.execute(
                "SELECT prompt_version,outcome FROM model_invocations ORDER BY model_invocation_id"
            ).fetchall()
            self.assertEqual([row["outcome"] for row in invocations], ["schema_failed", "succeeded"])
            self.assertIn("metadata_retry", invocations[1]["prompt_version"])
            self.assertEqual(len(client.calls), 2)
