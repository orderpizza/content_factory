"""Verify Instagram publishing credentials without creating or publishing media."""

import json
import os
import sys
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import Request, urlopen

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))


def main() -> None:
    user_id = os.getenv("INSTAGRAM_USER_ID")
    access_token = os.getenv("INSTAGRAM_ACCESS_TOKEN")
    api_version = os.getenv("INSTAGRAM_GRAPH_API_VERSION", "v24.0")
    missing = [
        name for name, value in {
            "INSTAGRAM_USER_ID": user_id,
            "INSTAGRAM_ACCESS_TOKEN": access_token,
        }.items() if not value
    ]
    if missing:
        raise ValueError(f"Instagram credential check is not configured: {', '.join(missing)}")
    query = urlencode({"fields": "id,username", "access_token": access_token})
    request = Request(
        f"https://graph.facebook.com/{api_version}/{user_id}?{query}",
        headers={"User-Agent": "ContentFactoryCredentialProbe/1.0"},
    )
    with urlopen(request, timeout=30) as response:
        profile = json.load(response)
    print(f"Instagram credential check passed: id={profile['id']}; username={profile.get('username', '(not returned)')}")


if __name__ == "__main__":
    main()
