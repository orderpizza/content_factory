import tempfile
import unittest
from pathlib import Path

from common.models import ContentJob, ContentPackage, TrendCandidate
from database.sqlite import Database
from dashboard import render_dashboard


class DashboardTests(unittest.TestCase):
    def test_dashboard_is_read_only_html(self):
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

    def test_visual_status_reports_pending_render_work(self):
        with tempfile.TemporaryDirectory() as directory:
            database = Database(Path(directory) / "content.db")
            database.initialize()
            job_id = database.save_content_job(ContentJob(None, "poc_pipeline", "topic", "angle", "audience", "inform"))
            database.save_content_package(ContentPackage(job_id, "poc_pipeline", "Title", "Body", "Caption"))
            html = render_dashboard(database)
            database.close()

        self.assertIn("package(s) awaiting render", html)
        self.assertIn("Awaiting Render", html)
