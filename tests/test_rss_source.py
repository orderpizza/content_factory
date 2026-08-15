import unittest
from unittest.mock import patch

from intelligence.sources import CombinedTrendSource, RssSource


class RssSourceTests(unittest.TestCase):
    def test_parses_rss_entries(self):
        payload = b"<rss><channel><item><title>News topic</title><link>https://example.test/news</link></item></channel></rss>"

        class Response:
            def __enter__(self): return self
            def __exit__(self, *args): pass
            def read(self): return payload

        with patch("intelligence.sources.urlopen", return_value=Response()):
            observations = RssSource("https://example.test/feed").collect()

        self.assertEqual(observations[0].topic, "News topic")
        self.assertEqual(observations[0].source, "rss_example.test")
        self.assertEqual(observations[0].url, "https://example.test/news")

    def test_combines_sources(self):
        first = type("Source", (), {"collect": lambda self: ["one"]})()
        second = type("Source", (), {"collect": lambda self: ["two"]})()

        self.assertEqual(CombinedTrendSource([first, second]).collect(), ["one", "two"])
