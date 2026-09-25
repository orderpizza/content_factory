"""Sample local storage without starting a model, source, or content worker."""
from argparse import ArgumentParser
from pathlib import Path
import math
import os
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
from common.environment import load_environment_file
from common.operation_log import configure_logging, emit
from workflow import WorkflowStore
from workflow.maintenance import StorageMonitor
from database.paths import resolve_primary_database_argument


def main():
    load_environment_file(ROOT / '.env')
    parser = ArgumentParser(description=__doc__)
    parser.add_argument('--artifacts', default=os.getenv('CONTENT_FACTORY_ARTIFACT_ROOT', str(ROOT / 'data/artifacts')))
    parser.add_argument('--backups', default=os.getenv('CONTENT_FACTORY_BACKUP_ROOT', str(ROOT / 'data/backups')))
    parser.add_argument('--poll', action='store_true')
    parser.add_argument('--poll-interval', type=float, default=60)
    args = parser.parse_args()
    database = resolve_primary_database_argument(parser, ROOT / 'data')
    if not math.isfinite(args.poll_interval) or not 1 <= args.poll_interval <= 300:
        parser.error('--poll-interval must be between 1 and 300 seconds')
    configure_logging('storage')
    with WorkflowStore(database) as store:
        monitor = StorageMonitor(store, args.artifacts, args.backups)
        try:
            while True:
                sample = monitor.run_once()
                store.heartbeat('storage_monitor', 'storage-local', 'completed', f'storage sample #{sample}')
                if not args.poll:
                    break
                time.sleep(args.poll_interval)
        except KeyboardInterrupt:
            emit('storage', 'stopped', status='stopped')


if __name__ == '__main__':
    main()
