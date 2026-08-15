"""Collect one deterministic trend snapshot for local observation."""

import os
import time

from common.models import utc_now
from database.sqlite import Database
from intelligence.aggregation import build_snapshots
from intelligence.reporting import ranked_candidates
from intelligence.sources import HackerNewsSource, RssSource, WikimediaPageviewSource


def main() -> None:
    sources = [HackerNewsSource(), WikimediaPageviewSource()]
    feed_urls = [value.strip() for value in os.getenv("CONTENT_FACTORY_RSS_FEEDS", "").split(",") if value.strip()]
    sources.extend(RssSource(url) for url in feed_urls)
    database = Database(os.getenv("CONTENT_FACTORY_DB_PATH", "data/content.db"))
    database.initialize()
    observed_at = utc_now()
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
        for candidate in ranked_candidates(database, limit=100):
            database.upsert_candidate(candidate, observed_at)
        print(f"Observations saved: {collected}")
        print(f"Topic snapshots saved: {len(snapshots)}")
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
