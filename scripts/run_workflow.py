"""Run one polling pass of every local v2 workflow worker.

All default policies are local placeholders.  This command never calls Gemini
or a social platform; the Posting Agent records its disabled safety outcome.
"""

from __future__ import annotations

from argparse import ArgumentParser
from pathlib import Path
import os
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from common.environment import load_environment_file
from database.migrations import SchemaError
from workflow import AdaptationWorker, DeterminationWorker, IdeaIntakeWorker, PipelineRunner, PostingAgent, VisualRenderer, WorkflowStore

ROOT = Path(__file__).resolve().parents[1]


def main() -> None:
    load_environment_file(ROOT / ".env")
    parser = ArgumentParser(description=__doc__)
    parser.add_argument("--database", default=os.getenv("CONTENT_FACTORY_DB_PATH", str(ROOT / "data" / "content.db")))
    parser.add_argument("--artifacts", default=os.getenv("CONTENT_FACTORY_ARTIFACT_ROOT", str(ROOT / "data" / "artifacts")))
    args = parser.parse_args()
    try:
        with WorkflowStore(args.database) as store:
            workers = (
                IdeaIntakeWorker(store), DeterminationWorker(store), PipelineRunner(store),
                AdaptationWorker(store), VisualRenderer(store, args.artifacts), PostingAgent(store),
            )
            for worker in workers:
                result = worker.run_once()
                print(f"{worker.__class__.__name__}: {'no output (idle, clarification, cancellation or failure; see dashboard)' if result is None else result}")
    except SchemaError as error:
        raise SystemExit(f"Workflow worker refused: {error}")


if __name__ == "__main__":
    main()
