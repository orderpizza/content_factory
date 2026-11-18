"""Offline observations and read-only JSON reporting; never calls a provider."""
import argparse
from dataclasses import asdict
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from workflow.measurement import Observation, ingest_offline
from workflow.measurement_report import operator_report
from workflow.offline import offline_only
from workflow.store import WorkflowStore, digest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='command', required=True)
    demo = commands.add_parser('synthetic-demo', help='new isolated temporary database; no approval or publishing')
    demo.add_argument('--workspace', type=Path)
    demo.add_argument('--slides', type=int, choices=(4, 5, 6), default=6)
    for name in ('ingest', 'report'):
        command = commands.add_parser(name)
        command.add_argument('--database', type=Path, required=True)
        if name == 'ingest':
            command.add_argument('--observations', type=Path, required=True)
            command.add_argument('--append-offline-observations', action='store_true', required=True,
                                 help='explicit append to this database; never authenticates fixtures')
        else:
            command.add_argument('--destination-id', type=int, required=True)
            command.add_argument('--start', required=True)
            command.add_argument('--end', required=True)
            command.add_argument('--as-of', help='metric fetched-time cutoff; funnel/costs remain current')
    args = parser.parse_args()
    with offline_only():
        if args.command == 'synthetic-demo':
            from workflow.delivery_simulation import initialize_simulation, simulation_store
            root = initialize_simulation(args.workspace, slide_count=args.slides)
            with simulation_store(root) as store:
                dest = dict(store.connection.execute('SELECT * FROM social_destinations').fetchone())
                observation = Observation(
                    source_key='synthetic-demo-account-reach', social_destination_id=dest['social_destination_id'],
                    account_key=dest['account_key'], provider_account_id=dest['provider_account_id'],
                    definition_version='synthetic_insights_v1', metric='reach', unit='count', scope='account',
                    provenance='synthetic', value_status='known', value=123,
                    window_start='2026-11-01T00:00:00', window_end='2026-11-02T00:00:00',
                    observed_at='2026-11-02T00:00:00', fetched_at='2026-11-02T01:00:00',
                    provider='synthetic', api_version='fixture-v1', login='fixture', capability='synthetic_insights_v1',
                    source_response_hash=digest({'synthetic_reach': 123}), evidence_ref='synthetic-demo-v1')
                ingest_offline(store, [observation])
            (root / 'synthetic-observations.json').write_text(json.dumps([asdict(observation)], indent=2) + '\n')
            result = {'workspace': str(root), 'database': str(root / 'simulation.sqlite'),
                      'destination_id': dest['social_destination_id'], 'provenance': 'synthetic',
                      'notice': 'No review approval, Post now or publication performed.'}
        elif args.command == 'ingest':
            if args.observations.stat().st_size > 1_000_000:
                raise ValueError('observation batch exceeds 1 MB')
            values = json.loads(args.observations.read_text())
            if not isinstance(values, list) or not 1 <= len(values) <= 1000:
                raise ValueError('expected 1–1000 observation objects')
            observations = [Observation(**value) for value in values]
            with WorkflowStore(args.database) as store:
                result = {'observation_ids': ingest_offline(store, observations), 'interface': 'offline_only'}
        else:
            with WorkflowStore(args.database, read_only=True) as store:
                result = operator_report(store, args.destination_id, args.start, args.end, as_of=args.as_of)
        print(json.dumps(result, indent=2, ensure_ascii=False))


if __name__ == '__main__':
    main()
