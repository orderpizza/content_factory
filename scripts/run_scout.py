"""Collect one deterministic trend snapshot for local observation."""

import os

from common.models import utc_now
from database.sqlite import Database
from intelligence.aggregation import build_snapshots
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
            try:
                for observation in source.collect():
                    database.save_observation(observation, observed_at)
                    observations.append(observation)
                    collected += 1
            except Exception as error:  # A broken feed must not stop other sources.
                failures.append(f"{source.__class__.__name__}: {error}")
        print(f"Scout run: {observed_at}")
        snapshots = build_snapshots(observations, observed_at)
        for snapshot in snapshots:
            database.save_topic_snapshot(snapshot)
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
