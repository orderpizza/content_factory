import tempfile
import unittest
from pathlib import Path

from common.models import ContentPackage, ContentJob, PostRecord, Trend
from database.sqlite import Database
from posting.agent import PostingAgent


class PostingAgentTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.database = Database(Path(self.temp_dir.name) / "content.db")
        self.database.initialize()
        trend_id = self.database.save_trend(Trend("topic", "Topic", "fixture"))
        self.job_id = self.database.save_content_job(ContentJob(
            trend_id, "o2_english_instagram", "topic", "angle", "English learners", "teach",
            target_platform="instagram", target_account="o2_english",
            content_format="instagram_idiom_carousel", visual_profile_id="o2_english_idiom_carousel_v1",
        ))
        self.content_id = self.database.save_content_package(ContentPackage(
            self.job_id, "o2_english_instagram", "Title", "Body", "Caption", platform="instagram",
            account="o2_english", content_format="instagram_idiom_carousel", hashtags=["#EnglishLearning"],
        ))
        self.database.mark_package_rendered_assets(
            self.content_id, [f"generated/slide-{index}.png" for index in range(1, 6)], required_asset_count=5,
        )

    def tearDown(self):
        self.database.close()
        self.temp_dir.cleanup()

    def test_queue_and_mark_published(self):
        agent = PostingAgent(self.database)
        post_id = agent.queue(PostRecord(self.content_id, "instagram", "o2_english"))

        agent.mark_published(post_id, "external-123")
        row = self.database.connection.execute("SELECT * FROM posts WHERE id = ?", (post_id,)).fetchone()
        self.assertEqual(row["status"], "published")
        self.assertEqual(row["external_post_id"], "external-123")

    def test_duplicate_is_rejected(self):
        agent = PostingAgent(self.database)
        post = PostRecord(self.content_id, "instagram", "o2_english")
        agent.queue(post)

        with self.assertRaises(ValueError):
            agent.queue(post)

    def test_current_ready_package_queueing_is_idempotent(self):
        agent = PostingAgent(self.database)

        self.assertEqual(agent.queue_ready_packages(), 1)
        self.assertEqual(agent.queue_ready_packages(), 0)
        row = self.database.connection.execute("SELECT status, platform, account FROM posts WHERE content_id = ?", (self.content_id,)).fetchone()
        self.assertEqual((row["status"], row["platform"], row["account"]), ("scheduled", "instagram", "o2_english"))

    def test_queue_rejects_a_destination_different_from_the_package(self):
        with self.assertRaisesRegex(ValueError, "destination"):
            PostingAgent(self.database).queue(PostRecord(self.content_id, "instagram", "another_account"))

    def test_minimum_interval_moves_second_post_to_the_next_slot(self):
        agent = PostingAgent(self.database, min_post_interval_minutes=60)
        first = PostRecord(self.content_id, "instagram", "o2_english")
        first_id = agent.queue(first)
        second_content = self.database.save_content_package(ContentPackage(
            self.job_id, "o2_english_instagram", "Title 2", "Body", "Caption", platform="instagram",
            account="o2_english", content_format="instagram_idiom_carousel",
        ))
        self.database.mark_package_rendered_assets(
            second_content, [f"generated/second-slide-{index}.png" for index in range(1, 6)], required_asset_count=5,
        )

        second_id = agent.queue(PostRecord(second_content, "instagram", "o2_english"))
        first_row = self.database.connection.execute("SELECT scheduled_at FROM posts WHERE id = ?", (first_id,)).fetchone()
        second_row = self.database.connection.execute("SELECT scheduled_at FROM posts WHERE id = ?", (second_id,)).fetchone()
        self.assertGreaterEqual(second_row["scheduled_at"], first_row["scheduled_at"])

    def test_due_instagram_package_is_delivered_and_audited(self):
        agent = PostingAgent(self.database)
        post_id = agent.queue(PostRecord(self.content_id, "instagram", "o2_english"))

        class Publisher:
            def __init__(self):
                self.package = None

            def publish_package(self, package):
                self.package = package
                return "external-123"

        publisher = Publisher()
        self.assertEqual(agent.publish_due({"instagram": publisher}), 1)
        row = self.database.connection.execute("SELECT status, external_post_id FROM posts WHERE id = ?", (post_id,)).fetchone()
        self.assertEqual(publisher.package["package_platform"], "instagram")
        self.assertEqual(publisher.package["package_account"], "o2_english")
        self.assertEqual(row["status"], "published")
        self.assertEqual(row["external_post_id"], "external-123")

    def test_transient_delivery_failure_is_persisted_for_retry(self):
        agent = PostingAgent(self.database, retry_delay_minutes=15)
        post_id = agent.queue(PostRecord(self.content_id, "instagram", "o2_english"))

        class FailingPublisher:
            def publish_package(self, package):
                raise RuntimeError("temporary outage")

        self.assertEqual(agent.publish_due({"instagram": FailingPublisher()}), 0)
        post = self.database.connection.execute("SELECT status, attempt_count, next_attempt_at FROM posts WHERE id = ?", (post_id,)).fetchone()
        attempt = self.database.connection.execute("SELECT status, error FROM post_attempts WHERE post_id = ?", (post_id,)).fetchone()
        self.assertEqual(post["status"], "retryable_failure")
        self.assertEqual(post["attempt_count"], 1)
        self.assertIsNotNone(post["next_attempt_at"])
        self.assertEqual(attempt["status"], "retryable_failure")

    def test_instagram_adapter_container_ids_are_persisted(self):
        content_id = self.database.save_content_package(ContentPackage(
            self.job_id, "o2_english_instagram", "Idiom", "Body", "Caption",
            platform="instagram", account="o2_english",
            content_format="instagram_idiom_carousel",
        ))
        self.database.mark_package_rendered_assets(content_id, [f"slide-{index}.png" for index in range(1, 6)], required_asset_count=5)
        post_id = PostingAgent(self.database).queue(PostRecord(content_id, "instagram", "o2_english"))

        class Publisher:
            container_recorder = None

            def publish_package(self, package):
                self.container_recorder("item-1", "carousel_item", 0, "created", "2026-08-20T00:00:00+00:00")
                self.container_recorder("carousel-1", "carousel", None, "created", "2026-08-20T00:00:00+00:00")
                return "instagram-media-1"

        self.assertEqual(PostingAgent(self.database).publish_due({"instagram": Publisher()}), 1)
        containers = self.database.connection.execute(
            "SELECT container_id, container_type, asset_index FROM instagram_containers WHERE post_id = ? ORDER BY id",
            (post_id,),
        ).fetchall()
        self.assertEqual(
            [(row["container_id"], row["container_type"], row["asset_index"]) for row in containers],
            [("item-1", "carousel_item", 0), ("carousel-1", "carousel", None)],
        )
