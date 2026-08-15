import unittest

from intelligence.detector import TrendDetector
from intelligence.sources import FixtureTrendSource, Observation


class TrendDetectorTests(unittest.TestCase):
    def test_scores_relative_growth(self):
        detector = TrendDetector(FixtureTrendSource([
            Observation("new topic", "New Topic", "fixture", 4000, 500),
            Observation("steady topic", "Steady Topic", "fixture", 10200, 10000),
        ]))

        trends = detector.detect()

        self.assertEqual([trend.topic for trend in trends], ["new topic", "steady topic"])
        self.assertAlmostEqual(trends[0].score, 7.0)
        self.assertAlmostEqual(trends[1].score, 0.02)

    def test_deduplicates_same_topic_and_source_using_strongest_observation(self):
        detector = TrendDetector(FixtureTrendSource([
            Observation(" Topic ", "Weak", "Fixture", 110, 100),
            Observation("topic", "Strong", "fixture", 400, 100),
        ]))

        trends = detector.detect()

        self.assertEqual(len(trends), 1)
        self.assertEqual(trends[0].title, "Strong")

    def test_preserves_source_data_in_trend(self):
        detector = TrendDetector(FixtureTrendSource([
            Observation("topic", "Topic", "fixture", 20, 10, raw_data={"region": "global"}),
        ]))

        trend = detector.detect()[0]

        self.assertEqual(trend.raw_data["region"], "global")
        self.assertEqual(trend.raw_data["current_volume"], 20)
