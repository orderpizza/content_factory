"""Consume persisted determination handoffs into explicit content-job recipes."""

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from database.sqlite import Database
from determination.service import DeterminationService, GeminiCandidateEvaluator


def main() -> None:
    database = Database(os.getenv("CONTENT_FACTORY_DB_PATH", "data/content.db"))
    database.initialize()
    try:
        service = DeterminationService(evaluator=GeminiCandidateEvaluator())
        consumed = 0
        while service.consume_next_handoff(database) is not None:
            consumed += 1
        print(f"Determination handoffs consumed: {consumed}")
    finally:
        database.close()


if __name__ == "__main__":
    main()
