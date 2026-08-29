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

    def _o2_job(self, trend_id: int | None):
        return ContentJob(
            trend_id, "o2_english_instagram", "topic", "an angle", "English learners", "teach",
            ["point"], ["source"], target_platform="instagram", target_account="o2_english",
            content_format="instagram_idiom_carousel", visual_profile_id="o2_english_idiom_carousel_v1",
        )

    def _o2_package(self, job_id: int):
        return ContentPackage(
            job_id, "o2_english_instagram", "Title", "Body", "Caption", platform="instagram",
            account="o2_english", content_format="instagram_idiom_carousel",
        )

    def test_trend_is_stored_and_loaded(self):
        trend_id = self.database.save_trend(Trend("topic", "A topic", "rss", score=4.2, raw_data={"rank": 1}))
        trend = self.database.get_trend(trend_id)
        self.assertEqual(trend.id, trend_id)
        self.assertEqual(trend.raw_data, {"rank": 1})

    def test_o2_records_can_be_stored_across_the_delivery_boundary(self):
        trend_id = self.database.save_trend(Trend("topic", "A topic", "rss"))
        job_id = self.database.save_content_job(self._o2_job(trend_id))
        content_id = self.database.save_content_package(self._o2_package(job_id))
        self.database.mark_package_rendered_assets(content_id, [f"generated/slide-{index}.png" for index in range(1, 6)], required_asset_count=5)
        post_id = self.database.queue_post(PostRecord(content_id, "instagram", "o2_english"))
        self.assertGreater(post_id, 0)

    def test_duplicate_post_is_rejected_for_same_content_and_account(self):
        trend_id = self.database.save_trend(Trend("topic", "A topic", "rss"))
        job_id = self.database.save_content_job(self._o2_job(trend_id))
        content_id = self.database.save_content_package(self._o2_package(job_id))
        self.database.mark_package_rendered_assets(content_id, [f"generated/slide-{index}.png" for index in range(1, 6)], required_asset_count=5)
        self.database.queue_post(PostRecord(content_id, "instagram", "o2_english"))
        with self.assertRaises(Exception):
            self.database.queue_post(PostRecord(content_id, "instagram", "o2_english"))

    def test_rendered_package_records_asset_and_readiness(self):
        trend_id = self.database.save_trend(Trend("topic", "A topic", "rss"))
        job_id = self.database.save_content_job(self._o2_job(trend_id))
        content_id = self.database.save_content_package(self._o2_package(job_id))

        self.database.mark_package_rendered_assets(content_id, [f"generated/slide-{index}.png" for index in range(1, 6)], required_asset_count=5)
        row = self.database.connection.execute("SELECT assets, status FROM content_packages WHERE content_id = ?", (content_id,)).fetchone()

        self.assertEqual(json.loads(row["assets"]), [f"generated/slide-{index}.png" for index in range(1, 6)])
        self.assertEqual(row["status"], "ready_for_posting")

    def test_api_usage_is_persisted(self):
        usage_id = self.database.record_api_usage(
            "determination", 12, "gemini-test", 10, 5, 15, 0.001, "2026-08-18T00:00:00+00:00",
        )
        row = self.database.connection.execute("SELECT * FROM api_usage WHERE id = ?", (usage_id,)).fetchone()
        self.assertEqual((row["phase"], row["total_tokens"], row["estimated_cost_usd"]), ("determination", 15, 0.001))


if __name__ == "__main__":
    unittest.main()
