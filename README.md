# Content Factory

Local-first content-factory POC targeting a Mac Mini with SQLite handoffs.

**Working today:** deterministic source ingestion and hybrid scoring; persisted
human idea/refinement; Gemini-backed Intake, five-domain Determination,
generation, and Instagram/X adaptation; local Playwright rendering; exact
per-destination review; and opt-in credentialed Instagram carousel/X single-post
delivery. Production mode is schema v4 and fails closed behind an immutable
real-destination catalog, current readiness, storage admission, priced Gemini
reservations, and a dashboard **Post now** command for each exact package.

Nothing is activated by checkout or migration. The default runner still uses
non-deliverable fixtures. Active development uses the fresh normalized Option B
database and preserves the legacy database. Provider calls, profile quality,
credentials, and Mac `launchd` installation still require operator verification;
see [current operations](docs/current-state.md#production-setup-and-operation).
Legacy composition and publisher entrypoints remain retired and fail closed.

Before any provider smoke, run the non-network preflight at the intended level:

```sh
.venv/bin/python scripts/check_smoke_readiness.py \
  --database data/dev-normalized.db --mode preview
```

Use `--mode production` after configuration/backup, and `--mode delivery` only
after live destination readiness. A blocked report names local or configuration
gaps without exposing secret values or calling a provider.

## Start here

- [System guide](docs/system.md): target boundaries and required-reading router.
- [Current implementation and operations](docs/current-state.md): actual behavior,
  project map, setup/demo commands, hybrid rollout, settings and retired entrypoints.
- [Repository audit](audit_report.md): repair scope and historical verification.
- [Target plan](docs/plans/target-implementation.md): future implementation order.
- [Contract registry](docs/contracts/maturity.md): exact, draft and superseded contracts.

Code and tests establish current behavior. Target contracts establish intended
behavior; a discrepancy needs classification, not automatic code changes or a
claim that planned safeguards already work.

## Documentation layout

`docs/specs/` owns focused contracts, `pipelines/` domain intelligence,
`platforms/` provider references, `contracts/` SQL/JSON boundaries, and
`profiles/` concrete renderer versions. `plans/` is derived sequencing;
`archive/` is historical rationale. Nonsecret manifests live in `config/releases/`.

## Verification and scope

Run `py scripts/check_docs.py` for documentation changes; also run
`py scripts/run_tests.py` for implementation. Use the configured virtualenv's
`python` on Mac. Provider/paid/public smoke tests are not routine verification;
offline tests use fakes for Gemini, R2, Meta, and X.

Phase 1 targets `english`, `ai_tools`, `personal_finance`,
`business_side_hustle`, and `psychology_behavior`, with separately approved
Instagram/X outputs. It excludes TikTok, YouTube Shorts, AI video and Bluesky.
Do not introduce distributed queues or speculative infrastructure.
