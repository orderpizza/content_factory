import unittest

from common.models import ContentJob
from pipelines.poc.pipeline import PocPipeline
from metadata_fakes import FakeMetadataGenerator


class PocPipelineTests(unittest.TestCase):
    def test_job_becomes_content_package(self):
        job = ContentJob(1, "poc_pipeline", "rising topic", "Explain the shift.", "readers", "inform", ["Point one"], job_id=7)

        package = PocPipeline(FakeMetadataGenerator()).run(job)

        self.assertEqual(package.job_id, 7)
        self.assertEqual(package.pipeline_id, "poc_pipeline")
        self.assertEqual(package.title, "Rising Topic")
        self.assertIn("Point one", package.body)
        self.assertEqual(package.visual_spec["template_id"], "poc_card")
        self.assertEqual(package.platform, "bluesky")
        self.assertEqual(package.hashtags, ["#ContentFactory"])

    def test_rejects_unknown_pipeline(self):
        job = ContentJob(1, "other_pipeline", "topic", "angle", "audience", "objective")

        with self.assertRaises(ValueError):
            PocPipeline(FakeMetadataGenerator()).run(job)
