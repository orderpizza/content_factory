"""Strict validation for the non-secret detection configuration release."""

from __future__ import annotations

from datetime import datetime
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
    "canonicalization_version", "score_formula_version", "shortlist", "sources", "cluster_aliases"
}
SOURCE_FIELDS = {
    "stable_id", "source_kind", "adapter_version", "provider_name", "endpoint_url",
    "delivery_format", "coverage_note", "enabled", "cadence_seconds", "availability_seconds",
    "trust_weight", "independence_group", "language_scope", "region_scope", "quota_limit",
    "secret_ref", "allowed_redirect_hosts", "options",
}
SHORTLIST_VALUES = {
    "policy_version": "shortlist_v1",
    "minimum_score": 0.6,
    "minimum_reliability": 0.7,
    "max_selected_6h": 2,
    "max_selected_24h": 6,
    "deferred_fresh_hours": 48,
    "cooldown_days": 3,
    "material_score_delta": 0.15,
}


class ConfigurationError(ValueError):
    """Raised when a release does not satisfy configuration_manifest_v1."""


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
        raise ConfigurationError("configuration_manifest_v1 supports only global scope")
    if not isinstance(manifest["schema_id"], str) or type(manifest["schema_version"]) is not int or (manifest["schema_id"], manifest["schema_version"]) not in {("configuration_manifest_v1", 1), ("configuration_manifest_v2", 2), ("configuration_manifest_v3", 3)}:
        raise ConfigurationError("Unsupported manifest schema identity/version")
    try:
        created_at = datetime.fromisoformat(
            str(manifest["created_at"]).replace("Z", "+00:00")
        )
    except ValueError as error:
        raise ConfigurationError("created_at must be an ISO-8601 timestamp") from error
    if created_at.tzinfo is None or created_at.utcoffset().total_seconds() != 0:
        raise ConfigurationError("created_at must be an explicitly UTC timestamp")

    components = manifest["components"]
    if not isinstance(components, dict) or set(components) != {"detection"}:
        raise ConfigurationError("configuration_manifest_v1 contains exactly the detection component")
    detection = components["detection"]
    if not isinstance(detection, dict):
        raise ConfigurationError("components.detection must be an object")
    _exact_fields(detection, DETECTION_FIELDS, "components.detection")
    normalization_version = "canonicalization_v2" if manifest["schema_version"] == 3 else "canonicalization_v1"
    if detection["canonicalization_version"] != normalization_version:
        raise ConfigurationError("Unsupported canonicalization version")
    if detection["score_formula_version"] != ("attention_v2" if manifest["schema_version"] >= 2 else "attention_v1"):
        raise ConfigurationError("Unsupported score formula version")
    if canonical_json(detection["shortlist"]) != canonical_json(SHORTLIST_VALUES):
        raise ConfigurationError("shortlist must exactly match shortlist_v1")
    if not isinstance(detection["cluster_aliases"], list) or len(detection["cluster_aliases"]) > 500:
        raise ConfigurationError("cluster_aliases must be an array")
    alias_targets: dict[str, str] = {}
    seen_aliases: set[str] = set()
    for alias in detection["cluster_aliases"]:
        if not isinstance(alias, dict) or set(alias) != {"alias_key", "target_cluster_key", "active", "reason"}:
            raise ConfigurationError("Every cluster alias must use the exact v1 fields")
        _require_string(alias["alias_key"], "alias_key")
        _require_string(alias["target_cluster_key"], "target_cluster_key")
        _require_string(alias["reason"], "alias reason")
        if not isinstance(alias["active"], bool):
            raise ConfigurationError("alias active must be boolean")
        if canonical_title(alias["alias_key"], normalization_version) != alias["alias_key"]:
            raise ConfigurationError("alias_key must already be canonicalization_v1 normalized")
        if canonical_title(alias["target_cluster_key"], normalization_version) != alias["target_cluster_key"]:
            raise ConfigurationError(
                "target_cluster_key must already be canonicalization_v1 normalized"
            )
        if alias["alias_key"] in seen_aliases:
            raise ConfigurationError(f"Duplicate alias_key: {alias['alias_key']}")
        seen_aliases.add(alias["alias_key"])
        if alias["active"]:
            if alias["alias_key"] == alias["target_cluster_key"]:
                raise ConfigurationError("An active cluster alias cannot target itself")
            alias_targets[alias["alias_key"]] = alias["target_cluster_key"]
    for start in alias_targets:
        visited: set[str] = set()
        current = start
        while current in alias_targets:
            if current in visited:
                raise ConfigurationError("Active cluster aliases cannot contain a cycle")
            visited.add(current)
            current = alias_targets[current]

    sources = detection["sources"]
    if not isinstance(sources, list) or not 1 <= len(sources) <= 32:
        raise ConfigurationError("At least one detection source is required")
    stable_ids: set[str] = set()
    for source in sources:
        _validate_source(source)
        if source["stable_id"] in stable_ids:
            raise ConfigurationError(f"Duplicate source stable_id: {source['stable_id']}")
        stable_ids.add(source["stable_id"])


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
