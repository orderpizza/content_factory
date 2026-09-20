"""Materialize an immutable real-account catalog after explicit operator review."""

from __future__ import annotations

from argparse import ArgumentParser
from datetime import datetime, timezone
from hashlib import sha256
from pathlib import Path
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
import os
import re
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from common.environment import load_environment_file
from database.current import SchemaError, validate_database
from workflow import WORKFLOW_PIPELINES, WorkflowStore


def _required(parser: ArgumentParser, value: str | None, name: str) -> str:
    if not value or not value.strip():
        parser.error(f"{name} is required for the selected destination")
    return value.strip()


def _public_domain(parser: ArgumentParser, value: str | None) -> str:
    text = _required(parser, value, "R2 public domain")
    parsed = urlsplit(text)
    if (
        parsed.scheme != "https" or not parsed.hostname or parsed.username
        or parsed.password or parsed.query or parsed.fragment
        or parsed.path not in {"", "/"}
    ):
        parser.error("R2 public domain must be an origin-only HTTPS URL")
    return text.rstrip("/")


def _account_id(parser: ArgumentParser, value: str | None, name: str) -> str:
    text = _required(parser, value, name)
    if not re.fullmatch(r"[0-9]{1,30}", text):
        parser.error(f"{name} must be the provider's numeric account ID")
    return text


def main() -> None:
    load_environment_file(ROOT / ".env")
    parser = ArgumentParser(description=__doc__)
    parser.add_argument("--database", default=os.getenv("CONTENT_FACTORY_DB_PATH", str(ROOT / "data" / "development.db")))
    parser.add_argument("--instagram-account-key", default=os.getenv("INSTAGRAM_ACCOUNT_KEY"))
    parser.add_argument("--instagram-user-id", default=os.getenv("INSTAGRAM_USER_ID"))
    parser.add_argument("--graph-api-version", default=os.getenv("META_GRAPH_API_VERSION", "v24.0"))
    parser.add_argument("--r2-account-id", default=os.getenv("R2_ACCOUNT_ID"))
    parser.add_argument("--r2-bucket", default=os.getenv("R2_BUCKET_NAME"))
    parser.add_argument("--r2-public-domain", default=os.getenv("R2_PUBLIC_DOMAIN"))
    parser.add_argument("--x-account-key", default=os.getenv("X_ACCOUNT_KEY"))
    parser.add_argument("--x-user-id", default=os.getenv("X_USER_ID"))
    parser.add_argument("--disable-instagram", action="store_true")
    parser.add_argument("--disable-x", action="store_true")
    parser.add_argument("--timezone", default="Asia/Seoul")
    parser.add_argument("--max-posts-per-day", type=int, default=1)
    parser.add_argument("--min-post-interval-minutes", type=int, default=1200)
    parser.add_argument("--authorization-ttl-hours", type=int, default=48)
    parser.add_argument("--font-path", default=os.getenv("CONTENT_FACTORY_FONT_PATH"))
    parser.add_argument("--font-sha256", default=os.getenv("CONTENT_FACTORY_FONT_SHA256"))
    parser.add_argument(
        "--approve-current-static-profiles",
        action="store_true",
        help="record that the operator reviewed and accepts the current 1080x1350/1200x675 profiles",
    )
    args = parser.parse_args()
    if args.disable_instagram and args.disable_x:
        parser.error("at least one production destination must remain enabled")
    if not args.approve_current_static_profiles:
        parser.error(
            "review local preview assets first, then pass --approve-current-static-profiles explicitly"
        )
    configured_font_path = Path(_required(parser, args.font_path, "production font path"))
    if configured_font_path.is_symlink():
        parser.error("production font path cannot be a symbolic link")
    font_path = configured_font_path.resolve()
    if not font_path.is_file() or font_path.stat().st_size > 20_000_000:
        parser.error("production font path must be a regular local file no larger than 20 MB")
    font_hash = sha256(font_path.read_bytes()).hexdigest()
    if args.font_sha256 and args.font_sha256.casefold() != font_hash:
        parser.error("production font SHA-256 does not match the selected file")
    if args.max_posts_per_day < 1 or args.min_post_interval_minutes < 0 or args.authorization_ttl_hours < 1:
        parser.error("posting limits must be positive (the minimum interval may be zero)")
    try:
        ZoneInfo(args.timezone)
    except ZoneInfoNotFoundError:
        parser.error("--timezone must be a valid IANA time-zone name")

    destinations = []
    if not args.disable_instagram:
        if not re.fullmatch(r"v[0-9]{1,3}\.[0-9]{1,3}", args.graph_api_version):
            parser.error("Graph API version must have the form vNN.N")
        destinations.append({
            "destination_key": "instagram:" + _required(parser, args.instagram_account_key, "Instagram account key"),
            "platform": "instagram",
            "account_key": _required(parser, args.instagram_account_key, "Instagram account key"),
            "provider_account_id": _account_id(parser, args.instagram_user_id, "Instagram user ID"),
            "secret_ref": "INSTAGRAM_ACCESS_TOKEN",
            "enabled": True,
            "config": {
                "graph_api_version": args.graph_api_version,
                "r2_account_id": _required(parser, args.r2_account_id, "R2 account ID"),
                "r2_bucket_name": _required(parser, args.r2_bucket, "R2 bucket name"),
                "r2_public_domain": _public_domain(parser, args.r2_public_domain),
                "adapter_version": "meta_instagram_carousel_v1",
            },
            "posting_policy": {
                "timezone": args.timezone,
                "max_posts_per_day": args.max_posts_per_day,
                "min_post_interval_minutes": args.min_post_interval_minutes,
                "authorization_ttl_hours": args.authorization_ttl_hours,
            },
        })
    if not args.disable_x:
        destinations.append({
            "destination_key": "x:" + _required(parser, args.x_account_key, "X account key"),
            "platform": "x",
            "account_key": _required(parser, args.x_account_key, "X account key"),
            "provider_account_id": _account_id(parser, args.x_user_id, "X user ID"),
            "secret_ref": "X_USER_ACCESS_TOKEN",
            "enabled": True,
            "config": {
                "api_origin": "https://api.x.com",
                "media_upload_path": "/2/media/upload",
                "create_post_path": "/2/tweets",
                "adapter_version": "x_static_post_delivery_v1",
                "image_max_bytes": 5_000_000,
            },
            "posting_policy": {
                "timezone": args.timezone,
                "max_posts_per_day": args.max_posts_per_day,
                "min_post_interval_minutes": args.min_post_interval_minutes,
                "authorization_ttl_hours": args.authorization_ttl_hours,
            },
        })
    bindings = [
        {
            "pipeline_id": pipeline,
            "destination_key": destination["destination_key"],
            "content_format": (
                "instagram_static_carousel_v2"
                if destination["platform"] == "instagram" else "x_static_post_v1"
            ),
        }
        for pipeline in WORKFLOW_PIPELINES
        for destination in destinations
    ]
    moment = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    value = {
        "policy_version": "production_configuration_v1",
        "approved_by": "local_owner",
        "approved_at": moment,
        "profile_approved": True,
        "renderer_profile": {
            "profile_version": "static_social_delivery_profiles_v1",
            "template_version": "static_social_template_v1",
            "font_path": str(font_path),
            "font_sha256": font_hash,
        },
        "destinations": destinations,
        "bindings": bindings,
    }
    try:
        with WorkflowStore(args.database, catalog_kind="production") as store:
            validate_database(store.connection)
            configuration_id = store.register_production_configuration(value)
    except (SchemaError, RuntimeError, ValueError) as error:
        raise SystemExit(f"Production configuration refused: {error}")
    print(f"Production configuration #{configuration_id} materialized; live readiness remains blocked until checked.")


if __name__ == "__main__":
    main()
