"""UTC timestamp contract for persisted Content Factory records."""

from __future__ import annotations

from datetime import datetime, timezone


TIMESTAMP_FORMAT = "%Y-%m-%dT%H:%M:%S"


def parse_timestamp(value: str | datetime) -> datetime:
    """Read a Content Factory timestamp as an aware UTC datetime.

    Persisted values are deliberately timezone-naive.  Naive input therefore
    means UTC; external aware values are converted to UTC before serialization.
    """
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, str):
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    else:
        raise TypeError("timestamp must be a datetime or ISO-8601 string")
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def serialize_timestamp(value: str | datetime) -> str:
    """Return the one persisted representation: UTC-naive ISO seconds."""
    return parse_timestamp(value).replace(tzinfo=None, microsecond=0).strftime(TIMESTAMP_FORMAT)


def utc_now() -> str:
    """Return the current instant in the persisted Content Factory format."""
    return serialize_timestamp(datetime.now(timezone.utc))


def utc_datetime_now() -> datetime:
    """Return the current instant as an aware UTC datetime for calculations."""
    return datetime.now(timezone.utc).replace(microsecond=0)
