"""Bounded, deterministic adapters for the four documented detection sources."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from hashlib import sha256
from io import BytesIO
from http.client import HTTPSConnection
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode, urljoin, urlsplit
from urllib.request import HTTPRedirectHandler, HTTPSHandler, ProxyHandler, Request, build_opener
from xml.etree import ElementTree
import gzip
import ipaddress
import json
import os
import socket
import time
import zlib
import math
from common.diagnostics import safe_diagnostic

from .models import CollectedItem, CollectionResult, ItemEvent, SourceCollectionError
from .normalization import canonical_link, canonical_title


MAX_COMPRESSED_BYTES = 2 * 1024 * 1024
MAX_DECOMPRESSED_BYTES = 10 * 1024 * 1024
USER_AGENT = "content-factory-poc/0.1 (local trend detection)"


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: ANN001
        return None


def _validate_public_https(url: str, allowed_hosts: set[str]) -> tuple[str, ...]:
    try:
        parsed = urlsplit(url)
        port = parsed.port or 443
    except ValueError as error:
        raise SourceCollectionError("unsafe_endpoint", "Malformed HTTPS endpoint") from error
    host = (parsed.hostname or "").casefold()
    if parsed.scheme != "https" or not host or host not in allowed_hosts:
        raise SourceCollectionError("unsafe_endpoint", f"HTTPS host is not allowlisted: {host or '<missing>'}")
    if parsed.username is not None or parsed.password is not None:
        raise SourceCollectionError("unsafe_endpoint", "Endpoint userinfo is forbidden")
    try:
        addresses = {item[4][0] for item in socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)}
    except OSError as error:
        raise SourceCollectionError("dns_failed", str(error)) from error
    for address in addresses:
        parsed_address = ipaddress.ip_address(address)
        if not parsed_address.is_global:
            raise SourceCollectionError("unsafe_endpoint", f"Host resolved to non-public address: {address}")
    if not addresses:
        raise SourceCollectionError("dns_failed", "Endpoint resolved to no addresses")
    return tuple(sorted(addresses))


class _PinnedHTTPSConnection(HTTPSConnection):
    """Connect only to the checked numeric addresses; retain TLS host checking."""
    def __init__(self, host, *, addresses, expected_host, **kwargs):
        super().__init__(host, **kwargs)
        if self.host.casefold() != expected_host:
            raise SourceCollectionError("unsafe_endpoint", "Transport host differs from validated endpoint")
        self.addresses = addresses

    def connect(self):
        last_error = None
        for address in self.addresses:
            try:
                self.sock = socket.create_connection((address, self.port), self.timeout)
                try:
                    self.sock = self._context.wrap_socket(self.sock, server_hostname=self.host)
                except Exception:
                    self.sock.close()
                    raise
                return
            except OSError as error:
                last_error = error
        raise last_error or OSError("No validated endpoint address")


class _PinnedHTTPSHandler(HTTPSHandler):
    def __init__(self, addresses, host):
        super().__init__()
        self.addresses, self.host = addresses, host

    def https_open(self, request):
        def connection(host, **kwargs):
            return _PinnedHTTPSConnection(host, addresses=self.addresses, expected_host=self.host, **kwargs)
        return self.do_open(connection, request)


def _bounded_get(
    url: str,
    *,
    allowed_hosts: list[str],
    headers: dict[str, str] | None = None,
    max_redirects: int = 3,
) -> tuple[bytes, dict[str, str], str, list[str]]:
    allowed = {host.casefold() for host in allowed_hosts}
    current = url
    redirects: list[str] = []
    request_headers = {"User-Agent": USER_AGENT, "Accept-Encoding": "gzip, deflate", **(headers or {})}
    for _ in range(max_redirects + 1):
        addresses = _validate_public_https(current, allowed)
        # Environment proxies must not bypass destination-address validation.
        opener = build_opener(ProxyHandler({}), _NoRedirect(), _PinnedHTTPSHandler(addresses, urlsplit(current).hostname.casefold()))
        request = Request(current, headers=request_headers)
        try:
            response = opener.open(request, timeout=20)
        except HTTPError as error:
            try:
                if error.code in {301, 302, 307, 308}:
                    location = error.headers.get("Location")
                    if not location or len(redirects) >= max_redirects:
                        raise SourceCollectionError("redirect_rejected", "Redirect limit or missing location") from error
                    redirected = urljoin(current, location)
                    if urlsplit(redirected).hostname != urlsplit(current).hostname:
                        request_headers = {k: v for k, v in request_headers.items() if k.casefold() not in {"authorization", "cookie"}}
                    current = redirected
                    redirects.append(current)
                    continue
                raise SourceCollectionError("http_error", f"HTTP {error.code}") from error
            finally:
                error.close()
        except URLError as error:
            raise SourceCollectionError("transport_error", str(error.reason)) from error
        with response:
            body = response.read(MAX_COMPRESSED_BYTES + 1)
            if len(body) > MAX_COMPRESSED_BYTES:
                raise SourceCollectionError("response_oversized", "Compressed response exceeds 2 MiB")
            response_headers = {key.casefold(): value for key, value in response.headers.items()}
            encoding = response_headers.get("content-encoding", "").casefold()
            if encoding == "gzip":
                with gzip.GzipFile(fileobj=BytesIO(body)) as compressed:
                    body = compressed.read(MAX_DECOMPRESSED_BYTES + 1)
            elif encoding == "deflate":
                decompressor = zlib.decompressobj()
                body = decompressor.decompress(body, MAX_DECOMPRESSED_BYTES + 1)
                if len(body) <= MAX_DECOMPRESSED_BYTES and not decompressor.eof:
                    raise SourceCollectionError("parse_failed", "Incomplete deflate response")
            if len(body) > MAX_DECOMPRESSED_BYTES:
                raise SourceCollectionError("response_oversized", "Decompressed response exceeds 10 MiB")
            return body, response_headers, response.geturl(), redirects
    raise SourceCollectionError("redirect_rejected", "Redirect limit exceeded")


def _hash_json(value: Any) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    return sha256(encoded).hexdigest()


def _source_config(row: Any) -> dict[str, Any]:
    return json.loads(row["config_json"])


def collect_source(row: Any) -> CollectionResult:
    return _validate_result(_collect_source(row), dict(row).get("canonicalization_version", "canonicalization_v2"))


def _validate_result(result: CollectionResult, normalization_version: str = "canonicalization_v2") -> CollectionResult:
    """Reject invalid metadata before any normalized evidence can enter SQLite."""
    items = []
    events = [replace(e, reason=safe_diagnostic(e.reason), source_item_key=None if e.source_item_key and len(e.source_item_key) > 1000 else e.source_item_key) for e in result.events]
    invalid = False
    seen_keys = set()
    for ordinal, item in enumerate(result.items, 1):
        oversized = False
        try:
            fields = ((item.title, 512, True), (item.source_item_key, 1000, True),
                      (item.source_item_id, 500, False), (item.canonical_url, 2048, False),
                      (item.provider_time, 128, False))
            for value, limit, required in fields:
                if value is None and not required:
                    continue
                if not isinstance(value, str) or (required and not value.strip()):
                    raise ValueError("invalid text")
                value.encode("utf-8", errors="strict")
                if len(value) > limit:
                    oversized = True
            if not isinstance(item.payload, dict):
                raise ValueError("invalid metadata object")
            if item.rank is not None and (type(item.rank) is not int or item.rank < 1):
                raise ValueError("invalid rank")
            if item.source_item_key in seen_keys:
                raise ValueError("duplicate item identity")
            encoded = json.dumps(item.payload, ensure_ascii=False, allow_nan=False).encode("utf-8")
            oversized = oversized or len(encoded) > 16 * 1024
            if type(item.activity) not in (int, float) or not math.isfinite(item.activity) or item.activity < 0:
                raise ValueError("invalid activity")
            if not canonical_title(item.title, normalization_version):
                raise ValueError("empty normalized title")
            if oversized:
                raise ValueError("oversized metadata")
        except (TypeError, ValueError, UnicodeError, OverflowError):
            invalid = True
            events.append(ItemEvent("rejected_oversized" if oversized else "rejected_invalid", "invalid or oversized normalized metadata", item.rank or ordinal))
            continue
        items.append(item)
        seen_keys.add(item.source_item_key)
    return replace(result, items=tuple(items), events=tuple(events), complete=result.complete and not invalid,
                   failure_category="partial_response" if invalid else result.failure_category,
                   failure_detail="Rejected invalid or oversized normalized metadata" if invalid else result.failure_detail)


def _decode_utf8(body: bytes) -> str:
    try:
        text = body.decode("utf-8-sig", errors="strict")
    except UnicodeError as error:
        raise SourceCollectionError("parse_failed", "Response is not valid UTF-8") from error
    if "\x00" in text:
        raise SourceCollectionError("parse_failed", "Response contains invalid NUL characters")
    return text


def _collect_source(row: Any) -> CollectionResult:
    kind = row["source_kind"]
    if kind == "publisher_feed_collector_v1":
        return _collect_feed(row)
    if kind == "wikimedia_enwiki_pageviews_v1":
        return _collect_wikimedia(row)
    if kind == "youtube_most_popular_v1":
        return _collect_youtube(row)
    if kind == "hacker_news_top_stories_v1":
        return _collect_hacker_news(row)
    raise SourceCollectionError("adapter_missing", f"No adapter for {kind}")


def _collect_feed(row: Any) -> CollectionResult:
    config = _source_config(row)
    normalization_version = dict(row).get("canonicalization_version", "canonicalization_v2")
    started = time.monotonic()
    body, _headers, final_url, redirects = _bounded_get(
        row["endpoint_url"], allowed_hosts=config["allowed_redirect_hosts"]
    )
    text = _decode_utf8(body)
    if "<!doctype" in text.lower() or "<!entity" in text.lower():
        raise SourceCollectionError("parse_failed", "XML DTD/entity declarations are not accepted")
    try:
        root = ElementTree.fromstring(text)
    except ElementTree.ParseError as error:
        raise SourceCollectionError("parse_failed", str(error)) from error
    if root.tag not in {"rss", "{http://www.w3.org/2005/Atom}feed"} or (root.tag == "rss" and root.find("channel") is None):
        raise SourceCollectionError("parse_failed", "Response is not an RSS/Atom feed")
    entries = root.findall(".//item") or root.findall(".//{http://www.w3.org/2005/Atom}entry")
    items: list[CollectedItem] = []
    events: list[ItemEvent] = []
    seen_keys: set[str] = set()
    if len(entries) > config["options"]["max_items"]:
        events.append(ItemEvent("rejected_oversized", "feed exceeds configured item bound", config["options"]["max_items"] + 1))
    for ordinal, entry in enumerate(entries[: config["options"]["max_items"]], start=1):
        title = _xml_text(entry, "title")
        if not title:
            events.append(ItemEvent("rejected_invalid", "missing title", ordinal))
            continue
        guid = _xml_text(entry, "guid") or _xml_text(entry, "id")
        link = _xml_link(entry)
        normalized_link = canonical_link(link or "", normalization_version)
        published = _xml_text(entry, "pubDate") or _xml_text(entry, "published") or _xml_text(entry, "updated")
        provider_time = _parse_any_time(published)
        item_key = guid.strip() if guid else (normalized_link or f"title:{canonical_title(title)}")
        if not guid and not normalized_link and normalization_version == "canonicalization_v2":
            item_key = f"title:{row['collection_day']}:{canonical_title(title, normalization_version)}"
        if item_key in seen_keys:
            events.append(
                ItemEvent(
                    "duplicate_suppressed", "duplicate source item within one feed response",
                    ordinal, item_key[:1000],
                )
            )
            continue
        seen_keys.add(item_key)
        items.append(CollectedItem(
            source_item_key=item_key, source_item_id=guid if guid else None,
            title=title, canonical_url=normalized_link, provider_time=provider_time,
            activity=1.0, rank=ordinal,
            payload={"feed_url": final_url, "redirects": redirects},
        ))
    return CollectionResult(
        items=tuple(items), events=tuple(events), complete=len(entries) <= config["options"]["max_items"] and not any(e.disposition.startswith("rejected_") for e in events),
        response_hash=sha256(body).hexdigest(), latency_ms=int((time.monotonic() - started) * 1000),
    )


def _xml_text(entry: ElementTree.Element, name: str) -> str:
    node = entry.find(name)
    if node is None:
        node = entry.find(f"{{http://www.w3.org/2005/Atom}}{name}")
    return (node.text or "").strip() if node is not None else ""


def _xml_link(entry: ElementTree.Element) -> str | None:
    node = entry.find("link")
    if node is not None and node.text:
        return node.text.strip()
    node = entry.find("{http://www.w3.org/2005/Atom}link")
    return node.get("href") if node is not None else None


def _parse_any_time(value: str) -> str | None:
    if not value:
        return None
    try:
        parsed = parsedate_to_datetime(value)
    except (TypeError, ValueError):
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
    if parsed.tzinfo is None:
        return None
    return parsed.astimezone(timezone.utc).isoformat()


def _collect_wikimedia(row: Any) -> CollectionResult:
    config = _source_config(row)
    report_date = dict(row).get("report_date")
    if not report_date:
        raise SourceCollectionError("configuration_missing", "Wikimedia requires a frozen report date")
    day = datetime.fromisoformat(report_date).date()
    url = f"{row['endpoint_url'].rstrip('/')}/{day:%Y/%m/%d}"
    started = time.monotonic()
    body, _headers, _final_url, _redirects = _bounded_get(
        url, allowed_hosts=config["allowed_redirect_hosts"]
    )
    try:
        payload = json.loads(_decode_utf8(body))
        report = payload["items"][0]
        articles = report["articles"]
        if not isinstance(articles, list):
            raise TypeError("articles must be an array")
    except (json.JSONDecodeError, KeyError, IndexError, TypeError) as error:
        raise SourceCollectionError("parse_failed", "Malformed Wikimedia top-page response") from error
    items: list[CollectedItem] = []
    events: list[ItemEvent] = []
    invalid_content_row = False
    excluded = {"Main_Page", "Special:Search", "-"}
    limit = config["options"]["max_items"]
    for rank, article in enumerate(articles[:limit], start=1):
        if not isinstance(article, dict):
            events.append(ItemEvent("rejected_invalid", "malformed Wikimedia row", rank))
            invalid_content_row = True
            continue
        title = article.get("article", "")
        if not isinstance(title, str):
            events.append(ItemEvent("rejected_invalid", "invalid article identity", rank))
            invalid_content_row = True
            continue
        if not title:
            events.append(ItemEvent("rejected_invalid", "missing article identity", rank))
            invalid_content_row = True
            continue
        if title in excluded or title.startswith("Special:"):
            events.append(ItemEvent("excluded_out_of_scope", "non-content Wikimedia row", rank, title or None))
            continue
        views = article.get("views")
        if type(views) is not int or views < 0 or type(article.get("rank", rank)) is not int:
            events.append(ItemEvent("rejected_invalid", "invalid view count", rank, title))
            invalid_content_row = True
            continue
        display = title.replace("_", " ")
        items.append(CollectedItem(
            source_item_key=title, source_item_id=title, title=display,
            canonical_url=canonical_link(f"https://en.wikipedia.org/wiki/{quote(title)}", dict(row).get("canonicalization_version", "canonicalization_v2")),
            provider_time=datetime.combine(day, datetime.min.time(), tzinfo=timezone.utc).isoformat(),
            activity=float(views), rank=rank,
            payload={"views": views, "provider_rank": int(article.get("rank", rank)), "report_date": day.isoformat()},
        ))
    declared_date = (
        str(report.get("year")), str(report.get("month")), str(report.get("day"))
    )
    requested_date = (str(day.year), f"{day.month:02d}", f"{day.day:02d}")
    try:
        date_matches = tuple(int(value) for value in declared_date) == tuple(
            int(value) for value in requested_date
        )
    except ValueError:
        date_matches = False
    complete = (
        isinstance(articles, list) and 0 < len(articles) <= limit
        and not invalid_content_row and date_matches
    )
    return CollectionResult(
        items=tuple(items), events=tuple(events), complete=complete,
        response_hash=sha256(body).hexdigest(), latency_ms=int((time.monotonic() - started) * 1000),
        provider_time=day.isoformat(),
        failure_category=None if complete else "partial_response",
        failure_detail=None if complete else (
            f"Report validation failed: rows={len(articles)}, limit={limit}, "
            f"declared_date={declared_date}, requested_date={requested_date}"
        ),
    )


def _collect_youtube(row: Any) -> CollectionResult:
    config = _source_config(row)
    secret_ref = config["secret_ref"]
    api_key = os.getenv(secret_ref or "")
    if not api_key:
        raise SourceCollectionError("configuration_missing", f"Required secret reference is unresolved: {secret_ref}")
    options = config["options"]
    query = urlencode({
        "part": ",".join(options["parts"]), "chart": "mostPopular",
        "regionCode": options["region_code"], "maxResults": options["max_items"], "key": api_key,
    })
    started = time.monotonic()
    body, _headers, _final_url, _redirects = _bounded_get(
        f"{row['endpoint_url']}?{query}", allowed_hosts=config["allowed_redirect_hosts"]
    )
    try:
        payload = json.loads(_decode_utf8(body))
        records = payload["items"]
        if not isinstance(records, list):
            raise TypeError("items must be an array")
    except (json.JSONDecodeError, KeyError, TypeError) as error:
        raise SourceCollectionError("parse_failed", "Malformed YouTube chart response") from error
    items: list[CollectedItem] = []
    events: list[ItemEvent] = []
    seen: set[str] = set()
    for rank, record in enumerate(records[:options["max_items"]], start=1):
        if not isinstance(record, dict) or not isinstance(record.get("snippet"), dict) or not isinstance(record.get("statistics", {}), dict):
            events.append(ItemEvent("rejected_invalid", "malformed video metadata", rank))
            continue
        video_id = record.get("id", "")
        if not isinstance(video_id, str):
            events.append(ItemEvent("rejected_invalid", "invalid video identity", rank))
            continue
        snippet = record.get("snippet", {})
        if not video_id or video_id in seen or not snippet.get("title"):
            events.append(ItemEvent("rejected_invalid", "missing/duplicate video identity or title", rank, video_id or None))
            continue
        seen.add(video_id)
        stats = record.get("statistics", {})
        items.append(CollectedItem(
            source_item_key=video_id, source_item_id=video_id,
            title=snippet["title"],
            canonical_url=f"https://www.youtube.com/watch?v={video_id}",
            provider_time=_parse_any_time(str(snippet.get("publishedAt", ""))),
            activity=float(51 - rank), rank=rank,
            payload={
                "channel_id": snippet.get("channelId"), "channel_title": snippet.get("channelTitle"),
                "category_id": snippet.get("categoryId"), "view_count": stats.get("viewCount"),
                "like_count": stats.get("likeCount"), "comment_count": stats.get("commentCount"),
            },
        ))
    complete = len(records) == options["max_items"] and len(items) == options["max_items"]
    return CollectionResult(
        items=tuple(items), events=tuple(events), complete=complete,
        response_hash=sha256(body).hexdigest(), latency_ms=int((time.monotonic() - started) * 1000),
        failure_category=None if complete else "partial_response",
        failure_detail=None if complete else f"Expected {options['max_items']} unique videos, received {len(items)}",
    )


def _collect_hacker_news(row: Any) -> CollectionResult:
    config = _source_config(row)
    allowed_hosts = config["allowed_redirect_hosts"]
    limit = config["options"]["max_items"]
    started = time.monotonic()
    list_body, _headers, _final_url, _redirects = _bounded_get(
        f"{row['endpoint_url'].rstrip('/')}/topstories.json", allowed_hosts=allowed_hosts
    )
    try:
        story_ids = json.loads(_decode_utf8(list_body))
    except json.JSONDecodeError as error:
        raise SourceCollectionError("parse_failed", "Malformed Hacker News ID list") from error
    if not isinstance(story_ids, list) or len(story_ids) < limit:
        raise SourceCollectionError("partial_response", f"Hacker News returned fewer than {limit} IDs")
    selected = story_ids[:limit]
    if any(type(value) is not int or value <= 0 for value in selected) or len(set(selected)) != len(selected):
        raise SourceCollectionError("partial_response", "Hacker News IDs must be distinct positive integers")

    def fetch(position_and_id: tuple[int, int]) -> tuple[int, int, bytes, dict[str, Any] | None]:
        position, story_id = position_and_id
        body, _h, _u, _r = _bounded_get(
            f"{row['endpoint_url'].rstrip('/')}/item/{story_id}.json", allowed_hosts=allowed_hosts
        )
        return position, story_id, body, json.loads(_decode_utf8(body))

    responses: dict[int, tuple[int, bytes, dict[str, Any] | None]] = {}
    failures: dict[int, str] = {}
    with ThreadPoolExecutor(max_workers=10) as executor:
        futures = {executor.submit(fetch, pair): pair for pair in enumerate(selected, start=1)}
        for future in as_completed(futures):
            position, story_id = futures[future]
            try:
                _, _, body, record = future.result()
                responses[position] = (story_id, body, record)
            except Exception as error:  # retained below as an incomplete item event
                failures[position] = safe_diagnostic(f"item response failed ({type(error).__name__})")

    items: list[CollectedItem] = []
    events: list[ItemEvent] = []
    invalid_required_item = False
    response_hashes = [sha256(list_body).hexdigest()]
    for position, story_id in enumerate(selected, start=1):
        if position in failures:
            events.append(ItemEvent("rejected_invalid", failures[position], position, str(story_id)))
            continue
        _, body, record = responses[position]
        response_hashes.append(sha256(body).hexdigest())
        if not isinstance(record, dict):
            events.append(ItemEvent("rejected_invalid", "null or malformed story", position, str(story_id)))
            invalid_required_item = True
            continue
        if record.get("deleted"):
            events.append(ItemEvent("excluded_deleted", "story marked deleted", position, str(story_id)))
            continue
        if record.get("dead"):
            events.append(ItemEvent("excluded_dead", "story marked dead", position, str(story_id)))
            continue
        if record.get("type") != "story":
            events.append(ItemEvent("excluded_non_story", "item is not a story", position, str(story_id)))
            continue
        title = record.get("title", "")
        score = record.get("score")
        if not isinstance(title, str) or not title or type(score) is not int or score < 0:
            events.append(ItemEvent("rejected_invalid", "missing title or invalid score", position, str(story_id)))
            invalid_required_item = True
            continue
        provider_time = None
        if type(record.get("time")) is int:
            try:
                provider_time = datetime.fromtimestamp(record["time"], timezone.utc).isoformat()
            except (OverflowError, OSError, ValueError):
                provider_time = None
        items.append(CollectedItem(
            source_item_key=str(story_id), source_item_id=str(story_id), title=title,
            canonical_url=canonical_link(str(record.get("url", "")), dict(row).get("canonicalization_version", "canonicalization_v2")), provider_time=provider_time,
            activity=float(score), rank=position,
            payload={"score": score, "by": record.get("by"), "list_count": len(story_ids)},
        ))
    complete = not failures and not invalid_required_item
    return CollectionResult(
        items=tuple(items), events=tuple(events), complete=complete,
        response_hash=_hash_json(response_hashes), latency_ms=int((time.monotonic() - started) * 1000),
        failure_category=None if complete else "partial_response",
        failure_detail=None if complete else (
            f"Missing transport responses={len(failures)}, "
            f"invalid required items={int(invalid_required_item)}"
        ),
    )
