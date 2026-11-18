"""Inspect staged objects or authorize exact-object cleanup. Never contact providers."""
import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from workflow.offline import offline_only
from workflow.store import WorkflowStore
from workflow.resource_lifecycle import resource_report, release, schedule_safe


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--database', type=Path, required=True)
    commands = parser.add_subparsers(dest='action', required=True)
    report = commands.add_parser('report')
    report.add_argument('--attempt-id', type=int, required=True)
    automatic = commands.add_parser('schedule-safe')
    automatic.add_argument('--attempt-id', type=int, required=True)
    automatic.add_argument('--confirm-safe-policy', action='store_true')
    approve = commands.add_parser('release')
    approve.add_argument('--resource-id', type=int, required=True)
    approve.add_argument('--identity', type=Path, required=True, help='JSON containing the exact identity from the current report')
    approve.add_argument('--fingerprint', required=True)
    approve.add_argument('--expected-state', required=True)
    approve.add_argument('--command-id', required=True)
    approve.add_argument('--confirm-source-independent', action='store_true')
    args = parser.parse_args()
    if args.action == 'schedule-safe' and not args.confirm_safe_policy:
        parser.error('schedule-safe requires --confirm-safe-policy')
    with offline_only(), WorkflowStore(args.database, read_only=args.action == 'report') as store:
        if args.action == 'report':
            result = resource_report(store, args.attempt_id)
        elif args.action == 'schedule-safe':
            result = schedule_safe(store, args.attempt_id)
        else:
            result = release(store, args.resource_id, identity=json.loads(args.identity.read_text()), fingerprint=args.fingerprint,
                             expected_state=args.expected_state, command_id=args.command_id, confirm=args.confirm_source_independent)
    print(json.dumps({'result': result, 'provider_operations': False}, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
