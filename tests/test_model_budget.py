"""Model budget; offline tests use temporary databases and fake providers."""

from __future__ import annotations
from database.current import initialize_database
from decimal import Decimal
from detection.configuration import load_manifest
from detection.store import DetectionStore
from pathlib import Path
from test_gemini_workflow import FakeGeminiClient
from types import SimpleNamespace
from workflow import GeminiIntakeWorker, ModelBudgetPolicy, WorkflowStore
from workflow.store import now
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]


MANIFEST = ROOT / "config" / "releases" / "detection.json"


class ModelBudgetTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.path = Path(self.temporary.name) / "development.db"
        initialize_database(self.path)
        with DetectionStore(self.path) as store:
            store.apply_manifest(load_manifest(MANIFEST))

    def test_model_budget_is_reserved_before_call_and_settled_from_usage(self):
        policy = ModelBudgetPolicy(
            "fixture-model", Decimal("1"), Decimal("2"), 500_000, 1_000_000,
            1_000_000, {"intake": (100, 50), "determination": (100, 50),
                        "generation": (100, 50), "adaptation": (100, 50)},
        )
        with WorkflowStore(self.path, model_budget_policy=policy) as store:
            store.create_human_idea("A complete idea for admission.", command_id="budget")
            claim = store.claim("intake_requests", "intake_request_id", "budget-test")
            invocation = store.begin_model_invocation(
                phase="intake", table="intake_requests", key="intake_request_id", row=claim,
                request_version="fixture", prompt_version="fixture", schema_version="fixture",
                request_value={"safe": True}, model_id="fixture-model",
            )
            reservation = store.connection.execute(
                "SELECT status,worst_case_micro_usd,price_snapshot_hash FROM gemini_budget_reservations "
                "WHERE model_invocation_id=?", (invocation,),
            ).fetchone()
            self.assertEqual((reservation["status"], reservation["worst_case_micro_usd"]),
                             ("reserved", 200))
            self.assertEqual(reservation["price_snapshot_hash"], policy.fingerprint)
            store.finish_model_invocation(
                invocation, outcome="succeeded",
                usage=SimpleNamespace(input_tokens=10, output_tokens=5, total_tokens=15,
                                      model="fixture-model"),
                response_value={"ok": True},
            )
            settled = store.connection.execute(
                "SELECT status,settled_micro_usd FROM gemini_budget_reservations "
                "WHERE model_invocation_id=?", (invocation,),
            ).fetchone()
            self.assertEqual((settled["status"], settled["settled_micro_usd"]), ("settled", 20))

    def test_daily_model_budget_refusal_is_audited_and_deferred_without_a_call(self):
        policy = ModelBudgetPolicy(
            "fixture-model", Decimal("1"), Decimal("2"), 50, 100, 1_000,
            {"intake": (100, 50), "determination": (100, 50),
             "generation": (100, 50), "adaptation": (100, 50)},
        )
        client = FakeGeminiClient({
            "editorial_goal": "Teach a phrase.", "topic": "break the ice",
            "coverage_kind": "language_subject", "canonical_target": "break the ice",
            "revision_scope": "whole_brief", "audience": "learners",
            "desired_outcome": "teach", "constraints": {},
            "source_context": "A local idea.", "open_questions": [],
        })
        with WorkflowStore(self.path, model_budget_policy=policy) as store:
            request_id = store.create_human_idea(
                "Teach break the ice.", command_id="budget-block",
            )
            self.assertIsNone(GeminiIntakeWorker(store, client).run_once())
            request = store.connection.execute(
                "SELECT status,next_attempt_at,failure_detail FROM intake_requests "
                "WHERE intake_request_id=?", (request_id,),
            ).fetchone()
            self.assertEqual(request["status"], "retry_wait")
            self.assertIn("daily Gemini hard limit", request["failure_detail"])
            self.assertGreater(request["next_attempt_at"], now())
            self.assertEqual(client.calls, [])
            self.assertEqual(store.connection.execute(
                "SELECT outcome FROM model_invocations"
            ).fetchone()[0], "blocked")
