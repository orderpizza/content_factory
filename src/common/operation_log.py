"""Allowlisted JSON diagnostics: no arbitrary messages, payloads or exception bodies."""
from datetime import datetime, timezone
from functools import wraps
from logging.handlers import RotatingFileHandler
from pathlib import Path
from time import monotonic
import json
import logging
import os
import sys

from .diagnostics import safe_diagnostic
from .timestamps import utc_now

LOGGER = logging.getLogger('content_factory.operations')
LOGGER.addHandler(logging.NullHandler())
FIELDS = set('worker instance_id operation_id record_id request_id thread_id decision_id '
             'claim_version attempt_count status duration_ms source_id scheduled_slot attempt_id '
             'complete item_count event_count evaluation_id cluster_count candidate_count selected_count '
             'skipped_count blocked_count selected_domains job_ids model_id input_tokens output_tokens '
             'total_tokens cost_micro_usd outcome error_type error_code method path http_status '
             'command_kind row_version storage_reason sample_id table_count byte_count'.split())
FIELDS.update({'lease_expires_at', 'next_attempt_at'})


def refusal_code(error):
    """Classify locally known messages without copying user/provider text."""
    message = str(error)
    for prefix, code in (
        ('storage admission refused', 'storage_gate'),
        ('thread has changed', 'row_version_conflict'),
        ('the current idea message is still being processed', 'intake_in_progress'),
        ('only an open thread', 'thread_not_open'),
        ('command ID was reused', 'command_identity_conflict'),
        ('invalid or expired dashboard command token', 'csrf_refused'),
        ('input_too_large', 'input_too_large'),
    ):
        if message.startswith(prefix):
            return code
    return 'validation_failed' if isinstance(error, ValueError) else 'operation_failed'


def emit(subsystem, event, **fields):
    record = {'timestamp': utc_now(),
              'subsystem': subsystem, 'event': event}
    for key, value in fields.items():
        if key not in FIELDS or value is None:
            continue
        if isinstance(value, (int, float, bool)):
            record[key] = value
        elif isinstance(value, (list, tuple)):
            record[key] = [x if isinstance(x,(int,float,bool)) else safe_diagnostic(x, limit=100) for x in value[:20]]
        else:
            record[key] = safe_diagnostic(value, limit=160)
    LOGGER.info(json.dumps(record, ensure_ascii=False, separators=(',', ':')))


def configure_logging(process, *, root=None, max_bytes=None, backups=None):
    # PID-scoped files avoid unsafe rotation by separate processes sharing a file.
    root = Path(root or os.getenv('CONTENT_FACTORY_LOG_ROOT', 'data/logs')).resolve()
    max_bytes = int(max_bytes or os.getenv('CONTENT_FACTORY_LOG_MAX_BYTES', '2000000'))
    backups = int(backups or os.getenv('CONTENT_FACTORY_LOG_BACKUPS', '3'))
    if not 1024 <= max_bytes <= 100000000 or not 1 <= backups <= 20:
        raise ValueError('invalid bounded diagnostic log configuration')
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    # Seven-day retention of diagnostic logs only. Never touch DB/evidence files.
    cutoff = datetime.now(timezone.utc).timestamp() - 7 * 86400
    for path in root.glob('cf-*.jsonl*'):
        if path.is_file() and not path.is_symlink() and path.stat().st_mtime < cutoff:
            path.unlink()
    path = root / f'cf-{process}-{os.getpid()}.jsonl'
    handler = RotatingFileHandler(path, maxBytes=max_bytes, backupCount=backups, encoding='utf-8')
    path.chmod(0o600)
    for old in list(LOGGER.handlers):
        old.close()
        LOGGER.removeHandler(old)
    LOGGER.addHandler(handler)
    LOGGER.addHandler(logging.StreamHandler(sys.stderr))
    LOGGER.setLevel(logging.INFO)
    LOGGER.propagate = False


def human_command(kind):
    """Log command metadata at the shared dashboard/CLI boundary, never text."""
    def decorate(function):
        @wraps(function)
        def run(self, *args, **kwargs):
            start = monotonic()
            fields = {'command_kind': kind, 'row_version': kwargs.get('expected_row_version')}
            if kind == 'continue_thread' and args:
                fields['thread_id'] = args[0]
            try:
                result = function(self, *args, **kwargs)
            except Exception as error:
                from .storage import storage_status
                emit('human_ideation', 'command', **fields, status='refused',
                     storage_reason=storage_status(self.connection)['reason'],
                     error_type=type(error).__name__, error_code=refusal_code(error), duration_ms=round((monotonic()-start)*1000))
                raise
            row = self.connection.execute('SELECT thread_id FROM intake_requests WHERE intake_request_id=?', (result,)).fetchone()
            fields['thread_id'] = row[0] if row else fields.get('thread_id')
            emit('human_ideation', 'command', **fields, request_id=result, status='accepted',
                 duration_ms=round((monotonic()-start)*1000))
            return result
        return run
    return decorate
