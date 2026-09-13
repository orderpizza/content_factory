"""Verify Instagram publishing credentials without creating or publishing media."""

import json
import os
import re
import sys
from argparse import ArgumentParser
from hashlib import sha256
from pathlib import Path
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from common.diagnostics import safe_diagnostic
from common.environment import load_environment_file


def main() -> None:
    token_from_process = "INSTAGRAM_ACCESS_TOKEN" in os.environ
    load_environment_file(ROOT / ".env")
    parser = ArgumentParser(description=__doc__)
    parser.add_argument("--local-only", action="store_true",
                        help="show effective token fingerprint and configuration without a network call")
    args = parser.parse_args()
    user_id = os.getenv("INSTAGRAM_USER_ID")
    access_token = os.getenv("INSTAGRAM_ACCESS_TOKEN")
    api_version = os.getenv("META_GRAPH_API_VERSION") or os.getenv("INSTAGRAM_GRAPH_API_VERSION", "v24.0")
    missing = [
        name for name, value in {
            "INSTAGRAM_USER_ID": user_id,
            "INSTAGRAM_ACCESS_TOKEN": access_token,
        }.items() if not value
    ]
    if missing:
        raise SystemExit(f"Instagram credential check is not configured: {', '.join(missing)}")
    if not re.fullmatch(r"[0-9]{1,30}", user_id) or not re.fullmatch(r"v[0-9]{1,3}\.[0-9]{1,3}", api_version):
        raise SystemExit("Instagram credential check requires a numeric Instagram ID and vNN.N API version")
    if args.local_only:
        print(json.dumps({
            "api_version": api_version,
            "token_source": "process_environment" if token_from_process else "repository_env_file",
            "token_length": len(access_token),
            "token_sha256_prefix": sha256(access_token.encode("utf-8")).hexdigest()[:12],
            "network_calls_made": False,
        }, indent=2))
        return
    query = urlencode({"fields": "id,username", "access_token": access_token})
    request = Request(
        f"https://graph.facebook.com/{api_version}/{user_id}?{query}",
        headers={"User-Agent": "ContentFactoryCredentialProbe/1.0"},
    )
    try:
        with urlopen(request, timeout=30) as response:
            profile = json.loads(response.read(100_000))
    except HTTPError as error:
        try:
            detail = json.loads(error.read(100_000)).get("error", {})
        except (ValueError, AttributeError):
            detail = {}
        if not isinstance(detail, dict):
            detail = {}
        message = str(detail.get("message", "provider rejected request")).replace(access_token, "[redacted]")
        raise SystemExit(safe_diagnostic(
            f"Instagram credential check failed: HTTP {error.code}; "
            f"code={detail.get('code')}; subcode={detail.get('error_subcode')}; {message}"
        )) from None
    except Exception as error:
        # HTTP exception strings can contain the secret-bearing query URL.
        raise SystemExit(f"Instagram credential check failed ({type(error).__name__})") from None
    if str(profile.get("id")) != user_id:
        raise SystemExit("Instagram credential check returned a different account ID")
    print(f"Instagram credential check passed: id={profile['id']}; username={profile.get('username', '(not returned)')}")


if __name__ == "__main__":
    main()
