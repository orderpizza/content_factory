import json
import tempfile
import unittest
from pathlib import Path

from common.models import ContentJob, ContentPackage, PostRecord, Trend
from database.sqlite import Database


class DatabaseTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.database = Database(Path(self.temp_dir.name) / "content.db")
        self.database.initialize()

    def tearDown(self):
        self.database.close()
        self.temp_dir.cleanup()

    def test_trend_is_stored_and_loaded(self):
        trend_id = self.database.save_trend(Trend("topic", "A topic", "rss", score=4.2, raw_data={"rank": 1}))
        trend = self.database.get_trend(trend_id)
        self.assertEqual(trend.id, trend_id)
        self.assertEqual(trend.raw_data, {"rank": 1})

    def test_full_poc_records_can_be_stored(self):
        trend_id = self.database.save_trend(Trend("topic", "A topic", "rss"))
        job_id = self.database.save_content_job(ContentJob(trend_id, "poc_pipeline", "topic", "an angle", "readers", "inform", ["point"], ["source"]))
        content_id = self.database.save_content_package(ContentPackage(job_id, "poc_pipeline", "Title", "Body", "Caption", platform="test", account="local"))
        self.database.mark_package_rendered(content_id, "generated/card.png")
        post_id = self.database.queue_post(PostRecord(content_id, "test", "local"))
        self.assertGreater(post_id, 0)

    def test_duplicate_post_is_rejected_for_same_content_and_account(self):
        trend_id = self.database.save_trend(Trend("topic", "A topic", "rss"))
        job_id = self.database.save_content_job(ContentJob(trend_id, "poc_pipeline", "topic", "angle", "audience", "objective"))
        content_id = self.database.save_content_package(ContentPackage(job_id, "poc_pipeline", "Title", "Body", "Caption", platform="test", account="local"))
        self.database.mark_package_rendered(content_id, "generated/card.png")
        self.database.queue_post(PostRecord(content_id, "test", "local"))
        with self.assertRaises(Exception):
            self.database.queue_post(PostRecord(content_id, "test", "local"))

    def test_rendered_package_records_asset_and_readiness(self):
        trend_id = self.database.save_trend(Trend("topic", "A topic", "rss"))
        job_id = self.database.save_content_job(ContentJob(trend_id, "poc_pipeline", "topic", "angle", "audience", "objective"))
        content_id = self.database.save_content_package(ContentPackage(job_id, "poc_pipeline", "Title", "Body", "Caption"))

        self.database.mark_package_rendered(content_id, "generated/card.png")
        row = self.database.connection.execute("SELECT assets, status FROM content_packages WHERE content_id = ?", (content_id,)).fetchone()

        self.assertEqual(json.loads(row["assets"]), ["generated/card.png"])
        self.assertEqual(row["status"], "ready_for_posting")


if __name__ == "__main__":
    unittest.main()
