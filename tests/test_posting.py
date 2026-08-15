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
        self.content_id = self.database.save_content_package(ContentPackage(job_id, "poc_pipeline", "Title", "Body", "Caption"))

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

    def test_minimum_interval_is_enforced(self):
        agent = PostingAgent(self.database, min_post_interval_minutes=60)
        first = PostRecord(self.content_id, "test", "local")
        agent.queue(first)
        second_content = self.database.save_content_package(ContentPackage(1, "poc_pipeline", "Title 2", "Body", "Caption"))

        with self.assertRaises(ValueError):
            agent.queue(PostRecord(second_content, "test", "local"))

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
