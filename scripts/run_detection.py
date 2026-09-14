"""Run due source collection and one deterministic Scout evaluation."""

from __future__ import annotations

from argparse import ArgumentParser
from pathlib import Path
import json
import os
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from common.environment import load_environment_file
from detection import DetectionCollector, DetectionScout
from detection.reporting import summarize_scout
from detection.store import DetectionStore


ROOT = Path(__file__).resolve().parents[1]


def main() -> None:
    load_environment_file(ROOT / ".env")
    parser = ArgumentParser(description=__doc__)
    parser.add_argument(
        "--database",
        default=os.getenv("CONTENT_FACTORY_DB_PATH", str(ROOT / "data" / "content.db")),
    )
    parser.add_argument("--source", action="append", dest="sources", help="Run only this stable source ID; repeatable.")
    parser.add_argument("--force", action="store_true", help="Materialize/claim the current source cadence slots even after an idle check.")
    parser.add_argument("--skip-collection", action="store_true")
    parser.add_argument("--skip-scout", action="store_true")
    args = parser.parse_args()
    with DetectionStore(args.database) as store:
        collection = []
        if not args.skip_collection:
            collection = DetectionCollector(store).run_due(
                source_ids=set(args.sources) if args.sources else None,
                force=args.force,
            )
        scout = None
        if not args.skip_scout:
            scout = DetectionScout(store).run()
        if scout is not None:
            scout = summarize_scout(store, scout)
    print(json.dumps({"collection": collection, "scout": scout}, indent=2, default=str))


if __name__ == "__main__":
    main()
