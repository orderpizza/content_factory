"""Collect one deterministic trend snapshot for local observation."""

import os
import time
import json

from common.models import utc_now
from database.sqlite import Database
from intelligence.aggregation import build_snapshots, canonical_topic
from intelligence.reporting import format_report, ranked_candidates, select_candidates
from intelligence.sources import HackerNewsSource, RedditSource, RssSource, WikimediaPageviewSource, YouTubeSource


def main() -> None:
    sources = [HackerNewsSource(), WikimediaPageviewSource()]
    feed_urls = [value.strip() for value in os.getenv("CONTENT_FACTORY_RSS_FEEDS", "").split(",") if value.strip()]
    sources.extend(RssSource(url) for url in feed_urls)
    reddit_subreddits = [value.strip() for value in os.getenv("REDDIT_SUBREDDITS", "").split(",") if value.strip()]
    if reddit_subreddits and os.getenv("REDDIT_CLIENT_ID") and os.getenv("REDDIT_CLIENT_SECRET"):
        sources.append(RedditSource(reddit_subreddits))
    if os.getenv("YOUTUBE_API_KEY"):
        sources.append(YouTubeSource(region=os.getenv("YOUTUBE_REGION", "US")))
    database = Database(os.getenv("CONTENT_FACTORY_DB_PATH", "data/content.db"))
    database.initialize()
    observed_at = utc_now()
    run_id = database.start_detection_run(observed_at)
    collected = 0
    failures = []
    try:
        observations = []
        for source in sources:
            source_name = source.__class__.__name__
            max_attempts = int(os.getenv("CONTENT_FACTORY_SOURCE_RETRIES", "3"))
            for attempt in range(1, max_attempts + 1):
                try:
                    source_observations = source.collect()
                    database.save_source_health(source_name, observed_at, True, attempt)
                    for observation in source_observations:
                        database.save_observation(observation, observed_at)
                        observations.append(observation)
                        collected += 1
                    break
                except Exception as error:  # A broken source must not stop other sources.
                    if attempt == max_attempts:
                        database.save_source_health(source_name, observed_at, False, attempt, str(error))
                        failures.append(f"{source_name}: {error}")
                    else:
                        time.sleep(min(2 ** (attempt - 1), 8))
        print(f"Scout run: {observed_at}")
        snapshots = build_snapshots(observations, observed_at)
        for snapshot in snapshots:
            database.save_topic_snapshot(snapshot)
        all_candidates = ranked_candidates(database, limit=100)
        candidate_ids = {candidate.topic: database.upsert_candidate(candidate, observed_at) for candidate in all_candidates}
        minimum_score = float(os.getenv("CONTENT_FACTORY_MINIMUM_TREND_SCORE", "0.25"))
        top_n = int(os.getenv("CONTENT_FACTORY_TOP_N_CANDIDATES", "5"))
        selected = select_candidates(database, minimum_score=minimum_score, top_n=top_n)
        database.mark_candidates_for_determination([candidate.topic for candidate in selected], observed_at)
        for candidate in selected:
            evidence = [
                {
                    "source": observation.source,
                    "source_item_id": observation.source_item_id,
                    "title": observation.title,
                    "url": observation.url,
                    "observed_at": observed_at,
                    "activity_value": observation.current_volume,
                    "baseline_value": observation.baseline_volume,
                }
                for observation in observations
                if canonical_topic(observation.topic) == candidate.topic
            ]
            payload = {
                "handoff_id": None,
                "detection_run_id": run_id,
                "created_at": observed_at,
                "candidate": {
                    "candidate_id": candidate_ids[candidate.topic],
                    "topic": candidate.topic,
                    "score": candidate.score,
                    "lifecycle_stage": candidate.lifecycle_stage,
                    "score_breakdown": candidate.score_breakdown,
                    "supporting_sources": candidate.supporting_sources,
                    "first_seen_at": candidate.first_seen_at,
                    "last_seen_at": candidate.last_seen_at,
                },
                "evidence": evidence,
                "history": [snapshot.__dict__ for snapshot in database.topic_history(candidate.topic)],
                "status": "pending",
            }
            handoff_id = database.create_handoff_if_absent(candidate_ids[candidate.topic], run_id, payload, observed_at)
            if handoff_id is not None:
                payload["handoff_id"] = handoff_id
                database.connection.execute("UPDATE determination_handoffs SET payload_json = ? WHERE handoff_id = ?", (json.dumps(payload), handoff_id))
                database.connection.commit()
        database.finish_detection_run(run_id, utc_now(), collected, len(all_candidates), len(selected))
        print(f"Observations saved: {collected}")
        print(f"Topic snapshots saved: {len(snapshots)}")
        print(f"Candidates selected for determination: {len(selected)} (top_n={top_n}, minimum_score={minimum_score:.2f})")
        print(format_report(selected))
        if failures:
            print("Source failures:")
            for failure in failures:
                print(f"- {failure}")
        else:
            print("Source failures: none")
    finally:
        database.close()


if __name__ == "__main__":
    main()
