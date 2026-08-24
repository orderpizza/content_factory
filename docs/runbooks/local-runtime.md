# Local Runtime Runbook

## Verification

```sh
./.venv/bin/python scripts/run_tests.py
./.venv/bin/python scripts/check_docs.py
```

## Local Workers

These workers communicate only through persisted SQLite state:

```sh
./.venv/bin/python scripts/run_scout.py
./.venv/bin/python scripts/run_determination.py
./.venv/bin/python scripts/run_pipeline.py
./.venv/bin/python scripts/run_visual_renderer.py
```

The Posting Agent requires configured Meta and public-media credentials before
it can make a real external post. Do not treat a local worker invocation as
authorization to publish without those credentials.

## R2 Public-Asset Probe

After loading the R2 variables from `.env`, verify the R2 relay independently
before any Instagram test:

```sh
./.venv/bin/python scripts/test_r2_public_asset_store.py
```

The probe creates a one-pixel image, uploads it below the transient posting
prefix, confirms its public URL returns HTTP 200, and deletes it. It makes no
Meta or Instagram request and leaves no intended object behind.

The probe uses a browser-like request signature when checking the public URL.
Cloudflare's `r2.dev` edge can reject Python's default signature with error
1010 even when object upload and public access are configured correctly.

## Instagram Credential Check

The active adapter uses Meta's Instagram API with Facebook Login. Before a
live publish, load the local environment and make this read-only request:

```sh
./.venv/bin/python scripts/test_instagram_credentials.py
```

It calls only `GET /{INSTAGRAM_USER_ID}?fields=id,username`; it does not
create a media container, upload media, or publish a post. A passing result
confirms that `INSTAGRAM_USER_ID`, `INSTAGRAM_ACCESS_TOKEN`, and the configured
Graph API version work together.

For the current adapter, configure the local values as follows:

```dotenv
INSTAGRAM_USER_ID=<numeric Instagram Professional Account ID>
INSTAGRAM_ACCESS_TOKEN=<Page access token for its linked Facebook Page>
INSTAGRAM_GRAPH_API_VERSION=v24.0
```

The Instagram account must be Professional and linked to a Facebook Page
administered by the authorizing Facebook user. The Meta developer app's role
is to obtain the Page token; it is not a publishing destination. Never commit
the token. A `media_publish` request creates a real Instagram post—there is no
private or draft outcome for this carousel delivery path. Use the credential
check before granting any live-publish authorization.

## Dashboard

```sh
./.venv/bin/python scripts/serve_dashboard.py
```

The dashboard is read-only and must remain an observer of persisted state.

## O2 Instagram Smoke Test

The dedicated smoke harness uses an isolated SQLite database and generated
output directory. It creates a synthetic persisted determination handoff,
forces that handoff to the active `o2_english_instagram` route, uses the real
Gemini content and metadata generators, renders the real carousel PNGs, and
queues a real posting request.

```sh
./.venv/bin/python scripts/smoke_test_o2_instagram.py
```

The default run never contacts Instagram. It stops after queueing a post in
`data/smoke-o2-instagram.db` and prints the persisted record IDs. It does not
test Gemini determination because the deterministic smoke evaluator guarantees
the active o2 route; it does test both pipeline Gemini calls.

After configuring Vertex, Meta, and public-media credentials, make one real
Instagram post only with explicit opt-in:

```sh
./.venv/bin/python scripts/smoke_test_o2_instagram.py --live --database data/smoke-o2-instagram-live.db
```

The harness refuses to overwrite an existing smoke database. Use a new
`--database` path for each run. Keep `.env` local and load its variables into
your shell before running either command.

## Python 3.12 Setup

The POC requires Python 3.10 or later. On the Mac Mini, install Homebrew
Python 3.12, then create the project-local environment:

```sh
/opt/homebrew/bin/python3.12 -m venv .venv
./.venv/bin/python -m pip install -e '.[dev]'
```

The launch-agent templates intentionally reference `.venv/bin/python` rather
than `/usr/bin/python3`, which is Apple-managed and may be an older version.
