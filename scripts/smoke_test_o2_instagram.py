"""Run an isolated o2 English Instagram integration smoke test.

The default run exercises the persisted determination handoff, real Gemini
pipeline generation, deterministic carousel rendering, and Posting Agent
queueing. It never makes an Instagram request unless ``--live`` is supplied.
"""

import argparse
import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from common.models import PostRecord, TrendCandidate, utc_now
from database.sqlite import Database
from determination.service import (
    POC_PIPELINE_CATALOG,
    CandidateEvaluator,
    Determination,
    DeterminationService,
    PipelineCapability,
)
from pipelines.o2_english.pipeline import O2EnglishInstagramPipeline
from pipelines.runner import PipelineRunner
from posting.agent import PostingAgent
from posting.instagram import InstagramCarouselPublisher
from visual.o2_english import render_and_record_idiom_carousel_png


SMOKE_TOPIC = "break the ice"


class ForceO2Evaluator(CandidateEvaluator):
    """Deterministic test evaluator that guarantees the active o2 route."""

    def evaluate(self, candidate: dict, evidence: list[dict], catalog: tuple[PipelineCapability, ...]) -> Determination:
        capability = next(item for item in catalog if item.pipeline_id == "o2_english_instagram")
        return Determination(
            should_create=True,
            pipeline=capability,
            angle="Teach a useful conversational English idiom.",
            audience="Intermediate English learners",
            objective="Teach the idiom with a concise carousel.",
            key_points=(SMOKE_TOPIC, "Use it for starting a friendly conversation."),
            sources=("https://example.invalid/smoke-test",),
            priority=100,
            reasoning="Synthetic smoke-test candidate; routed deliberately to the active o2 pipeline.",
        )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", type=Path, default=Path("data/smoke-o2-instagram.db"))
    parser.add_argument("--output", type=Path, default=Path("generated/smoke-o2-instagram"))
    parser.add_argument("--live", action="store_true", help="Allow the configured Posting Agent to publish to Instagram.")
    return parser.parse_args()


def create_handoff(database: Database) -> int:
    created_at = utc_now()
    run_id = database.start_detection_run(created_at)
    candidate = TrendCandidate(SMOKE_TOPIC, 1.0, "EMERGING", {"smoke_test": 1.0}, ["smoke_test"])
    candidate_id = database.upsert_candidate(candidate, created_at)
    payload = {
        "handoff_id": None,
        "detection_run_id": run_id,
        "created_at": created_at,
        "candidate": {
            "candidate_id": candidate_id,
            "topic": SMOKE_TOPIC,
            "score": candidate.score,
            "lifecycle_stage": candidate.lifecycle_stage,
            "score_breakdown": candidate.score_breakdown,
            "supporting_sources": candidate.supporting_sources,
            "first_seen_at": created_at,
            "last_seen_at": created_at,
        },
        "evidence": [{
            "source": "smoke_test",
            "source_item_id": "o2-instagram-1",
            "title": "Synthetic o2 English smoke-test candidate",
            "url": "https://example.invalid/smoke-test",
            "observed_at": created_at,
            "activity_value": 100,
            "baseline_value": 1,
        }],
        "history": [],
        "status": "pending",
    }
    handoff_id = database.create_handoff_if_absent(candidate_id, run_id, payload, created_at)
    if handoff_id is None:
        raise RuntimeError("The isolated smoke database unexpectedly contains an active handoff")
    payload["handoff_id"] = handoff_id
    database.connection.execute(
        "UPDATE determination_handoffs SET payload_json = ? WHERE handoff_id = ?",
        (json.dumps(payload), handoff_id),
    )
    database.connection.commit()
    database.finish_detection_run(run_id, utc_now(), 1, 1, 1)
    return handoff_id


async def run(args: argparse.Namespace) -> None:
    if args.database.exists():
        raise FileExistsError(
            f"Smoke-test database already exists: {args.database}. Choose --database with a new path; it is never overwritten."
        )
    database = Database(args.database)
    database.initialize()
    try:
        handoff_id = create_handoff(database)
        determination = DeterminationService(catalog=POC_PIPELINE_CATALOG, evaluator=ForceO2Evaluator())
        job = determination.consume_next_handoff(database)
        if job is None or job.pipeline_id != "o2_english_instagram":
            raise RuntimeError("Smoke test did not produce an o2 English ContentJob")

        runner = PipelineRunner(database, {O2EnglishInstagramPipeline.pipeline_id: O2EnglishInstagramPipeline()})
        package = runner.consume_next()
        if package is None or package.content_id is None:
            raise RuntimeError("Smoke test did not produce a persisted ContentPackage")

        assets = await render_and_record_idiom_carousel_png(database, package, args.output / f"content-{package.content_id}")
        post_id = PostingAgent(database).queue(PostRecord(package.content_id, "instagram", "o2_english"))
        print(f"Smoke handoff: {handoff_id}")
        print(f"ContentJob: {job.job_id}; ContentPackage: {package.content_id}; rendered slides: {len(assets)}")
        print(f"Post request: {post_id}; status: scheduled")

        if not args.live:
            print("Dry run complete. No external post was attempted. Re-run with --live only after Meta and public-media credentials are configured.")
            return

        published = PostingAgent(database).publish_due({"instagram": InstagramCarouselPublisher()})
        if published != 1:
            raise RuntimeError("Instagram posting did not complete; inspect the isolated smoke-test database for attempts and errors")
        record = database.connection.execute(
            "SELECT external_post_id FROM posts WHERE id = ?", (post_id,)
        ).fetchone()
        print(f"Live Instagram smoke test published: {record['external_post_id']}")
    finally:
        database.close()


if __name__ == "__main__":
    asyncio.run(run(parse_args()))
