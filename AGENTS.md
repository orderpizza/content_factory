# Content Factory working instructions

Read [product](docs/product.md), [architecture](docs/architecture.md) and
[roadmap](docs/roadmap.md) first. Use the architecture router for the affected
technical contract and [operations](docs/operations.md) for runnable commands.

## Direction and scope

Build a profitable, repeatable operation: publish and measure one Instagram
account before multi-account support and wider platforms. The current application
stops at review. Do not describe target features as implemented. Domain/account
coupling is a current limitation, not a permanent architectural requirement.
Change runtime topology, schemas or editorial policy only in an authorized phase.

## Protect current operation

- SQLite is the persisted worker interface; preserve atomic/idempotent handoffs,
  immutable evidence, fenced leases, lineage and explicit failure states.
- Detection is LLM-free. Keep source-bound claims and editorial qualifications
  intact through generation/adaptation; consult the owning contracts.
- The dashboard reads evidence and persists commands, never invokes providers or
  workers. Human review must authorize exact assets for each destination.
- Preserve bounded model cost, uncertain-outcome handling and checkpoint recovery.
  Never blindly replay possibly accepted provider calls or publication attempts.
- Active rendering uses Gemini with local split/normalization/overlays. Preserve
  supported geometry and final-asset validation; no silent renderer fallback.
- Planning through job creation ignores storage admission; downstream write and
  production safeguards still apply.
- All workers use `database.current`. Bootstrap creates a fresh DB; do not migrate
  or reset an operator database incidentally. Persist timestamps via
  `common.timestamps` as UTC-naive ISO-8601 seconds (`YYYY-MM-DDTHH:MM:SS`).

## Safe changes and verification

Inspect code, inbound references and tests before deleting anything. Preserve
unrelated edits and untracked data. Secrets stay outside tracked files, logs and
model inputs. No paid calls, live provider checks, public posts or local data
cleanup without explicit authorization. Repository cleanup does not erase ignored
Mac Mini databases, logs, artifacts or secrets; local cleanup requires separately
verified paths and authorization.

Run `.venv/bin/python scripts/check_docs.py` for documentation changes; also run
`.venv/bin/python scripts/run_tests.py` for code/tooling changes. See
[testing](docs/testing.md) for safeguard coverage and honest reporting of blockers.
Keep one authoritative owner for each current contract and link to it. Update
product/architecture/roadmap when direction changes; store runtime evidence in
ignored data paths, not permanent historical reports. Put cleanup rationale and
verification evidence in the PR description. Do not merge without authorization.
