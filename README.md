# Content Factory

Local-first content-factory POC targeting a Mac Mini with SQLite handoffs.

**Working today:** deterministic source ingestion and a loopback read-only
dashboard. An optional v2 workflow demonstrates later editorial handoffs using
local placeholders. It does not generate production content or publish.
The optional safety-v3 migration enables the user-approved hybrid scoring release.
Separate legacy code remains for compatibility; real legacy Gemini and publishing
entrypoints are retired and refuse execution.

## Start here

- [System guide](docs/system.md): target boundaries and required-reading router.
- [Current implementation and operations](docs/current-state.md): actual behavior,
  project map, setup/demo commands, hybrid rollout, settings and retired entrypoints.
- [Repository audit](audit_report.md): severity-ranked findings, fixes, remaining
  decisions and verification.
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
`python` on Mac. Provider/paid/public smoke tests are not routine verification.

Phase 1 targets `english`, `ai_tools`, `personal_finance`,
`business_side_hustle`, and `psychology_behavior`, with separately approved
Instagram/X outputs. It excludes TikTok, YouTube Shorts, AI video and Bluesky.
Do not introduce distributed queues or speculative infrastructure.
