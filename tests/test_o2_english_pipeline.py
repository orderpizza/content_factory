import tempfile
import unittest
from pathlib import Path

from common.models import ContentJob
from pipelines.o2_english.pipeline import O2EnglishInstagramPipeline
from visual.o2_english import render_idiom_carousel_html
from metadata_fakes import FakeIdiomGenerator


class O2EnglishPipelineTests(unittest.TestCase):
    def _job(self):
        return ContentJob(
            trend_id=None,
            pipeline_id="o2_english_instagram",
            topic="break the ice",
            angle="Teach the idiom through simple examples.",
            audience="intermediate English learners",
            objective="teach and encourage saves",
            job_id=7,
            target_platform="instagram",
            target_account="o2_english",
            content_format="instagram_idiom_carousel",
            visual_profile_id="o2_english_idiom_carousel_v1",
        )

    def test_fixed_idiom_job_becomes_instagram_package(self):
        package = O2EnglishInstagramPipeline(FakeIdiomGenerator()).run(self._job())

        self.assertEqual(package.platform, "instagram")
        self.assertEqual(package.account, "o2_english")
        self.assertEqual(package.visual_spec["profile_id"], "o2_english_idiom_carousel_v1")
        self.assertEqual(package.visual_spec["resolved_template_ids"][0], "o2_hook_centered_v1")
        self.assertEqual(len(package.visual_spec["slides"]), 5)

    def test_renderer_writes_one_escaped_html_file_per_slide(self):
        package = O2EnglishInstagramPipeline(FakeIdiomGenerator()).run(self._job())
        package.visual_spec["slides"][0]["text"] = "A <topic>"
        with tempfile.TemporaryDirectory() as directory:
            files = render_idiom_carousel_html(package, Path(directory))
            html = files[0].read_text(encoding="utf-8")

        self.assertEqual(len(files), 5)
        self.assertIn("width:1080px", html)
        self.assertIn("height:1920px", html)
        self.assertIn("A &lt;topic&gt;", html)
