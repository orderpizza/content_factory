"""Daily size-only measurement; no payload export, compaction or deletion."""
from time import monotonic
import sqlite3


def measure_tables(connection, *, max_seconds=5.0):
    started = monotonic()
    report = {'tables': {}, 'complete': True, 'measurement_limit_seconds': max_seconds}
    connection.set_progress_handler(lambda: int(monotonic()-started > max_seconds), 10000)
    try:
        connection.execute('BEGIN')
        tables = connection.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name").fetchall()
        for (table,) in tables:
            if monotonic()-started >= max_seconds:
                report.update(complete=False, error_code='measurement_time_limit')
                break
            quoted = '"' + table.replace('"', '""') + '"'
            columns = [r[1] for r in connection.execute(f'PRAGMA table_info({quoted})') if r[1].endswith('_json')]
            sums = [f'COALESCE(SUM(length(CAST("{c}" AS BLOB))),0)' for c in columns]
            row = connection.execute('SELECT COUNT(*)' + (',' + ','.join(sums) if sums else '') + f' FROM {quoted}').fetchone()
            report['tables'][table] = {'rows': row[0], 'json_bytes': dict(zip(columns, row[1:]))}
    except sqlite3.OperationalError:
        report['complete'] = False
        report['error_code'] = 'measurement_interrupted'
    finally:
        connection.set_progress_handler(None, 0)
        connection.rollback()
    report['duration_ms'] = round((monotonic()-started)*1000)
    return report
