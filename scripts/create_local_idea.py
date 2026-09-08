"""Create a durable local human-idea → IntakeRequest handoff in workflow v2."""

from __future__ import annotations

from argparse import ArgumentParser
from pathlib import Path
import os
import sys
import uuid

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from workflow import WorkflowStore

ROOT = Path(__file__).resolve().parents[1]


def main() -> None:
    parser = ArgumentParser(description=__doc__)
    parser.add_argument("message")
    parser.add_argument("--database", default=os.getenv("CONTENT_FACTORY_DB_PATH", str(ROOT / "data" / "content.db")))
    parser.add_argument("--command-id", default=None, help="Reuse this UUID to safely retry the same command.")
    args = parser.parse_args()
    command_id = args.command_id or str(uuid.uuid4())
    with WorkflowStore(args.database) as store:
        request_id = store.create_human_idea(args.message, command_id=command_id)
    print(f"Intake request: {request_id}; command ID: {command_id}")


if __name__ == "__main__":
    main()
