# Content Factory

Build a repeatable, profitable AI-assisted social content operation, beginning
with one Instagram account. The current local Mac Mini application produces
review-ready content; production publishing, analytics feedback and account-first
configuration are not operational.

## Start locally

With Python 3.10+ and uv installed:

```sh
uv sync --frozen --extra dev
.venv/bin/python -m playwright install chromium
.venv/bin/python scripts/setup_development.py
.venv/bin/python scripts/serve_dashboard.py
```

Setup creates a fresh timestamped SQLite database and synthetic development
bindings without provider calls. The dashboard runs on loopback port 8787.
It records commands; producing Gemini review assets requires the separately
configured, paid workflow described in [operations](docs/operations.md).
Actual settings belong in ignored `.env`; `.env.example` inventories their names.

## Documentation

- [Product](docs/product.md): business hypotheses and measurable MVP outcomes.
- [Architecture](docs/architecture.md): current pipeline, target and contract router.
- [Roadmap](docs/roadmap.md): publish and measure, then accounts, then platforms.
- [Operations](docs/operations.md): setup, secrets, Mac Mini processes and backups.
- [Testing](docs/testing.md): offline safeguards and opt-in paid acceptance.
- [AGENTS.md](AGENTS.md): safe implementation and verification instructions.

Remote repository cleanup does not erase ignored local databases, logs, artifacts
or secrets. Local data cleanup is a separate, explicitly authorized operation.
