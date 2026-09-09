# Current implementation and operations

**As-built snapshot:** 2026-09-09. Code and boundary tests establish actual
behavior. [System guide](system.md) routes target requirements; the root
[audit report](../audit_report.md#follow-up-repairs--2026-09-09) records repaired,
mitigated and still-open findings. Neither a design-approved label nor a green
offline suite means public production is enabled.

## Current state

The usable slice is deterministic collection, scoring/shortlist SQLite handoffs
and the loopback read-only dashboard. An optional local editorial scaffold
demonstrates persisted stages using **placeholders**, not domain intelligence.

| Capability | State today |
| --- | --- |
| NASA RSS, Wikimedia daily reports, YouTube popular chart, HN Top-100 | Implemented bounded adapters; source credentials/configuration are assumed available, live provider operation was not tested in this repair. |
| Hybrid attention scoring | Implemented as `attention_v2`, enabled only through an explicit safety-v3 migration and new configuration release. Fast sources are live; Wikimedia uses completed days. Existing databases/releases are not automatically changed. |
| Source evidence/recovery | Frozen report date, stable undated-item first-observed time, immutable contributor replay; safety v3 adds frozen historical health and per-execution partial-response evidence. |
| Input normalization/validation | Corrected punctuation and path handling in opt-in `canonicalization_v2`; separate database only. All adapters reject oversized/malformed normalized metadata without truncation and preserve valid partial evidence. |
| Human idea/continuation | CLI commands persist messages/Intake requests and idempotent receipts under a write lock. Continuation requires the displayed positive row version. Oversized frozen conversation fails visibly, without truncation. |
| Local Intake/Determination | Deterministic demo: length-based clarification, generic brief, first-ready-domain selection. Five route rows and aggregate/readiness checks, but no Gemini/editorial-quality implementation. |
| Local claim safety | Expired local claims recover with bounded attempts; stale owners cannot finalize. Recorded model work is not automatically retried. Failures/cancellation are persisted, not left indefinitely claimed. Full production supervision/recovery remains planned. |
| Canonical generation/adaptation | Generic local fixtures only; no production identity/reuse/reservation system or five-domain semantic schemas. |
| Render/review | HTML preview only. Existing render directories cannot be overwritten. Reviews are visible but `approve_review` refuses authorization for this scaffold. |
| Public delivery/model spending | Legacy Gemini and Instagram/Bluesky publishing are retired at their call boundaries. V2/v3 authorization remains disabled. No environment bypass is supplied. |
| Dashboard | Read-only ingestion/opportunities plus bounded thread-first conversation, pending/clarification/failure states, routes and downstream status/IDs. No browser idea forms, exact-asset review or Post now. |
| Automatic recurrence | Not implemented end to end. The existing selected-candidate identity prevents a second seed; the configured three-day value is not a complete recurrence/reuse system. |
| Backup/restore/storage/maintenance | Production implementation remains planned. Unsafe file-moving rebuild and legacy retention commands are retired. |

## Implemented architecture and project map

Two incompatible persistence families remain. Similar filenames and table names
do not make them interchangeable.

| Location | Current responsibility |
| --- | --- |
| `src/database/migrations.py`, `docs/contracts/*schema-v*.sql` | Explicit v1 detection, v2 editorial scaffold and v3 detection-safety forward migrations; recorded checksums/FKs, encoded read-only connections. Checkout SQL or byte-identical packaged resources. |
| `src/detection/` | Current source configuration, collection, frozen evidence, v1 compatibility scoring and new hybrid scoring/shortlist. No LLM. |
| `src/workflow/store.py`, `workers.py` | Local SQLite commands and placeholder workers; no connection to real Gemini/social providers. |
| `src/dashboard/detection.py`, `workflow.py` | Read-only reporting; the HTTP server renders detection and workflow in one SQLite snapshot. |
| `src/common/environment.py`, `diagnostics.py`, `legacy.py` | Literal optional environment loader, bounded diagnostic redaction, fail-closed legacy operational boundary. |
| `src/database/sqlite.py` | Unversioned legacy DB; rejects any nonzero schema before DDL. Retained for old fixtures, not current workers. |
| `src/intelligence/`, `intake/`, `determination/`, `pipelines/`, `visual/`, `posting/` | Legacy algorithms/fixtures/reference implementation. Operational entrypoints and real model/publishing methods are retired; do not wire them into versioned approval. |
| `scripts/com.contentfactory.*.plist` | Mac templates, not installed by this work. Only Collector/Scout/dashboard belong to the current slice. Maintenance must not be installed. |
| `tests/` | Offline legacy compatibility plus current slice/workflow/safety/hybrid regression fixtures. |

Collector and Scout are independent one-shot processes. The development drivers
invoke workers sequentially but all handoffs are persisted in SQLite. A local
workflow pass may advance one item across several stages; it does not drain the
backlog. A no-output result may mean idle, clarification, collision, cancellation
or failure; inspect the dashboard's persisted stopping state.

## Safe handoff and local operation

Use an isolated Python environment. `uv.lock` freezes dependency resolution and
artifact hashes; `uv sync --locked --extra dev` installs that resolution. Pinned
build tools and packaged SQL have a clean installed-wheel migration regression.
The lock and suite are verified in an isolated Windows installation, not on Mac.
Font bundles and Mac supervision acceptance remain future/deployment work.
Generated egg-info is build output, not an editable project contract.

### Detection and local scaffold

```powershell
py scripts/setup_detection.py
py scripts/setup_workflow.py
py scripts/serve_dashboard.py
```

Setup is explicit, not worker startup. Detection setup accepts a validated v1,
v2 or v3 database without downgrading it, and validates its manifest before
schema writes. Its default manifest is still the historical detection-v1
release: do not reapply that default after hybrid rollout unless deliberately
rolling back configuration.

`run_detection.py` makes real source requests, including quota-bearing YouTube
calls, but no model call. Collector/Scout wrappers are the separated scheduler
entrypoints. The dashboard defaults to `http://127.0.0.1:8787/`; loopback IPv4,
localhost and an IPv6-aware `::1` server class are supported. No live listener
was started or provider requested by this repair.

To demonstrate offline downstream stages:

```powershell
py scripts/enable_placeholder_route.py --confirm-local-placeholder
py scripts/create_local_idea.py "Explain a useful learning habit" --command-id demo-idea-1
py scripts/run_workflow.py
```

Use a separate explicitly named database/artifact root for isolated demos.
All these commands support `--database`; the workflow driver also supports
`--artifacts`. Fixture registration is idempotent for identical input and
rejects changed immutable input. A new active configuration release does not
inherit fixture capabilities automatically.

Continue an open thread with `create_local_idea.py "Your refinement"
--thread-id <id> --row-version <displayed-version> --command-id <unique-id>`.
The thread ID/version is shown in the read-only workflow view. Reuse command
IDs only for identical retries. Messages are limited to 8,000 characters;
serialized frozen conversation is capped at 32,000 and failure is explicit.
Do not paste secrets or personal data.

### Explicit hybrid scoring rollout

The operator approved live fast signals plus completed Wikimedia reports.
The implementation and fixture tests are present, but **this repair has not
migrated or activated the existing development database**.

After stopping affected workers and taking a verified backup of the exact v2
database, the explicit command is:

```powershell
py scripts/setup_scoring.py --database C:\absolute\path\to\content.db
```

This adds safety v3 and activates `detection-hybrid-v2`. It preserves old
migration checksums, immutable snapshots, candidate identities and selected
handoffs; it does not enable production model/delivery workers. Compatible source
configurations retain historical inputs; quota reservations continue across
releases. An interrupted activation can safely be rerun after inspection.

### Normalized detection experiment

`canonicalization_v2` fixes punctuation-equivalent title keys and preserves
meaningful repeated/trailing URL slashes. To avoid silently renaming/merging old
opportunities, configuration activation cannot cross normalization versions in
an existing database. After selecting a new development database filename:

```powershell
py scripts/setup_normalized_detection.py --database C:\absolute\existing-directory\new-experiment.db
```

The command refuses existing files, creates schema v3 and activates
`detection-normalized-v3` (manifest schema 3, attention formula 2, normalization 2).
The original database and all handoffs remain untouched. This is a separate
experiment, not a migration of old conversations or publication history. Do not
point production delivery at a fresh DB to bypass historical duplicate guards.
No runtime database was created or switched by this repair; rollout is a user
decision. In-place identity conversion would need a separately tested migration.

Workers never rebuild/migrate at startup. `setup_detection.py --rebuild` refuses
without moving the DB/WAL/SHM. For a disposable experiment, choose a new explicit
database filename rather than resetting an existing database to fix a mismatch.
No production backup/restore-verification/retention command exists yet.

## Configuration actually consumed

Versioned detection/setup/reporting and demo composition roots load optional
root `.env`; process values win, then explicit CLI paths override defaults.
The new scoring setup requires an explicit database argument and has no secret
dependency. Relative configured paths resolve from process working directory.

| Setting | Current use |
| --- | --- |
| `CONTENT_FACTORY_DB_PATH` | Versioned DB path, default checkout `data/content.db`; retired legacy code must never share it. |
| `YOUTUBE_API_KEY` | Current source adapter's named credential reference. |
| `CONTENT_FACTORY_ARTIFACT_ROOT` | Offline HTML preview root; overridden by `--artifacts`. |
| `CONTENT_FACTORY_DASHBOARD_HOST`, `CONTENT_FACTORY_DASHBOARD_PORT` | Loopback server; defaults 127.0.0.1 / 8787. |
| `CONTENT_FACTORY_DASHBOARD_PATH` | Static detection-only snapshot output. |
| `CONTENT_FACTORY_REPORT_LIMIT` | CLI candidate limit, clamped to 1–100. |
| `CONTENT_FACTORY_BACKUP_ROOT` | Reserved target setting; no production maintenance consumer. |

Source endpoints forbid userinfo and known credential/signed parameters.
Collection connects only to validated public numeric IP addresses while retaining
TLS hostname verification; environment proxies cannot bypass this check.
Diagnostics redact URLs/token patterns and bound safe text. Authoritative human
messages are not rewritten. These guards are not a completed privacy/security audit.

## Retired and externally authorized commands

`run_intake.py`, `run_determination.py`, `run_pipeline.py`, `run_poc.py`,
`run_posting.py`, `smoke_test_o2_instagram.py` and `cleanup_data.py` refuse
their superseded operational paths. Real legacy Gemini generation and
Instagram/Bluesky publishing also fail closed when called directly.
Historical fake-provider/unit-test behavior is not current delivery authorization.

`test_r2_public_asset_store.py` remains a separately authorized external
upload/read/delete probe. `test_instagram_credentials.py` is a separately
authorized external account read. Neither is an offline acceptance command.
The legacy renderer is a local compatibility utility, not the new production
static-profile renderer.

## Verification and roadmap

Run `py scripts/run_tests.py` and `py scripts/check_docs.py`. Current tests use
temporary DBs/fakes; live Gemini/Meta/X/R2/provider calls, Mac launchd behavior,
real static output quality, actual backup restore and unattended load are not
verified.

The [active audit](../audit_report.md) lists genuine review/rollout items. Per the
user's scope clarification, unbuilt production identity/reuse/recurrence, semantic
schemas, browser commands, budgets, real renderer, review/posting and maintenance
remain in the [implementation plan](plans/target-implementation.md#audit-to-plan-disposition).
Moving them to the plan does not mean they are implemented. Resolved finding
evidence remains in the separate audit history, not the active action list.
