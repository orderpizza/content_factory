"""Normalize observations and build explainable topic snapshots."""

import re
from collections import defaultdict

from common.models import TopicSnapshot
from intelligence.sources import Observation


def canonical_topic(value: str) -> str:
    value = re.sub(r"[^a-z0-9 ]+", " ", value.lower())
    return re.sub(r"\s+", " ", value).strip()


def build_snapshots(observations: list[Observation], observed_at: str) -> list[TopicSnapshot]:
    grouped: dict[str, list[Observation]] = defaultdict(list)
    for observation in observations:
        topic = canonical_topic(observation.topic)
        if topic:
            grouped[topic].append(observation)
    return [TopicSnapshot(
        topic=topic,
        observed_at=observed_at,
        activity=sum(item.current_volume for item in items),
        source_count=len({item.source for item in items}),
        mention_count=len(items),
        sources=sorted({item.source for item in items}),
    ) for topic, items in grouped.items()]
