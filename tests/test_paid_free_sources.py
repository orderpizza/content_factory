import json
import unittest
from unittest.mock import patch

from intelligence.sources import RedditSource, YouTubeSource


class OptionalSourceTests(unittest.TestCase):
    def test_reddit_requires_credentials(self):
        with self.assertRaises(RuntimeError):
            RedditSource(["news"], client_id=None, client_secret=None).collect()

    def test_youtube_requires_api_key(self):
        with self.assertRaises(RuntimeError):
            YouTubeSource(api_key=None).collect()

    def test_youtube_converts_popular_video(self):
        payload = {"items": [{"id": "abc", "snippet": {"title": "Popular video"}, "statistics": {"viewCount": "100"}}]}

        class Response:
            def __enter__(self): return self
            def __exit__(self, *args): pass
            def read(self): return json.dumps(payload).encode()

        with patch("intelligence.sources.urlopen", return_value=Response()):
            observations = YouTubeSource(api_key="key", limit=1).collect()

        self.assertEqual(observations[0].topic, "Popular video")
        self.assertEqual(observations[0].current_volume, 100)
