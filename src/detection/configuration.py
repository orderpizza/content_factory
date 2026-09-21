"""Strict validation for the non-secret detection configuration release."""

from __future__ import annotations

from datetime import datetime
from common.timestamps import parse_timestamp
from pathlib import Path
from typing import Any
import json
import re
from urllib.parse import parse_qsl, urlparse

from .normalization import canonical_title


SOURCE_KINDS = {
    "publisher_feed_collector_v1",
    "wikimedia_enwiki_pageviews_v1",
    "youtube_most_popular_v1",
    "hacker_news_top_stories_v1",
}
ROOT_FIELDS = {
    "release_name", "scope_key", "schema_id", "schema_version", "created_at", "components"
}
DETECTION_FIELDS = {
    "canonicalization_version", "score_formula_version", "shortlist", "sources", "semantic_resolution"
}
SOURCE_FIELDS = {
    "stable_id", "source_kind", "adapter_version", "provider_name", "endpoint_url",
    "delivery_format", "coverage_note", "enabled", "cadence_seconds", "availability_seconds",
    "trust_weight", "independence_group", "language_scope", "region_scope", "quota_limit",
    "secret_ref", "allowed_redirect_hosts", "options",
}
SHORTLIST_VALUES = {
    "policy_version": "shortlist_v2",
    "minimum_score": 0.6,
    "minimum_reliability": 0.7,
    "max_selected_6h": 2,
    "max_selected_24h": 6,
    "deferred_fresh_hours": None,
    "cooldown_days": 3,
    "material_score_delta": 0.15,
}

class ConfigurationError(ValueError):
    """Raised when a release does not satisfy configuration_manifest_v4."""


def load_manifest(path: str | Path) -> dict[str, Any]:
    try:
        value = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ConfigurationError(f"Cannot read valid manifest JSON: {error}") from error
    validate_manifest(value)
    return value


def _exact_fields(value: dict[str, Any], fields: set[str], label: str) -> None:
    extra = set(value) - fields
    missing = fields - set(value)
    if extra or missing:
        raise ConfigurationError(
            f"{label} fields mismatch; missing={sorted(missing)}, extra={sorted(extra)}"
        )


def _require_string(value: Any, label: str, *, nullable: bool = False) -> None:
    if nullable and value is None:
        return
    if not isinstance(value, str) or not value.strip():
        raise ConfigurationError(f"{label} must be a non-empty string")


def validate_manifest(manifest: Any) -> None:
    if not isinstance(manifest, dict):
        raise ConfigurationError("Manifest root must be an object")
    _exact_fields(manifest, ROOT_FIELDS, "manifest")
    if not re.fullmatch(r"[a-z0-9][a-z0-9._-]{0,99}", str(manifest["release_name"])):
        raise ConfigurationError("release_name is invalid")
    if manifest["scope_key"] != "global":
        raise ConfigurationError("configuration_manifest_v4 supports only global scope")
    if (manifest["schema_id"], manifest["schema_version"]) != ("configuration_manifest_v4", 4):
        raise ConfigurationError("Unsupported manifest schema identity/version")
    try:
        created_at = parse_timestamp(str(manifest["created_at"]))
    except ValueError as error:
        raise ConfigurationError("created_at must be an ISO-8601 timestamp") from error

    components = manifest["components"]
    if not isinstance(components, dict) or set(components) != {"detection"}:
        raise ConfigurationError("configuration_manifest_v4 contains exactly the detection component")
    detection = components["detection"]
    if not isinstance(detection, dict):
        raise ConfigurationError("components.detection must be an object")
    _exact_fields(detection, DETECTION_FIELDS, "components.detection")
    normalization_version = "canonicalization_v2"
    if detection["canonicalization_version"] != normalization_version:
        raise ConfigurationError("Unsupported canonicalization version")
    if detection["score_formula_version"] != "attention_v3":
        raise ConfigurationError("Unsupported score formula version")
    if canonical_json(detection["shortlist"]) != canonical_json(SHORTLIST_VALUES):
        raise ConfigurationError("shortlist does not match the supported policy for this release")
    _validate_semantic(detection["semantic_resolution"])

    sources = detection["sources"]
    if not isinstance(sources, list) or not 1 <= len(sources) <= 32:
        raise ConfigurationError("At least one detection source is required")
    stable_ids: set[str] = set()
    for source in sources:
        _validate_source(source)
        if source["stable_id"] in stable_ids:
            raise ConfigurationError(f"Duplicate source stable_id: {source['stable_id']}")
        stable_ids.add(source["stable_id"])


def _validate_semantic(policy: Any) -> None:
    fields = {"model_id", "model_revision", "dimensions", "cpu_threads", "batch_size",
              "recent_hours", "max_pair_hours", "max_clusters", "max_pairs", "max_neighbors",
              "max_group_size", "similarity_decimals", "link_threshold", "separate_threshold",
              "entity_aliases", "entity_stopwords", "negation_terms", "event_terms"}
    if not isinstance(policy, dict):
        raise ConfigurationError("semantic_resolution must be an object")
    _exact_fields(policy, fields, "semantic_resolution")
    if policy["model_id"] != "sentence-transformers/all-MiniLM-L6-v2" or policy["dimensions"] != 384:
        raise ConfigurationError("semantic_resolution requires the supported 384-dimensional MiniLM model")
    if not isinstance(policy["model_revision"], str) or not re.fullmatch(r"[a-f0-9]{40}", policy["model_revision"]):
        raise ConfigurationError("semantic model revision must be a pinned commit SHA")
    limits = {"cpu_threads": 4, "batch_size": 64, "recent_hours": 168, "max_pair_hours": 72,
              "max_clusters": 1024, "max_pairs": 16384, "max_neighbors": 64, "max_group_size": 16,
              "similarity_decimals": 9}
    for key, ceiling in limits.items():
        if type(policy[key]) is not int or not 1 <= policy[key] <= ceiling:
            raise ConfigurationError(f"semantic {key} is outside the supported resource envelope")
    if policy["max_pair_hours"] > policy["recent_hours"]:
        raise ConfigurationError("semantic pair window cannot exceed candidate recency")
    for key in ("link_threshold", "separate_threshold"):
        if type(policy[key]) not in (int, float) or not 0 <= policy[key] <= 1:
            raise ConfigurationError(f"semantic {key} must be a finite similarity")
    if policy["separate_threshold"] >= policy["link_threshold"]:
        raise ConfigurationError("semantic separate threshold must be below link threshold")
    for key in ("entity_stopwords", "negation_terms"):
        words = policy[key]
        if not isinstance(words, list) or not words or len(words) > 500 or any(not isinstance(w, str) or not w or w != w.casefold() for w in words) or len(set(words)) != len(words):
            raise ConfigurationError(f"semantic {key} must contain unique lowercase words")
    aliases = policy["entity_aliases"]
    if not isinstance(aliases, dict) or len(aliases) > 500 or any(not isinstance(k, str) or not isinstance(v, str) or not k or not v or k != k.casefold() or v != v.casefold() for k, v in aliases.items()):
        raise ConfigurationError("semantic entity_aliases must be a bounded lowercase mapping")
    events = policy["event_terms"]
    if not isinstance(events, dict) or not 1 <= len(events) <= 50:
        raise ConfigurationError("semantic event_terms must be a bounded action vocabulary")
    seen = set()
    for kind, words in events.items():
        if not isinstance(kind, str) or not kind or not isinstance(words, list) or not 1 <= len(words) <= 100:
            raise ConfigurationError("invalid semantic event category")
        for word in words:
            if not isinstance(word, str) or not word or word != word.casefold() or word in seen:
                raise ConfigurationError("semantic event terms must be unique lowercase words")
            seen.add(word)


def _validate_source(source: Any) -> None:
    if not isinstance(source, dict):
        raise ConfigurationError("Every source must be an object")
    _exact_fields(source, SOURCE_FIELDS, "source")
    if not re.fullmatch(r"[a-z0-9][a-z0-9_]{0,99}", str(source["stable_id"])):
        raise ConfigurationError("Source stable_id is invalid")
    if not isinstance(source["source_kind"], str) or source["source_kind"] not in SOURCE_KINDS:
        raise ConfigurationError(f"Unsupported source kind: {source['source_kind']}")
    for key in ("adapter_version", "provider_name", "coverage_note", "independence_group"):
        _require_string(source[key], key)
    try:
        parsed = urlparse(str(source["endpoint_url"]))
        parsed.port
    except ValueError as error:
        raise ConfigurationError("Source endpoint_url is malformed") from error
    if parsed.scheme != "https" or not parsed.hostname:
        raise ConfigurationError("Source endpoint_url must be absolute HTTPS")
    sensitive = {"key", "api_key", "apikey", "token", "access_token", "password", "signature", "credential"}
    if (parsed.username is not None or parsed.password is not None or parsed.fragment
            or any(key.casefold() in sensitive or key.casefold().startswith("x-amz-") for key, _ in parse_qsl(parsed.query))):
        raise ConfigurationError("Source endpoint_url must not contain credentials, signed parameters or fragments")
    if source["delivery_format"] not in ("rss", "atom", "json", None):
        raise ConfigurationError("Unsupported delivery_format")
    if not isinstance(source["enabled"], bool):
        raise ConfigurationError("Source enabled must be boolean")
    for key in ("cadence_seconds", "availability_seconds"):
        if type(source[key]) is not int or not 60 <= source[key] <= 172800:
            raise ConfigurationError(f"{key} is out of range")
    if type(source["trust_weight"]) not in (int, float) or not 0 <= source["trust_weight"] <= 1:
        raise ConfigurationError("trust_weight must be between 0 and 1")
    for key in ("language_scope", "region_scope", "secret_ref"):
        _require_string(source[key], key, nullable=True)
    quota = source["quota_limit"]
    if quota is not None and (type(quota) is not int or quota <= 0):
        raise ConfigurationError("quota_limit must be null or positive")
    hosts = source["allowed_redirect_hosts"]
    if not isinstance(hosts, list) or not all(isinstance(host, str) and host for host in hosts):
        raise ConfigurationError("allowed_redirect_hosts must be an array of host names")
    normalized_hosts = []
    for host in hosts:
        normalized = host.casefold()
        if (
            normalized != host
            or not re.fullmatch(r"[a-z0-9.-]+", normalized)
            or normalized.startswith((".", "-"))
            or normalized.endswith((".", "-"))
            or ".." in normalized
        ):
            raise ConfigurationError("allowed_redirect_hosts must contain lowercase DNS names")
        normalized_hosts.append(normalized)
    if len(set(normalized_hosts)) != len(normalized_hosts):
        raise ConfigurationError("allowed_redirect_hosts cannot contain duplicates")
    if parsed.hostname.casefold() not in normalized_hosts:
        raise ConfigurationError("endpoint_url host must be explicitly allowlisted")
    if not isinstance(source["options"], dict):
        raise ConfigurationError("source options must be an object")

    kind = source["source_kind"]
    options = source["options"]
    expected: dict[str, Any]
    if kind == "publisher_feed_collector_v1":
        expected = {"max_items": 100}
        if source["delivery_format"] not in {"rss", "atom"}:
            raise ConfigurationError("Publisher feed must declare rss or atom")
    elif kind == "wikimedia_enwiki_pageviews_v1":
        if source["delivery_format"] != "json":
            raise ConfigurationError("Wikimedia source must declare json")
        expected = {
            "max_items": 1000,
            "project": "en.wikipedia.org",
            "access": "all-access",
            "agent": "all-agents",
        }
    elif kind == "youtube_most_popular_v1":
        if source["delivery_format"] != "json":
            raise ConfigurationError("YouTube source must declare json")
        expected = {"max_items": 50, "region_code": "US", "parts": ["snippet", "statistics"]}
        if source["quota_limit"] != 1000 or source["secret_ref"] != "YOUTUBE_API_KEY":
            raise ConfigurationError("YouTube v1 requires its documented quota and secret reference")
    else:
        if source["delivery_format"] != "json":
            raise ConfigurationError("Hacker News source must declare json")
        expected = {"max_items": 100}
    if options != expected:
        raise ConfigurationError(f"Options for {kind} must exactly match its v1 contract")


def canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
