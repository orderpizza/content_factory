import tempfile
import unittest
from pathlib import Path

from common.models import ContentJob, ContentPackage
from database.sqlite import Database
from metadata_fakes import FakeIdiomGenerator, FakeIdiomMetadataGenerator
from pipelines.o2_english.pipeline import O2EnglishInstagramPipeline
from pipelines.runner import PipelineRunner


class PipelineRunnerTests(unittest.TestCase):
    @staticmethod
    def _o2_job():
        return ContentJob(
            None, "o2_english_instagram", "break the ice", "Teach the idiom.",
            "intermediate English learners", "teach", target_platform="instagram",
            target_account="o2_english", content_format="instagram_idiom_carousel",
            visual_profile_id="o2_english_idiom_carousel_v1",
        )

    @staticmethod
    def _pipeline():
        return O2EnglishInstagramPipeline(FakeIdiomGenerator(), FakeIdiomMetadataGenerator())

    def test_persisted_o2_job_becomes_package(self):
        with tempfile.TemporaryDirectory() as directory:
            database = Database(Path(directory) / "content.db")
            database.initialize()
            job_id = database.save_content_job(self._o2_job())
            package = PipelineRunner(database, self._pipeline()).consume_next()
            job = database.connection.execute("SELECT status FROM content_jobs WHERE job_id = ?", (job_id,)).fetchone()
            database.close()

        self.assertEqual(package.job_id, job_id)
        self.assertEqual(package.pipeline_id, "o2_english_instagram")
        self.assertEqual(package.status, "awaiting_render")
        self.assertEqual(job["status"], "completed")

    def test_unregistered_o2_job_is_marked_failed(self):
        with tempfile.TemporaryDirectory() as directory:
            database = Database(Path(directory) / "content.db")
            database.initialize()
            job_id = database.save_content_job(self._o2_job())
            runner = PipelineRunner(database, {})
            with self.assertRaisesRegex(ValueError, "No pipeline registered"):
                runner.consume_next()
            job = database.connection.execute("SELECT status FROM content_jobs WHERE job_id = ?", (job_id,)).fetchone()
            database.close()

        self.assertEqual(job["status"], "failed")

    def test_existing_package_is_reused_after_interrupted_completion(self):
        with tempfile.TemporaryDirectory() as directory:
            database = Database(Path(directory) / "content.db")
            database.initialize()
            job_id = database.save_content_job(self._o2_job())
            content_id = database.save_content_package(ContentPackage(
                job_id, "o2_english_instagram", "Idiom", "Body", "Caption", platform="instagram",
                account="o2_english", content_format="instagram_idiom_carousel",
            ))
            database.connection.execute("UPDATE content_jobs SET status = 'pending' WHERE job_id = ?", (job_id,))
            database.connection.commit()
            package = PipelineRunner(database, self._pipeline()).consume_next()
            count = database.connection.execute("SELECT COUNT(*) AS count FROM content_packages WHERE job_id = ?", (job_id,)).fetchone()["count"]
            database.close()

        self.assertEqual(package.content_id, content_id)
        self.assertEqual(count, 1)
