"""Instagram Graph API carousel adapter for the shared Posting Agent."""

import json
import mimetypes
import os
from pathlib import Path
from typing import Mapping, Protocol
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from uuid import uuid4


class PublicAssetStore(Protocol):
    def upload(self, local_path: str) -> tuple[str, str]:
        """Upload a local asset and return its object key and public HTTPS URL."""

    def delete(self, object_key: str) -> None:
        """Remove an uploaded transient object after publication."""


class R2PublicAssetStore:
    """Cloudflare R2 implementation kept isolated from the posting scheduler."""

    def __init__(self, *, account_id: str | None = None, access_key_id: str | None = None,
                 secret_access_key: str | None = None, bucket_name: str | None = None,
                 public_domain: str | None = None):
        self.account_id = account_id or os.getenv("R2_ACCOUNT_ID")
        self.access_key_id = access_key_id or os.getenv("R2_ACCESS_KEY_ID")
        self.secret_access_key = secret_access_key or os.getenv("R2_SECRET_ACCESS_KEY")
        self.bucket_name = bucket_name or os.getenv("R2_BUCKET_NAME")
        self.public_domain = (public_domain or os.getenv("R2_PUBLIC_DOMAIN") or "").rstrip("/")
        missing = [name for name, value in {
            "R2_ACCOUNT_ID": self.account_id, "R2_ACCESS_KEY_ID": self.access_key_id,
            "R2_SECRET_ACCESS_KEY": self.secret_access_key, "R2_BUCKET_NAME": self.bucket_name,
            "R2_PUBLIC_DOMAIN": self.public_domain,
        }.items() if not value]
        if missing:
            raise ValueError(f"Instagram public-asset storage is not configured: {', '.join(missing)}")
        import boto3
        from botocore.config import Config
        self._client = boto3.client(
            "s3", endpoint_url=f"https://{self.account_id}.r2.cloudflarestorage.com",
            aws_access_key_id=self.access_key_id, aws_secret_access_key=self.secret_access_key,
            region_name="auto", config=Config(signature_version="s3v4"),
        )

    def upload(self, local_path: str) -> tuple[str, str]:
        path = Path(local_path).resolve()
        if not path.is_file():
            raise FileNotFoundError(f"Rendered asset does not exist: {path}")
        key = f"instagram-transient/{uuid4().hex}{path.suffix.lower()}"
        content_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        self._client.upload_file(str(path), self.bucket_name, key, ExtraArgs={"ContentType": content_type})
        return key, f"{self.public_domain}/{key}"

    def delete(self, object_key: str) -> None:
        self._client.delete_object(Bucket=self.bucket_name, Key=object_key)


class InstagramCarouselPublisher:
    """Upload completed carousel assets, create Graph containers, and publish."""

    def __init__(self, asset_store: PublicAssetStore | None = None, *, instagram_user_id: str | None = None,
                 access_token: str | None = None, graph_api_version: str | None = None):
        self.asset_store = asset_store or R2PublicAssetStore()
        self.instagram_user_id = instagram_user_id or os.getenv("INSTAGRAM_USER_ID")
        self.access_token = access_token or os.getenv("INSTAGRAM_ACCESS_TOKEN")
        self.graph_api_version = graph_api_version or os.getenv("INSTAGRAM_GRAPH_API_VERSION", "v24.0")
        if not self.instagram_user_id or not self.access_token:
            raise ValueError("INSTAGRAM_USER_ID and INSTAGRAM_ACCESS_TOKEN must be configured")
        self.base_url = f"https://graph.facebook.com/{self.graph_api_version}"

    def publish_package(self, package: Mapping[str, object]) -> str:
        if package["package_platform"] != "instagram" or package["package_account"] != "o2_english":
            raise ValueError("Instagram carousel publisher only accepts o2_english Instagram packages")
        if package["content_format"] != "instagram_idiom_carousel":
            raise ValueError("Unsupported Instagram content format")
        assets = json.loads(str(package["assets"]))
        if not 2 <= len(assets) <= 10:
            raise ValueError("Instagram carousel requires two to ten rendered assets")
        keys: list[str] = []
        try:
            children = []
            for asset in assets:
                key, public_url = self.asset_store.upload(asset)
                keys.append(key)
                children.append(self._post(f"{self.instagram_user_id}/media", {
                    "image_url": public_url, "is_carousel_item": "true",
                })["id"])
            caption = _caption_with_hashtags(str(package["caption"]), json.loads(str(package["hashtags"])))
            parent = self._post(f"{self.instagram_user_id}/media", {
                "media_type": "CAROUSEL", "children": ",".join(str(item) for item in children), "caption": caption,
            })["id"]
            return str(self._post(f"{self.instagram_user_id}/media_publish", {"creation_id": parent})["id"])
        finally:
            for key in keys:
                try:
                    self.asset_store.delete(key)
                except Exception:
                    pass

    def _post(self, route: str, values: dict[str, str]) -> dict:
        payload = {**values, "access_token": self.access_token}
        request = Request(f"{self.base_url}/{route}", data=urlencode(payload).encode(), method="POST")
        try:
            with urlopen(request, timeout=60) as response:
                return json.load(response)
        except Exception as error:
            raise RuntimeError(f"Instagram Graph API request failed for {route}: {error}") from error


def _caption_with_hashtags(caption: str, hashtags: list[str]) -> str:
    return " ".join(part for part in [caption.strip(), *hashtags] if part).strip()
