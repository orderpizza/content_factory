import tempfile
import unittest
from pathlib import Path

from common.models import ContentJob, ContentPackage, TrendCandidate
from database.sqlite import Database
from dashboard import render_dashboard


class DashboardTests(unittest.TestCase):
    def test_current_dashboard_is_read_only_and_auto_refreshes(self):
        with tempfile.TemporaryDirectory() as directory:
            database = Database(Path(directory) / "content.db")
            database.initialize()
            database.upsert_candidate(TrendCandidate("topic", 0.8, "EMERGING", {"velocity": 0.9}, ["rss"]), "2026-01-01")
            html = render_dashboard(database)
            database.close()

        self.assertIn("System Overview", html)
        self.assertIn("Trend Detection", html)
        self.assertIn("Ranked Candidates", html)
        self.assertIn("topic", html)
        self.assertIn("Cooldown Until", html)
        self.assertNotIn("<form", html)
        self.assertIn("http-equiv='refresh'", html)
        self.assertIn("content='15'", html)

    def test_visual_status_reports_pending_render_work(self):
        with tempfile.TemporaryDirectory() as directory:
            database = Database(Path(directory) / "content.db")
            database.initialize()
            job_id = database.save_content_job(ContentJob(
                None, "o2_english_instagram", "topic", "angle", "English learners", "teach",
                target_platform="instagram", target_account="o2_english",
                content_format="instagram_idiom_carousel", visual_profile_id="o2_english_idiom_carousel_v1",
            ))
            database.save_content_package(ContentPackage(
                job_id, "o2_english_instagram", "Title", "Body", "Caption", platform="instagram",
                account="o2_english", content_format="instagram_idiom_carousel",
            ))
            html = render_dashboard(database)
            database.close()

        self.assertIn("package(s) awaiting render", html)
        self.assertIn("Awaiting Render", html)
