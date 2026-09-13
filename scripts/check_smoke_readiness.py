"""Report offline preview/production/delivery smoke blockers without provider calls."""

from argparse import ArgumentParser
from pathlib import Path
import json
import os
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from common.environment import load_environment_file
from workflow.preflight import inspect_smoke_readiness


def main() -> None:
    load_environment_file(ROOT / ".env")
    parser = ArgumentParser(description=__doc__)
    parser.add_argument("--database", default=os.getenv(
        "CONTENT_FACTORY_DB_PATH", str(ROOT / "data" / "content.db")
    ))
    parser.add_argument("--artifacts", default=os.getenv(
        "CONTENT_FACTORY_ARTIFACT_ROOT", str(ROOT / "data" / "artifacts")
    ))
    parser.add_argument("--backups", default=os.getenv("CONTENT_FACTORY_BACKUP_ROOT"))
    parser.add_argument(
        "--mode", choices=("preview", "production", "delivery"), default="preview",
        help="preview checks Gemini/rendering; later modes add production and delivery gates",
    )
    args = parser.parse_args()
    report = inspect_smoke_readiness(
        args.database, args.artifacts, args.backups, mode=args.mode
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))
    raise SystemExit(0 if report["status"] == "ready" else 2)


if __name__ == "__main__":
    main()
