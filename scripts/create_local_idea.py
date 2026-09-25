"""Start or continue a durable human idea conversation in workflow."""

from __future__ import annotations

from argparse import ArgumentParser
from pathlib import Path
import sys
import uuid

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from common.environment import load_environment_file
from common.operation_log import configure_logging
from database.paths import resolve_primary_database_argument
from workflow import WorkflowStore

ROOT = Path(__file__).resolve().parents[1]


def main() -> None:
    load_environment_file(ROOT / ".env")
    parser = ArgumentParser(description=__doc__)
    parser.add_argument("message", help="Free-text idea or refinement message.")
    parser.add_argument("--command-id", default=None, help="Reuse this UUID to safely retry the same command.")
    parser.add_argument("--thread-id", type=int, help="Continue this open thread instead of starting a new idea.")
    parser.add_argument("--row-version", type=int, help="Displayed thread version; required with --thread-id.")
    args = parser.parse_args()
    database = resolve_primary_database_argument(parser, ROOT / "data")
    configure_logging('human-idea')
    if args.thread_id is not None and (args.row_version is None or args.row_version < 1):
        parser.error("--thread-id requires a positive displayed --row-version")
    command_id = args.command_id or str(uuid.uuid4())
    with WorkflowStore(database, enforce_storage=True) as store:
        if args.thread_id is None:
            request_id = store.create_human_idea(args.message, command_id=command_id)
            action = "New idea"
        else:
            request_id = store.continue_human_thread(
                args.thread_id, args.message, command_id=command_id, expected_row_version=args.row_version
            )
            action = f"Thread {args.thread_id} refinement"
    print(f"{action}; Intake request: {request_id}; command ID: {command_id}")


if __name__ == "__main__":
    main()
