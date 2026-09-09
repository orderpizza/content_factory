"""Versioned deterministic normalization used by collection and scouting."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from urllib.parse import parse_qsl, quote, urlencode, urlsplit, urlunsplit
import re
import unicodedata


TRACKING_PARAMETERS = {"gclid", "fbclid", "mc_cid", "mc_eid", "_ga"}
APOSTROPHES = {"’", "‘", "‛", "＇", "`"}
DASHES = {"‐", "‑", "‒", "–", "—", "―", "﹘", "﹣", "－"}


def canonical_title(value: str, version: str = "canonicalization_v1") -> str:
    if version not in {"canonicalization_v1", "canonicalization_v2"}:
        raise ValueError("unsupported canonicalization version")
    normalized = unicodedata.normalize("NFKC", value).casefold()
    if version == "canonicalization_v2":
        normalized = "".join("'" if c in APOSTROPHES else "-" if c in DASHES else c for c in normalized)
    characters: list[str] = []
    for character in normalized:
        if character in APOSTROPHES:
            characters.append("'")
        elif character in DASHES:
            characters.append("-")
        elif character == "&":
            characters.append(" and ")
        elif unicodedata.category(character)[0] in {"L", "N"}:
            characters.append(character)
        else:
            characters.append(" ")
    return re.sub(r"\s+", " ", "".join(characters)).strip()


def canonical_link(value: str, version: str = "canonicalization_v1") -> str | None:
    if version not in {"canonicalization_v1", "canonicalization_v2"}:
        raise ValueError("unsupported canonicalization version")
    if not value or len(value) > 2048:
        return None
    try:
        parsed = urlsplit(value)
        port = parsed.port
    except ValueError:
        return None
    if parsed.scheme.lower() != "https" or not parsed.hostname:
        return None
    host = parsed.hostname.casefold()
    if parsed.username is not None or parsed.password is not None:
        return None
    if ":" in host:
        host = f"[{host}]"
    netloc = host if port in (None, 443) else f"{host}:{port}"
    path_parts: list[str] = []
    for part in parsed.path.split("/"):
        if part in ("", "."):
            if not path_parts:
                path_parts.append("")
            continue
        if part == "..":
            if len(path_parts) > 1:
                path_parts.pop()
            continue
        path_parts.append(part)
    path = "/".join(path_parts) or "/"
    if version == "canonicalization_v2":
        # Dot segments are removed, but empty/trailing segments remain significant.
        segments = []
        source_segments = (parsed.path or "/").split("/")
        for index, part in enumerate(source_segments):
            if part == ".":
                if index == len(source_segments) - 1:
                    segments.append("")
            elif part == "..":
                if len(segments) > 1:
                    segments.pop()
                if index == len(source_segments) - 1:
                    segments.append("")
            else:
                segments.append(part)
        path = "/".join(segments) or "/"
    query = [
        (name, value)
        for name, value in parse_qsl(parsed.query, keep_blank_values=True)
        if not name.casefold().startswith("utm_") and name.casefold() not in TRACKING_PARAMETERS
    ]
    query.sort(key=lambda pair: (pair[0].encode("utf-8"), pair[1].encode("utf-8")))
    return urlunsplit(("https", netloc, path, urlencode(query, doseq=True, quote_via=quote), ""))


def parse_provider_time(value: str | None, collected_at: datetime) -> tuple[str, str]:
    if not value:
        return collected_at.isoformat(), "provider_time_fallback"
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return collected_at.isoformat(), "provider_time_fallback"
    if parsed.tzinfo is None:
        return collected_at.isoformat(), "provider_time_fallback"
    parsed = parsed.astimezone(timezone.utc)
    if parsed > collected_at + timedelta(minutes=5):
        return collected_at.isoformat(), "provider_time_fallback"
    if parsed > collected_at:
        return collected_at.isoformat(), "provider_time_clamped"
    return parsed.isoformat(), "provider_time_valid"


def utc_day_window(value: datetime) -> tuple[str, str]:
    start = value.astimezone(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
    return start.isoformat(), (start + timedelta(days=1)).isoformat()
