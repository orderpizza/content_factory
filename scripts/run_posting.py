"""Publish due packages through configured platform adapters."""

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from database.sqlite import Database
from posting.agent import BlueskyPublisher, PostingAgent
from posting.instagram import InstagramCarouselPublisher


def main() -> None:
    publishers = {}
    handle, password = os.getenv("BLUESKY_HANDLE"), os.getenv("BLUESKY_APP_PASSWORD")
    if handle and password:
        publishers["bluesky"] = BlueskyPublisher(handle, password)
    if os.getenv("INSTAGRAM_USER_ID") and os.getenv("INSTAGRAM_ACCESS_TOKEN"):
        publishers["instagram"] = InstagramCarouselPublisher()
    if not publishers:
        raise RuntimeError("Configure a supported publishing adapter before running the posting worker")
    database = Database(os.getenv("CONTENT_FACTORY_DB_PATH", "data/content.db"))
    database.initialize()
    try:
        agent = PostingAgent(database)
        queued = agent.queue_ready_packages()
        published = agent.publish_due(publishers)
        print(f"Posts queued: {queued}; published: {published}")
    finally:
        database.close()


if __name__ == "__main__":
    main()
