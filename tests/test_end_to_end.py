import tempfile
import unittest
from pathlib import Path

from common.models import PostRecord, Trend
from database.sqlite import Database
from determination.service import DeterminationService
from intelligence.detector import TrendDetector
from intelligence.sources import FixtureTrendSource, Observation
from pipelines.poc.pipeline import PocPipeline
from posting.agent import PostingAgent
from visual.renderer import VisualRenderer


class EndToEndTests(unittest.TestCase):
    def test_offline_poc_loop_reaches_publication_record(self):
        with tempfile.TemporaryDirectory() as directory:
            database = Database(Path(directory) / "content.db")
            database.initialize()
            try:
                detected = TrendDetector(FixtureTrendSource([
                    Observation("rapid topic", "Rapid Topic", "fixture", 4000, 500),
                ])).detect()[0]
                detected.id = database.save_trend(detected)

                job = DeterminationService().determine(detected)
                self.assertIsNotNone(job)
                job.job_id = database.save_content_job(job)

                package = PocPipeline().run(job)
                package.content_id = database.save_content_package(package)
                html_path = VisualRenderer().render_html(package, Path(directory) / "generated" / "card.html")

                post_id = PostingAgent(database).queue(PostRecord(package.content_id, "test", "local"))
                PostingAgent(database).mark_published(post_id, "offline-post-1")
                record = database.connection.execute("SELECT * FROM posts WHERE id = ?", (post_id,)).fetchone()

                self.assertTrue(html_path.exists())
                self.assertEqual(record["status"], "published")
                self.assertEqual(record["external_post_id"], "offline-post-1")
            finally:
                database.close()


if __name__ == "__main__":
    unittest.main()
