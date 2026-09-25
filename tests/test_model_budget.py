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
from workflow.model_budget import DEFAULT_PHASE_LIMITS, MAX_TEXT_OUTPUT_TOKENS, TEXT_PHASES
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

    def test_generation_default_reserves_calibrated_six_thousand_output_tokens(self):
        self.assertEqual(DEFAULT_PHASE_LIMITS["generation"], (12_000, 6_000))
        environment = {
            "GEMINI_INPUT_COST_PER_MILLION_USD": "1",
            "GEMINI_OUTPUT_COST_PER_MILLION_USD": "2",
            "GEMINI_DAILY_WARNING_USD": "5",
            "GEMINI_DAILY_HARD_LIMIT_USD": "10",
            "GEMINI_JOB_HARD_LIMIT_USD": "2",
        }
        policy = ModelBudgetPolicy.from_environment("fixture-model", environment)
        self.assertEqual(policy.reservation_estimate("generation"), (12_000, 6_000, 24_000))

    def test_text_stage_defaults_remain_calibrated_and_within_global_ceiling(self):
        self.assertEqual(
            {phase: DEFAULT_PHASE_LIMITS[phase][1] for phase in TEXT_PHASES},
            {
                "intake": 2_000,
                "determination": 4_000,
                "editorial_planning": 4_000,
                "generation": 6_000,
                "adaptation": 8_000,
            },
        )
        self.assertTrue(all(
            1 <= DEFAULT_PHASE_LIMITS[phase][1] <= MAX_TEXT_OUTPUT_TOKENS
            for phase in TEXT_PHASES
        ))
        self.assertTrue(all(
            1 <= limits[1] <= MAX_TEXT_OUTPUT_TOKENS
            for limits in DEFAULT_PHASE_LIMITS.values()
        ))

    def test_text_stage_output_limit_at_global_ceiling_is_admitted(self):
        environment = {
            "GEMINI_INPUT_COST_PER_MILLION_USD": "1",
            "GEMINI_OUTPUT_COST_PER_MILLION_USD": "2",
            "GEMINI_DAILY_WARNING_USD": "5",
            "GEMINI_DAILY_HARD_LIMIT_USD": "10",
            "GEMINI_JOB_HARD_LIMIT_USD": "2",
            "GEMINI_GENERATION_MAX_OUTPUT_TOKENS": str(MAX_TEXT_OUTPUT_TOKENS),
        }
        policy = ModelBudgetPolicy.from_environment("fixture-model", environment)
        self.assertEqual(policy.phase_limits["generation"], (12_000, MAX_TEXT_OUTPUT_TOKENS))
        self.assertEqual(policy.reservation_estimate("generation")[1], MAX_TEXT_OUTPUT_TOKENS)

    def test_reservation_uses_configured_stage_allowance_not_global_ceiling(self):
        environment = {
            "GEMINI_INPUT_COST_PER_MILLION_USD": "1",
            "GEMINI_OUTPUT_COST_PER_MILLION_USD": "2",
            "GEMINI_DAILY_WARNING_USD": "5",
            "GEMINI_DAILY_HARD_LIMIT_USD": "10",
            "GEMINI_JOB_HARD_LIMIT_USD": "2",
            "GEMINI_GENERATION_MAX_OUTPUT_TOKENS": "7000",
        }
        policy = ModelBudgetPolicy.from_environment("fixture-model", environment)
        self.assertEqual(policy.reservation_estimate("generation"), (12_000, 7_000, 26_000))

    def test_text_stage_output_limit_over_global_ceiling_is_rejected_before_client_use(self):
        environment = {
            "GEMINI_INPUT_COST_PER_MILLION_USD": "1",
            "GEMINI_OUTPUT_COST_PER_MILLION_USD": "2",
            "GEMINI_DAILY_WARNING_USD": "5",
            "GEMINI_DAILY_HARD_LIMIT_USD": "10",
            "GEMINI_JOB_HARD_LIMIT_USD": "2",
            "GEMINI_ADAPTATION_MAX_OUTPUT_TOKENS": str(MAX_TEXT_OUTPUT_TOKENS + 1),
        }
        client = FakeGeminiClient({})
        with self.assertRaisesRegex(ValueError, "cannot exceed"):
            ModelBudgetPolicy.from_environment("fixture-model", environment)
        self.assertEqual(client.calls, [])

    def test_nonpositive_text_stage_output_limits_remain_rejected(self):
        base = {
            "GEMINI_INPUT_COST_PER_MILLION_USD": "1",
            "GEMINI_OUTPUT_COST_PER_MILLION_USD": "2",
            "GEMINI_DAILY_WARNING_USD": "5",
            "GEMINI_DAILY_HARD_LIMIT_USD": "10",
            "GEMINI_JOB_HARD_LIMIT_USD": "2",
        }
        for value in ("0", "-1"):
            with self.subTest(value=value), self.assertRaisesRegex(ValueError, "must be positive"):
                ModelBudgetPolicy.from_environment(
                    "fixture-model", {**base, "GEMINI_INTAKE_MAX_OUTPUT_TOKENS": value}
                )

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

    def test_reserved_input_preferred_name_and_legacy_alias(self):
        env = {"GEMINI_INPUT_COST_PER_MILLION_USD": "1", "GEMINI_OUTPUT_COST_PER_MILLION_USD": "2",
               "GEMINI_DAILY_WARNING_USD": "5", "GEMINI_DAILY_HARD_LIMIT_USD": "10",
               "GEMINI_JOB_HARD_LIMIT_USD": "2", "GEMINI_INTAKE_MAX_INPUT_TOKENS": "123"}
        old = ModelBudgetPolicy.from_environment("fixture-model", env)
        preferred = ModelBudgetPolicy.from_environment("fixture-model", {
            **env, "GEMINI_INTAKE_RESERVED_INPUT_TOKENS": "456"})
        self.assertEqual(old.reservation_estimate("intake")[0],123)
        self.assertEqual(preferred.reservation_estimate("intake")[0],456)
        with self.assertRaises(ValueError):
            ModelBudgetPolicy.from_environment("fixture-model", {**env, "GEMINI_INTAKE_RESERVED_INPUT_TOKENS":"0"})

    def test_actual_input_over_reservation_is_accounted_in_full(self):
        policy = ModelBudgetPolicy("fixture-model",Decimal("1"),Decimal("2"),500_000,1_000_000,
                                  1_000_000,{"intake":(1,50)})
        with WorkflowStore(self.path,model_budget_policy=policy) as store:
            store.create_human_idea("A complete idea.",command_id="input-reservation")
            claim=store.claim("intake_requests","intake_request_id","test")
            invocation=store.begin_model_invocation(phase="intake",table="intake_requests",key="intake_request_id",
                row=claim,request_version="fixture",prompt_version="fixture",schema_version="fixture",
                request_value={"copy":"Many words do not represent an exact tokenizer count."},model_id="fixture-model")
            store.finish_model_invocation(invocation,outcome="succeeded",
                usage=SimpleNamespace(input_tokens=200,output_tokens=5,total_tokens=205,model="fixture-model"))
            row=store.connection.execute("SELECT max_input_tokens,worst_case_micro_usd,settled_micro_usd FROM gemini_budget_reservations").fetchone()
            self.assertEqual(tuple(row),(1,101,210))

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
