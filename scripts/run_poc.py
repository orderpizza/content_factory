"""Run an offline fixture demonstration, not the persisted production path."""

from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from common.models import PostRecord
from database.sqlite import Database
from determination.service import DeterminationService
from intelligence.detector import TrendDetector
from intelligence.sources import FixtureTrendSource, Observation
from pipelines.poc.pipeline import PocPipeline
from posting.agent import PostingAgent
from visual.renderer import VisualRenderer


def main() -> None:
    database = Database(Path("data/content.db"))
    database.initialize()
    try:
        trend = TrendDetector(FixtureTrendSource([
            Observation("rapid topic", "Rapid Topic", "fixture", 4000, 500),
        ])).detect()[0]
        trend.id = database.save_trend(trend)
        job = DeterminationService().determine(trend)
        if job is None:
            print("Trend was not selected for content.")
            return
        job.job_id = database.save_content_job(job)
        package = PocPipeline().run(job)
        package.content_id = database.save_content_package(package)
        html_path = VisualRenderer().render_html(package, Path("generated/poc-card.html"))
        post_id = PostingAgent(database).queue(PostRecord(package.content_id, "test", "local"))
        PostingAgent(database).mark_published(post_id, f"offline-{post_id}")
        print(f"Published offline post {post_id}; visual asset: {html_path}")
    finally:
        database.close()


if __name__ == "__main__":
    main()
