"""Persist local or explicitly authorized live production-readiness checks."""

from argparse import ArgumentParser
from pathlib import Path
import json
import os
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from common.environment import load_environment_file
from database.migrations import SchemaError, validate_production_workflow
from workflow import WorkflowStore
from workflow.readiness import CapabilityReadinessMonitor


def main() -> None:
    load_environment_file(ROOT / ".env")
    parser = ArgumentParser(description=__doc__)
    parser.add_argument("--database", default=os.getenv(
        "CONTENT_FACTORY_DB_PATH", str(ROOT / "data" / "content.db")
    ))
    parser.add_argument(
        "--live", action="store_true",
        help="perform read-only Meta/X checks and, for Instagram, the separately confirmed R2 probe",
    )
    parser.add_argument(
        "--confirm-transient-r2-write", action="store_true",
        help="allow one random R2 put/head/public-get/delete readiness probe; never posts publicly",
    )
    parser.add_argument(
        "--only-due", action="store_true",
        help="reuse still-current persisted results; intended for an explicitly installed scheduler",
    )
    args = parser.parse_args()
    if args.confirm_transient_r2_write and not args.live:
        parser.error("--confirm-transient-r2-write requires --live")
    try:
        with WorkflowStore(args.database, catalog_kind="production") as store:
            validate_production_workflow(store.connection)
            store.heartbeat(
                "capability_readiness", "capability-readiness-v1", "polling",
                "destination readiness poll started",
            )
            try:
                result = CapabilityReadinessMonitor(store).run(
                    live=args.live, confirm_r2_probe=args.confirm_transient_r2_write,
                    only_due=args.only_due,
                )
            except Exception as error:
                store.heartbeat(
                    "capability_readiness", "capability-readiness-v1", "failed",
                    f"destination readiness poll failed ({type(error).__name__})",
                )
                raise
            blocked = sum(item["status"] != "ready" for item in result)
            store.heartbeat(
                "capability_readiness", "capability-readiness-v1",
                "completed" if blocked == 0 else "blocked",
                f"checked {len(result)} destination(s); blocked={blocked}",
            )
    except (SchemaError, RuntimeError, ValueError) as error:
        raise SystemExit(f"Production readiness refused: {error}")
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
