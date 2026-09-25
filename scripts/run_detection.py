"""Run due source collection and one deterministic Scout evaluation."""

from __future__ import annotations

from argparse import ArgumentParser
from pathlib import Path
import sys
import time
import math

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from common.environment import load_environment_file
from common.operation_log import configure_logging, emit
from database.paths import resolve_primary_database_argument
from detection import DetectionCollector, DetectionScout
from detection.reporting import summarize_scout
from detection.store import DetectionStore


ROOT = Path(__file__).resolve().parents[1]


def main() -> None:
    load_environment_file(ROOT / ".env")
    parser = ArgumentParser(description=__doc__)
    parser.add_argument("--source", action="append", dest="sources", help="Run only this stable source ID; repeatable.")
    parser.add_argument("--force", action="store_true", help="Materialize/claim the current source cadence slots even after an idle check.")
    parser.add_argument("--skip-collection", action="store_true")
    parser.add_argument("--skip-scout", action="store_true")
    parser.add_argument("--poll", action="store_true", help="repeat due collection and Scout checks until Ctrl+C")
    parser.add_argument("--poll-interval", type=float, default=30.0)
    args = parser.parse_args()
    database = resolve_primary_database_argument(parser, ROOT / "data")
    configure_logging('detection')
    if not math.isfinite(args.poll_interval) or args.poll_interval <= 0:
        parser.error("--poll-interval must be finite and positive")
    with DetectionStore(database) as store:
        collector, resolver = DetectionCollector(store), DetectionScout(store)
        try:
            while True:
                run_pass(store, collector, resolver, args)
                if not args.poll:
                    break
                time.sleep(args.poll_interval)
        except KeyboardInterrupt:
            print("Detection poller stopped.")


def run_pass(store, collector, resolver, args):
    collection = []
    if not args.skip_collection:
        collection = collector.run_due(source_ids=set(args.sources) if args.sources else None, force=args.force)
    scout = None
    if not args.skip_scout:
        scout = resolver.run()
    if scout is not None:
        scout = summarize_scout(store, scout)
    emit('detection', 'poll', item_count=len(collection), status='completed',
         evaluation_id=scout.get('run_id') if isinstance(scout, dict) else None)


if __name__ == "__main__":
    main()
