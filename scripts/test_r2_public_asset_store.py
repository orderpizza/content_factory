"""Verify the configured R2 public-asset store without contacting Meta.

The probe uploads a generated one-pixel image to the Posting Agent's transient
prefix, verifies that the returned public URL is anonymously readable, and
deletes the object even when verification fails.
"""

import sys
import tempfile
import time
from base64 import b64decode
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from posting.instagram import R2PublicAssetStore


def _wait_until_public(public_url: str, attempts: int = 6, interval_seconds: float = 2.0) -> None:
    last_error: Exception | None = None
    for attempt in range(attempts):
        try:
            request = Request(public_url, headers={"User-Agent": "Mozilla/5.0 (compatible; ContentFactoryR2Probe/1.0)"})
            with urlopen(request, timeout=20) as response:
                if response.status != 200:
                    raise RuntimeError(f"expected HTTP 200, received {response.status}")
                if not response.headers.get("Content-Type", "").startswith("image/"):
                    raise RuntimeError(f"unexpected Content-Type: {response.headers.get('Content-Type')}")
                return
        except HTTPError as error:
            detail = error.read(1000).decode("utf-8", errors="replace").strip()
            last_error = RuntimeError(f"HTTP {error.code}: {detail or error.reason}")
            if attempt < attempts - 1:
                time.sleep(interval_seconds)
        except Exception as error:
            last_error = error
            if attempt < attempts - 1:
                time.sleep(interval_seconds)
    raise RuntimeError(f"R2 object was uploaded but its public URL could not be read: {last_error}")


def main() -> None:
    store = R2PublicAssetStore()
    object_key: str | None = None
    with tempfile.TemporaryDirectory(prefix="content-factory-r2-probe-") as temporary_directory:
        image_path = Path(temporary_directory) / "r2-probe.png"
        image_path.write_bytes(b64decode(
            "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVQIHWP4"
            "z8DwHwAFgAI/ScLqYQAAAABJRU5ErkJggg=="
        ))
        try:
            object_key, public_url = store.upload(str(image_path))
            _wait_until_public(public_url)
            print(f"R2 public-asset probe passed: uploaded and read {object_key}")
        finally:
            if object_key:
                store.delete(object_key)
                print(f"R2 public-asset probe cleanup passed: deleted {object_key}")


if __name__ == "__main__":
    main()
