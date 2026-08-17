import tempfile
import unittest
from pathlib import Path

from common.models import ContentPackage, ContentJob, PostRecord, Trend
from database.sqlite import Database
from posting.agent import BlueskyPublisher, PostingAgent


class PostingAgentTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.database = Database(Path(self.temp_dir.name) / "content.db")
        self.database.initialize()
        trend_id = self.database.save_trend(Trend("topic", "Topic", "fixture"))
        job_id = self.database.save_content_job(ContentJob(trend_id, "poc_pipeline", "topic", "angle", "audience", "objective"))
        self.content_id = self.database.save_content_package(ContentPackage(job_id, "poc_pipeline", "Title", "Body", "Caption", platform="test", account="local"))
        self.database.mark_package_rendered(self.content_id, "generated/card.png")

    def tearDown(self):
        self.database.close()
        self.temp_dir.cleanup()

    def test_queue_and_mark_published(self):
        agent = PostingAgent(self.database)
        post_id = agent.queue(PostRecord(self.content_id, "test", "local"))

        agent.mark_published(post_id, "external-123")
        row = self.database.connection.execute("SELECT * FROM posts WHERE id = ?", (post_id,)).fetchone()
        self.assertEqual(row["status"], "published")
        self.assertEqual(row["external_post_id"], "external-123")

    def test_duplicate_is_rejected(self):
        agent = PostingAgent(self.database)
        post = PostRecord(self.content_id, "test", "local")
        agent.queue(post)

        with self.assertRaises(ValueError):
            agent.queue(post)

    def test_ready_package_is_automatically_queued_once(self):
        agent = PostingAgent(self.database)

        self.assertEqual(agent.queue_ready_packages(), 1)
        self.assertEqual(agent.queue_ready_packages(), 0)
        row = self.database.connection.execute("SELECT status, platform, account FROM posts WHERE content_id = ?", (self.content_id,)).fetchone()
        self.assertEqual((row["status"], row["platform"], row["account"]), ("scheduled", "test", "local"))

    def test_minimum_interval_moves_second_post_to_the_next_slot(self):
        agent = PostingAgent(self.database, min_post_interval_minutes=60)
        first = PostRecord(self.content_id, "test", "local")
        first_id = agent.queue(first)
        second_content = self.database.save_content_package(ContentPackage(1, "poc_pipeline", "Title 2", "Body", "Caption", platform="test", account="local"))
        self.database.mark_package_rendered(second_content, "generated/card-2.png")

        second_id = agent.queue(PostRecord(second_content, "test", "local"))
        first_row = self.database.connection.execute("SELECT scheduled_at FROM posts WHERE id = ?", (first_id,)).fetchone()
        second_row = self.database.connection.execute("SELECT scheduled_at FROM posts WHERE id = ?", (second_id,)).fetchone()
        self.assertGreaterEqual(second_row["scheduled_at"], first_row["scheduled_at"])

    def test_bluesky_publisher_uses_session_token(self):
        publisher = BlueskyPublisher("example.bsky.social", "app-password", "https://example.test")
        calls = []

        def fake_request(endpoint, payload, token=None):
            calls.append((endpoint, payload, token))
            if endpoint.endswith("createSession"):
                return {"did": "did:example:1", "accessJwt": "jwt"}
            return {"uri": "at://did:example:1/app.bsky.feed.post/1"}

        publisher._request = fake_request
        self.assertEqual(publisher.publish("Hello from the POC"), "at://did:example:1/app.bsky.feed.post/1")
        self.assertEqual(calls[1][2], "jwt")

    def test_due_post_is_published_with_generated_hashtags(self):
        self.database.connection.execute("UPDATE content_packages SET caption = ?, hashtags = ? WHERE content_id = ?", ("Caption", '["#Topic"]', self.content_id))
        self.database.connection.commit()
        agent = PostingAgent(self.database)
        post_id = agent.queue(PostRecord(self.content_id, "test", "local"))

        class Publisher:
            def __init__(self):
                self.text = ""

            def publish(self, text):
                self.text = text
                return "external-123"

        publisher = Publisher()
        self.assertEqual(agent.publish_due(publisher), 1)
        row = self.database.connection.execute("SELECT status FROM posts WHERE id = ?", (post_id,)).fetchone()
        self.assertEqual(publisher.text, "Caption #Topic")
        self.assertEqual(row["status"], "published")
