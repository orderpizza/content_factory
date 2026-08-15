"""Normalize observations and build explainable topic snapshots."""

import re
from collections import defaultdict

from common.models import TopicSnapshot
from intelligence.sources import Observation

STOPWORDS = {"a", "an", "and", "are", "as", "at", "by", "for", "from", "in", "is", "of", "on", "the", "to", "with", "after", "before", "says", "new"}


def canonical_topic(value: str) -> str:
    value = re.sub(r"[^a-z0-9 ]+", " ", value.lower())
    return re.sub(r"\s+", " ", value).strip()


def topic_tokens(value: str) -> set[str]:
    tokens = {token for token in canonical_topic(value).split() if token not in STOPWORDS and len(token) > 2}
    return {_stem(token) for token in tokens}


def _stem(token: str) -> str:
    for suffix in ("ing", "ers", "ies", "es", "s"):
        if token.endswith(suffix) and len(token) - len(suffix) >= 4:
            return token[:-len(suffix)]
    return token


def _related(left: set[str], right: set[str]) -> bool:
    if not left or not right:
        return False
    overlap = len(left & right)
    return overlap >= 2 and overlap / min(len(left), len(right)) >= 0.5


def build_snapshots(observations: list[Observation], observed_at: str) -> list[TopicSnapshot]:
    grouped: dict[str, list[Observation]] = defaultdict(list)
    for observation in observations:
        tokens = topic_tokens(observation.topic)
        matching_topic = next((topic for topic, items in grouped.items() if _related(tokens, topic_tokens(items[0].topic))), None)
        topic = matching_topic or canonical_topic(observation.topic)
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
