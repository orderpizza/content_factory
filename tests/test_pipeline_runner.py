import tempfile
import unittest
from pathlib import Path

from common.models import ContentJob
from database.sqlite import Database
from metadata_fakes import FakeMetadataGenerator
from metadata_fakes import FakeIdiomGenerator
from pipelines.o2_english.pipeline import O2EnglishInstagramPipeline
from pipelines.poc.pipeline import PocPipeline
from pipelines.runner import PipelineRunner


class PipelineRunnerTests(unittest.TestCase):
    def test_persisted_job_becomes_package(self):
        with tempfile.TemporaryDirectory() as directory:
            database = Database(Path(directory) / "content.db")
            database.initialize()
            job_id = database.save_content_job(ContentJob(None, "poc_pipeline", "topic", "angle", "audience", "inform"))
            package = PipelineRunner(database, PocPipeline(FakeMetadataGenerator())).consume_next()
            job = database.connection.execute("SELECT status FROM content_jobs WHERE job_id = ?", (job_id,)).fetchone()
            database.close()

        self.assertEqual(package.job_id, job_id)
        self.assertEqual(package.status, "awaiting_render")
        self.assertEqual(job["status"], "completed")

    def test_runner_dispatches_persisted_o2_english_job(self):
        with tempfile.TemporaryDirectory() as directory:
            database = Database(Path(directory) / "content.db")
            database.initialize()
            job_id = database.save_content_job(ContentJob(
                None, "o2_english_instagram", "break the ice", "Teach the idiom.",
                "intermediate learners", "teach", target_platform="instagram",
                target_account="o2_english", content_format="instagram_idiom_carousel",
                visual_profile_id="o2_english_idiom_carousel_v1",
            ))
            runner = PipelineRunner(database, {
                "poc_pipeline": PocPipeline(FakeMetadataGenerator()),
                "o2_english_instagram": O2EnglishInstagramPipeline(FakeIdiomGenerator()),
            })
            package = runner.consume_next()
            job = database.connection.execute("SELECT status FROM content_jobs WHERE job_id = ?", (job_id,)).fetchone()
            database.close()

        self.assertEqual(package.pipeline_id, "o2_english_instagram")
        self.assertEqual(package.content_format, "instagram_idiom_carousel")
        self.assertEqual(job["status"], "completed")
