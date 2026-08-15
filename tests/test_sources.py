import unittest
from unittest.mock import patch

from intelligence.sources import HackerNewsSource


class HackerNewsSourceTests(unittest.TestCase):
    def test_collects_top_story_observations(self):
        responses = [b'[1]', b'{"id": 1, "type": "story", "title": "A story", "score": 42, "url": "https://example.test"}']

        class Response:
            def __init__(self, body): self.body = body
            def __enter__(self): return self
            def __exit__(self, *args): pass
            def read(self): return self.body

        with patch("intelligence.sources.urlopen", side_effect=[Response(body) for body in responses]):
            observations = HackerNewsSource(limit=1).collect()

        self.assertEqual(observations[0].topic, "A story")
        self.assertEqual(observations[0].current_volume, 42)
