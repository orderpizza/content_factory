import unittest

from intelligence.aggregation import build_snapshots, canonical_topic
from intelligence.sources import Observation


class AggregationTests(unittest.TestCase):
    def test_canonical_topic_normalizes_punctuation_and_case(self):
        self.assertEqual(canonical_topic("  New! Topic  "), "new topic")

    def test_groups_mentions_and_counts_sources(self):
        snapshots = build_snapshots([
            Observation("New Topic", "One", "rss", 2, 0),
            Observation("new-topic", "Two", "wikimedia", 3, 0),
        ], "2026-01-01T00:00:00+00:00")

        self.assertEqual(len(snapshots), 1)
        self.assertEqual(snapshots[0].topic, "new topic")
        self.assertEqual(snapshots[0].activity, 5)
        self.assertEqual(snapshots[0].source_count, 2)
        self.assertEqual(snapshots[0].sources, ["rss", "wikimedia"])

    def test_clusters_related_headlines(self):
        snapshots = build_snapshots([
            Observation("Earthquake strikes Indonesia", "One", "rss", 2, 0),
            Observation("Strong earthquake reported Indonesia", "Two", "wikimedia", 3, 0),
        ], "2026-01-01T00:00:00+00:00")

        self.assertEqual(len(snapshots), 1)
        self.assertEqual(snapshots[0].source_count, 2)
