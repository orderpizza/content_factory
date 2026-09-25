"""Report offline planning/preview smoke blockers without provider calls."""

from argparse import ArgumentParser
from pathlib import Path
import json
import os
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from common.environment import load_environment_file
from workflow.preflight import inspect_smoke_readiness
from database.paths import resolve_primary_database_argument


def main() -> None:
    load_environment_file(ROOT / ".env")
    parser = ArgumentParser(description=__doc__)
    parser.add_argument("--artifacts", default=os.getenv(
        "CONTENT_FACTORY_ARTIFACT_ROOT", str(ROOT / "data" / "artifacts")
    ))
    parser.add_argument(
        "--mode", choices=("planning", "preview"), default="planning",
        help="planning checks local planning; preview checks Gemini/rendering",
    )
    args = parser.parse_args()
    database = resolve_primary_database_argument(parser, ROOT / "data")
    report = inspect_smoke_readiness(
        database, args.artifacts, mode=args.mode
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))
    raise SystemExit(0 if report["status"] == "ready" else 2)


if __name__ == "__main__":
    main()
