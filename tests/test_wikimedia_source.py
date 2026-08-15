import json
import unittest
from unittest.mock import patch

from intelligence.sources import WikimediaPageviewSource


class WikimediaPageviewSourceTests(unittest.TestCase):
    def test_converts_pageviews_to_observations(self):
        payload = {"items": [{"articles": [{"article": "Example_topic", "views": 123}]}]}

        class Response:
            def __enter__(self): return self
            def __exit__(self, *args): pass
            def read(self): return json.dumps(payload).encode()

        with patch("intelligence.sources.urlopen", return_value=Response()):
            observations = WikimediaPageviewSource(limit=1).collect()

        self.assertEqual(observations[0].topic, "Example topic")
        self.assertEqual(observations[0].current_volume, 123)
