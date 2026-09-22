from common.timestamps import parse_timestamp, serialize_timestamp, utc_now
from datetime import datetime, timedelta, timezone
import unittest


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

    def test_adapter_normalized_timestamp_is_not_treated_as_missing(self):
        from detection.normalization import parse_provider_time
        collected = parse_timestamp("2026-09-22T12:00:00")
        self.assertEqual(parse_provider_time("2026-09-21T10:00:00", collected),
                         ("2026-09-21T10:00:00", "provider_time_valid"))
        self.assertEqual(parse_provider_time("2026-09-22T12:03:00", collected),
                         ("2026-09-22T12:00:00", "provider_time_clamped"))
        for value in (None, "invalid", "2026-09-22T12:06:00"):
            self.assertEqual(parse_provider_time(value, collected),
                             ("2026-09-22T12:00:00", "provider_time_fallback"))


if __name__ == "__main__":
    unittest.main()
