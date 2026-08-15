import tempfile
import unittest
from pathlib import Path

from common.models import ContentPackage
from visual.renderer import VisualRenderer


class VisualRendererTests(unittest.TestCase):
    def test_renders_fixed_size_html_with_escaped_content(self):
        with tempfile.TemporaryDirectory() as directory:
            path = VisualRenderer().render_html(
                ContentPackage(1, "poc_pipeline", "A <topic>", "Body & detail", "Caption"),
                Path(directory) / "card.html",
            )
            html = path.read_text(encoding="utf-8")

        self.assertIn("width: 1080px", html)
        self.assertIn("height: 1350px", html)
        self.assertIn("A &lt;topic&gt;", html)
        self.assertIn("Body &amp; detail", html)
