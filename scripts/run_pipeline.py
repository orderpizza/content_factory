"""Consume persisted POC ContentJobs. Gemini metadata credentials are required."""

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from database.sqlite import Database
from pipelines.o2_english.pipeline import O2EnglishInstagramPipeline
from pipelines.poc.pipeline import PocPipeline
from pipelines.runner import PipelineRunner


def main() -> None:
    database = Database(os.getenv("CONTENT_FACTORY_DB_PATH", "data/content.db"))
    database.initialize()
    try:
        runner = PipelineRunner(database, {
            PocPipeline.pipeline_id: PocPipeline(),
            O2EnglishInstagramPipeline.pipeline_id: O2EnglishInstagramPipeline(),
        })
        produced = 0
        while runner.consume_next() is not None:
            produced += 1
        print(f"Content packages produced: {produced}")
    finally:
        database.close()


if __name__ == "__main__":
    main()
