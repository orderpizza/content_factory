"""Consume persisted IntakeRequests into immutable briefs."""

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from database.sqlite import Database
from intake.service import GeminiIntakeEvaluator, IdeaIntakeService


def main() -> None:
    from common.legacy import refuse_legacy_operation
    refuse_legacy_operation("run_intake.py")
    database = Database(os.getenv("CONTENT_FACTORY_DB_PATH", "data/content.db"))
    database.initialize()
    try:
        service = IdeaIntakeService(evaluator=GeminiIntakeEvaluator())
        consumed = 0
        while service.consume_next_request(database) is not None:
            consumed += 1
        print(f"Idea Intake requests consumed: {consumed}")
    finally:
        database.close()


if __name__ == "__main__":
    main()
