"""Read-only storage facts. Planning never uses these as admission policy."""
from .timestamps import parse_timestamp, utc_datetime_now

MAX_SAMPLE_AGE_SECONDS = 600


def storage_status(connection, *, at=None):
    at = at or utc_datetime_now()
    row = connection.execute(
        "SELECT * FROM storage_samples ORDER BY storage_sample_id DESC LIMIT 1"
    ).fetchone()
    reason, age = "missing_sample", None
    if row is not None:
        try:
            sampled = parse_timestamp(row['sampled_at'])
            age = (at - sampled).total_seconds()
            reason = ("invalid_sample_time" if age < 0 else
                      "stale_sample" if age > MAX_SAMPLE_AGE_SECONDS else row['state'])
        except (TypeError, ValueError):
            reason = "invalid_sample_time"
    return {"reason": reason, "state": row['state'] if row else None,
            "sampled_at": row['sampled_at'] if row else None,
            "age_seconds": round(age) if age is not None else None,
            "free_bytes": row['free_bytes'] if row else None}


def storage_recovery(status):
    if status['reason'] in {'missing_sample', 'stale_sample', 'invalid_sample_time'}:
        return ('Storage sample is missing, stale or clock-invalid; this does not mean the disk is full. '
                'Run .venv/bin/python scripts/run_storage_monitor.py --database <the dashboard database> '
                '--poll to refresh observability. Planning remains available. '
                'Check system UTC time if the sample remains clock-invalid.')
    return ('Measured disk pressure is advisory for planning. Investigate disk use without '
            'deleting retained evidence. Downstream generation/delivery admission is separate.')
