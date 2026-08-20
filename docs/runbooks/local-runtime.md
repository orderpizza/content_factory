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
