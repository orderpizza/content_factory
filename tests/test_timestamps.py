import re
import unittest
from datetime import datetime, timedelta, timezone

from common.timestamps import parse_timestamp, serialize_timestamp, utc_now


class TimestampContractTests(unittest.TestCase):
    def test_canonical_values_are_utc_naive_second_precision(self):
        value = utc_now()
        self.assertRegex(value, r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}$")
        self.assertNotIn("+", value)
        self.assertNotIn("Z", value)

    def test_aware_external_timestamp_preserves_its_utc_instant(self):
        self.assertEqual(
            serialize_timestamp("2026-09-21T20:16:00+02:00"),
            "2026-09-21T18:16:00",
        )
        self.assertEqual(
            serialize_timestamp(datetime(2026, 9, 21, 18, 16, 0, 900000, tzinfo=timezone.utc)),
            "2026-09-21T18:16:00",
        )

    def test_persisted_naive_timestamp_is_utc_for_arithmetic(self):
        current = parse_timestamp("2026-09-21T18:16:00")
        self.assertEqual(current.tzinfo, timezone.utc)
        self.assertEqual(serialize_timestamp(current + timedelta(minutes=5)), "2026-09-21T18:21:00")


if __name__ == "__main__":
    unittest.main()
