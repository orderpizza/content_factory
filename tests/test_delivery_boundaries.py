"""Delivery boundaries; offline tests use temporary databases and fake providers."""

from __future__ import annotations
from common.gemini import GeminiUsage
from copy import deepcopy
from database.current import connect, initialize_database, validate_database
from datetime import timedelta
from pathlib import Path
from workflow import WorkflowStore
from workflow.delivery import CredentialedPostingAgent, DeliveryError
import delivery_fixtures
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


class FakeDeliveryAdapter:
    def __init__(self, *, fail_final: bool = False):
        self.fail_final = fail_final
        self.staged = []
        self.published = []

    def stage(self, context, record):
        self.staged.append(deepcopy(context))
        record(resource_type="external_media", remote_id="778899", asset_ordinal=1,
               status="ready", safe_metadata={})
        return {"media_id": "778899"}

    def publish(self, context, staged):
        self.published.append((deepcopy(context), deepcopy(staged)))
        if self.fail_final:
            raise DeliveryError("transport", "response was lost", True, "publish")
        return "1122334455"


class DeliveryBoundaryTests(delivery_fixtures.DeliveryFixture, unittest.TestCase):
    def test_schema_preserves_delivery_records_and_initialization_is_idempotent(self):
        self.assertFalse(initialize_database(self.path))
        with connect(self.path) as connection:
            validate_database(connection)
            self.assertEqual(connection.execute("PRAGMA user_version").fetchone()[0], 13)
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM schema_migrations").fetchone()[0], 1)
            self.assertEqual(connection.execute("PRAGMA foreign_key_check").fetchall(), [])

    def test_delivery_catalog_is_blocked_until_readiness_is_current(self):
        with WorkflowStore(self.path, catalog_kind="production") as store:
            store.register_production_configuration(self.configuration())
            self.assertFalse(any(output["ready"] for item in store.catalog() for output in item["outputs"]))
            for row in store.connection.execute("SELECT social_destination_id FROM social_destinations"):
                store.record_destination_readiness(
                    row[0], status="ready", reasons=[], facts={"fixture": True},
                    valid_for=timedelta(days=1),
                )
            catalog = store.catalog()
            self.assertEqual(len(catalog), 3)
            self.assertTrue(all(len(item["outputs"]) == 1 for item in catalog))
            self.assertTrue(all(output["ready"] for item in catalog for output in item["outputs"]))

    def test_post_now_revalidates_exact_assets_and_can_cancel_pre_final(self):
        with WorkflowStore(self.path, catalog_kind="production") as store:
            self.configure(
                store, platforms=("instagram",), max_posts_per_day=2,
                min_post_interval_minutes=0,
            )
            review_id = self.create_review(store, "instagram")
            version = store.connection.execute(
                "SELECT row_version FROM review_requests WHERE review_request_id=?", (review_id,),
            ).fetchone()[0]
            record_id = store.authorize_post_now(review_id, row_version=version, command_id="post-x")
            self.assertEqual(record_id, store.authorize_post_now(
                review_id, row_version=version, command_id="post-x"
            ))
            record = store.connection.execute(
                "SELECT * FROM post_records WHERE post_record_id=?", (record_id,),
            ).fetchone()
            self.assertEqual(record["status"], "pending")
            store.cancel_delivery(record_id, row_version=record["row_version"], command_id="cancel-x")
            self.assertEqual(store.connection.execute(
                "SELECT status FROM post_records WHERE post_record_id=?", (record_id,),
            ).fetchone()[0], "cancelled")

    def test_post_now_refuses_tampered_reviewed_asset(self):
        with WorkflowStore(self.path, catalog_kind="production") as store:
            self.configure(store, platforms=("instagram",))
            review_id = self.create_review(store, "instagram")
            asset = store.connection.execute(
                "SELECT local_path FROM render_assets WHERE asset_role='delivery_jpeg'"
            ).fetchone()[0]
            Path(asset).write_bytes(b"tampered")
            version = store.connection.execute(
                "SELECT row_version FROM review_requests WHERE review_request_id=?", (review_id,),
            ).fetchone()[0]
            with self.assertRaisesRegex(ValueError, "hash|size"):
                store.authorize_post_now(review_id, row_version=version, command_id="tampered")
            self.assertEqual(store.connection.execute("SELECT COUNT(*) FROM post_requests").fetchone()[0], 0)

    def test_posting_success_and_ambiguous_final_failure_are_distinct(self):
        with WorkflowStore(self.path, catalog_kind="production") as store:
            self.configure(
                store, platforms=("instagram",), max_posts_per_day=2,
                min_post_interval_minutes=0,
            )
            first = self.create_review(store, "instagram")
            version = store.connection.execute(
                "SELECT row_version FROM review_requests WHERE review_request_id=?", (first,),
            ).fetchone()[0]
            first_record = store.authorize_post_now(first, row_version=version, command_id="publish")
            success = FakeDeliveryAdapter()
            self.assertEqual(CredentialedPostingAgent(store, adapters={"instagram": success}).run_once(), first_record)
            published = store.connection.execute(
                "SELECT status,external_post_id FROM post_records WHERE post_record_id=?", (first_record,),
            ).fetchone()
            self.assertEqual((published["status"], published["external_post_id"]),
                             ("published", "1122334455"))
            self.assertEqual(len(success.published), 1)

            second = self.create_review(store, "instagram")
            version = store.connection.execute(
                "SELECT row_version FROM review_requests WHERE review_request_id=?", (second,),
            ).fetchone()[0]
            second_record = store.authorize_post_now(second, row_version=version, command_id="unknown")
            failure = FakeDeliveryAdapter(fail_final=True)
            self.assertEqual(CredentialedPostingAgent(store, adapters={"instagram": failure}).run_once(), second_record)
            self.assertEqual(store.connection.execute(
                "SELECT status FROM post_records WHERE post_record_id=?", (second_record,),
            ).fetchone()[0], "publication_unknown")
            self.assertEqual(store.connection.execute(
                "SELECT COUNT(*) FROM reconciliation_requests WHERE post_record_id=?", (second_record,),
            ).fetchone()[0], 0)
            reconciliation_id = store.request_publication_reconciliation(
                second_record, command_id="reconcile-unknown",
            )
            self.assertGreater(reconciliation_id, 0)
            self.assertIsNone(CredentialedPostingAgent(store, adapters={"instagram": failure}).run_once())
            self.assertEqual(len(failure.published), 1)

    def test_committed_final_marker_blocks_cancel_and_requires_human_reconciliation(self):
        with WorkflowStore(self.path, catalog_kind="production") as store:
            self.configure(store, platforms=("instagram",), min_post_interval_minutes=0)
            review_id = self.create_review(store, "instagram")
            version = store.connection.execute(
                "SELECT row_version FROM review_requests WHERE review_request_id=?", (review_id,),
            ).fetchone()[0]
            record_id = store.authorize_post_now(
                review_id, row_version=version, command_id="marker-post",
            )
            record = store.claim("post_records", "post_record_id", "marker-worker")
            context = store.prepare_post_attempt(record)
            store.mark_attempt_ready(context["post_attempt_id"])
            store.mark_final_publication_request(context)
            current_version = store.connection.execute(
                "SELECT row_version FROM post_records WHERE post_record_id=?", (record_id,),
            ).fetchone()[0]
            with self.assertRaisesRegex(ValueError, "reconcile"):
                store.cancel_delivery(
                    record_id, row_version=current_version, command_id="too-late-cancel",
                )
            store.fail_post_attempt(
                context, category="transport", detail="response lost", retryable=True,
                after_final_marker=True,
            )
            reconciliation_id = store.request_publication_reconciliation(
                record_id, command_id="marker-reconcile",
            )
            request = store.claim(
                "reconciliation_requests", "reconciliation_request_id", "reconcile-worker",
            )
            check_id = store.record_reconciliation_check(
                request, outcome="confirmed_not_published", query_version="fixture",
                evidence={"fixture": True},
            )
            current = store.connection.execute(
                "SELECT row_version FROM reconciliation_requests "
                "WHERE reconciliation_request_id=?", (reconciliation_id,),
            ).fetchone()[0]
            store.resolve_publication_unknown(
                reconciliation_id, reconciliation_check_id=check_id,
                decision="leave_unknown", note="Provider evidence is still inconclusive.",
                row_version=current, command_id="leave-unknown",
            )
            self.assertEqual(store.connection.execute(
                "SELECT status FROM reconciliation_requests WHERE reconciliation_request_id=?",
                (reconciliation_id,),
            ).fetchone()[0], "resolved")
            self.assertEqual(store.connection.execute(
                "SELECT status FROM post_records WHERE post_record_id=?", (record_id,),
            ).fetchone()[0], "publication_unknown")

    def test_final_marker_rechecks_destination_readiness_and_live_lease(self):
        with WorkflowStore(self.path, catalog_kind="production") as store:
            self.configure(
                store, platforms=("instagram",), max_posts_per_day=2,
                min_post_interval_minutes=0,
            )
            review_id = self.create_review(store, "instagram")
            version = store.connection.execute(
                "SELECT row_version FROM review_requests WHERE review_request_id=?", (review_id,),
            ).fetchone()[0]
            store.authorize_post_now(review_id, row_version=version, command_id="stale-ready")
            record = store.claim("post_records", "post_record_id", "stale-ready-worker")
            context = store.prepare_post_attempt(record)
            store.mark_attempt_ready(context["post_attempt_id"])
            with store.transaction():
                store.connection.execute(
                    "UPDATE capability_readiness SET valid_until='2000-01-01T00:00:00'"
                )
            with self.assertRaisesRegex(RuntimeError, "readiness expired"):
                store.mark_final_publication_request(context)
            self.assertIsNone(store.connection.execute(
                "SELECT final_publication_request_sent_at FROM post_attempts WHERE post_attempt_id=?",
                (context["post_attempt_id"],),
            ).fetchone()[0])
            current_version = store.connection.execute(
                "SELECT row_version FROM post_records WHERE post_record_id=?",
                (context["post_record_id"],),
            ).fetchone()[0]
            store.cancel_delivery(
                context["post_record_id"], row_version=current_version,
                command_id="readiness-cancel-wins",
            )
            store.fail_post_attempt(
                context, category="final_marker", detail="readiness expired",
                retryable=False, after_final_marker=False,
            )
            self.assertEqual(store.connection.execute(
                "SELECT status FROM post_records WHERE post_record_id=?",
                (context["post_record_id"],),
            ).fetchone()[0], "cancelled")

            destination = store.connection.execute(
                "SELECT social_destination_id FROM social_destinations"
            ).fetchone()[0]
            store.record_destination_readiness(
                destination, status="ready", reasons=[], facts={"fixture": True},
                valid_for=timedelta(days=1),
            )
            second_review = self.create_review(store, "instagram")
            second_version = store.connection.execute(
                "SELECT row_version FROM review_requests WHERE review_request_id=?", (second_review,),
            ).fetchone()[0]
            store.authorize_post_now(
                second_review, row_version=second_version, command_id="stale-lease",
            )
            second = store.claim("post_records", "post_record_id", "stale-lease-worker")
            second_context = store.prepare_post_attempt(second)
            store.mark_attempt_ready(second_context["post_attempt_id"])
            with store.transaction():
                store.connection.execute(
                    "UPDATE post_records SET lease_expires_at='2000-01-01T00:00:00' "
                    "WHERE post_record_id=?", (second_context["post_record_id"],),
                )
            with self.assertRaisesRegex(RuntimeError, "claim is stale"):
                store.mark_final_publication_request(second_context)
            store.fail_post_attempt(
                second_context, category="final_marker", detail="lease expired",
                retryable=False, after_final_marker=False,
            )
            self.assertEqual(store.connection.execute(
                "SELECT status FROM post_records WHERE post_record_id=?",
                (second_context["post_record_id"],),
            ).fetchone()[0], "publishing")
            self.assertIsNone(store.connection.execute(
                "SELECT final_publication_request_sent_at FROM post_attempts WHERE post_attempt_id=?",
                (second_context["post_attempt_id"],),
            ).fetchone()[0])
            recovered = store.claim("post_records", "post_record_id", "recovery-worker")
            self.assertEqual(recovered["post_record_id"], second_context["post_record_id"])
            self.assertGreater(recovered["claim_version"], second_context["claim_version"])

    def test_missing_adapter_fails_before_final_marker_without_stranding_claim(self):
        with WorkflowStore(self.path, catalog_kind="production") as store:
            self.configure(store)
            review_id = self.create_review(store)
            version = store.connection.execute("SELECT row_version FROM review_requests WHERE review_request_id=?", (review_id,)).fetchone()[0]
            record_id = store.authorize_post_now(review_id, row_version=version, command_id="no-adapter")
            CredentialedPostingAgent(store).run_once()
            row = store.connection.execute("SELECT status FROM post_records WHERE post_record_id=?", (record_id,)).fetchone()
            self.assertEqual(row[0], "failed")
            attempt = store.connection.execute("SELECT final_publication_request_sent_at FROM post_attempts WHERE post_record_id=?", (record_id,)).fetchone()
            self.assertIsNone(attempt[0])

    def test_unavailable_reconciliation_preserves_unknown_and_cleanup_is_separate(self):
        from workflow.delivery import PublicationReconciliationWorker, R2CleanupWorker
        from unittest.mock import MagicMock
        with WorkflowStore(self.path, catalog_kind="production") as store:
            self.configure(store)
            review_id = self.create_review(store)
            version = store.connection.execute("SELECT row_version FROM review_requests WHERE review_request_id=?", (review_id,)).fetchone()[0]
            record_id = store.authorize_post_now(review_id, row_version=version, command_id="staged-unknown")
            class StagedAdapter(FakeDeliveryAdapter):
                def stage(self, context, record):
                    record(resource_type="r2_object", remote_id="fixture/staged.jpg", asset_ordinal=1,
                           status="ready", safe_metadata={})
                    return {}
            adapter = StagedAdapter(fail_final=True)
            CredentialedPostingAgent(store, adapters={"instagram": adapter}).run_once()
            store.request_publication_reconciliation(record_id, command_id="lookup")
            PublicationReconciliationWorker(store).run_once()
            self.assertEqual(store.connection.execute("SELECT outcome FROM reconciliation_checks").fetchone()[0], "provider_unavailable")
            relay = MagicMock()
            # The cleanup queue owns its due time independently of publication.
            store.connection.execute("UPDATE delivery_cleanup_tasks SET next_attempt_at='2000-01-01T00:00:00'")
            store.connection.commit()
            self.assertIsNotNone(R2CleanupWorker(store, relay_factory=lambda config: relay).run_once())
            relay.delete.assert_called_once_with("fixture/staged.jpg")
            self.assertEqual(store.connection.execute("SELECT status FROM post_records WHERE post_record_id=?", (record_id,)).fetchone()[0], "publication_unknown")
            self.assertEqual(len(adapter.published), 1)

    def test_expired_reconciliation_cannot_record_evidence_or_confirm_publication(self):
        with WorkflowStore(self.path, catalog_kind="production") as store:
            self.configure(store)
            review_id = self.create_review(store)
            version = store.connection.execute("SELECT row_version FROM review_requests WHERE review_request_id=?", (review_id,)).fetchone()[0]
            record_id = store.authorize_post_now(review_id, row_version=version, command_id="expired-reconciliation")
            CredentialedPostingAgent(store, adapters={"instagram": FakeDeliveryAdapter(fail_final=True)}).run_once()
            store.request_publication_reconciliation(record_id, command_id="stale-lookup")
            request = store.claim("reconciliation_requests", "reconciliation_request_id", "expired-worker")
            store.connection.execute("UPDATE reconciliation_requests SET lease_expires_at='2000-01-01T00:00:00'")
            store.connection.commit()
            with self.assertRaisesRegex(RuntimeError, "stale"):
                store.record_reconciliation_check(request, outcome="confirmed_published", query_version="fixture", evidence={"fixture": True})
            self.assertEqual(store.connection.execute("SELECT COUNT(*) FROM reconciliation_checks").fetchone()[0], 0)
            self.assertEqual(store.connection.execute("SELECT status FROM post_records WHERE post_record_id=?", (record_id,)).fetchone()[0], "publication_unknown")
