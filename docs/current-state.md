# Current implementation and operations

**As-built snapshot:** 2026-09-13. Code and boundary tests establish actual
behavior. [System guide](system.md) routes target requirements; the root
[audit report](../audit_report.md) preserves repair and verification history.
Neither migration nor a green offline suite enables public posting.

## Current state

Content Factory currently supports deterministic trend collection and hybrid
shortlisting, human idea/refinement intake, Gemini-guided five-domain routing
and content production, local static rendering, exact human review, and an
opt-in credentialed path for Instagram carousels and X single-image posts. All
handoffs are persisted in one versioned SQLite database.

The default runner is still a non-deliverable fixture. Real-account mode is a
separate schema-v4 path and fails closed unless the operator has materialized an
immutable destination/profile release, supplied priced model limits, recorded a
current storage sample, passed explicit live readiness checks, and clicked
**Post now** for the exact destination package. No migration, worker start, or
editorial approval authorizes a public post.

| Capability | State today |
| --- | --- |
| Detection | **Implemented.** Bounded NASA RSS, Wikimedia, YouTube, and HN adapters feed deterministic normalization, evidence snapshots, scoring, and shortlist handoffs. Active development uses `canonicalization_v2` + hybrid `attention_v2` in a fresh Option B database. Detection remains LLM-free. |
| Human idea and refinement | **Implemented.** CLI and CSRF-protected loopback dashboard commands persist new ideas or versioned replies. Gemini Intake creates a route-neutral brief or records a clarification question; Gemini Determination evaluates exactly five domains and may create zero, one, or several jobs. |
| Generation and adaptation | **Implemented with bounded gaps.** Gemini workers validate five domain payloads, source-claim links, Instagram 5–8-card carousel packages, and weighted X single-post text. Production adaptation checkpoints the body before independent bounded metadata attempts. Full research/reference-quality verification and cross-revision canonical reuse remain future work. |
| Rendering and review | **Implemented.** Playwright renders exact 1080×1350 Instagram or 1200×675 X assets; Pillow produces delivery JPEGs. Production rendering uses a pinned, fingerprinted local font, verifies dimensions/hashes, fsyncs before promotion, quarantines failed runs, and never overwrites a completed directory. Review decisions remain per destination. |
| Production configuration | **Implemented.** Schema v4 persists immutable real destinations, account policies, output bindings, renderer/font fingerprints, and configuration history. Configuration is CLI-only and requires an explicit operator assertion that the current static profiles were reviewed. |
| Model admission | **Implemented.** Production calls require positive input/output prices, phase token maxima, a daily warning, daily hard limit, and per-job hard limit. Worst-case cost is reserved before the call and settled from usage afterward. A daily exhaustion defers the claim until the next UTC day; a job-cap failure is terminal. Exact provider tokenization is not pre-counted, so a 32,000-character frozen-input cap and configured worst-case reservation are the current guardrails. |
| Destination readiness | **Implemented with live verification required.** Readiness records expire after six hours when ready and after 15 minutes when blocked. Live checks verify configured Meta/X account identity; Instagram additionally requires an explicit transient R2 put/head/public-get/delete probe. These checks do not prove provider app review, every write permission, quotas, or future token lifetime. |
| Human delivery authorization | **Implemented.** The dashboard creates one immutable PostRequest/PostRecord only for current, delivery-ready, hash-valid assets and one ready destination. Post now respects account cadence and expires before the final send. Pre-final cancellation is fenced; after the durable final-request marker, the result can only become published or publication-unknown. |
| Instagram/X delivery | **Implemented; live calls unverified.** A shared agent validates the approved bytes, records an attempt before side effects, and dispatches to a small Meta or X adapter. Instagram uses transient R2 media and child/parent carousel containers; X uploads media, applies alt text, then creates one post. X threads are disabled. No posting code generates or changes creative. |
| Failure, cleanup, reconciliation | **Implemented for the current single-post formats.** Retry-safe pre-final failures are bounded; a possibly sent final request is never retried automatically. R2 cleanup has its own durable tasks. Publication-unknown requires an explicit dashboard reconciliation request and, when unresolved, an explicit human outcome. |
| Storage and maintenance | **Implemented locally.** A five-minute storage sample gates new production work. Maintenance performs SQLite online backup, checksums, integrity and migration validation, safe WAL checkpointing, optional temporary restore verification, and conservative retention of tracked/hash-matching backups. Off-device backup and automatic artifact/high-volume SQL retention are not implemented. |
| Dashboard | **Implemented as the local HAI.** It displays detection, conversations, briefs, five route reasons, job/run/package state, exact review assets, storage/budget/readiness summaries, delivery attempts, cleanup, and reconciliation. Its POST handler creates narrow SQLite commands only; it never invokes a worker or provider directly. |
| Runtime | **Partial.** Polling processes and review/readiness/maintenance `launchd` templates exist. Detection, workflow stages, readiness, storage, and maintenance persist bounded heartbeat state; substantive workflow results append run summaries without idle-poll spam. Ten-minute local-stage leases now match the runtime envelope. Long calls still lack lease renewal/capacity allocation, templates are not installed, and unattended Mac Mini/load acceptance has not run. |
| Recurrence/reuse | **Planned.** Existing candidate identity prevents duplicate initial seeds, but the target recurrence, material-new-evidence, cooldown, and canonical-reuse policy is not complete. |

## Architecture and project map

The current production chain is:

```text
source or human message
  -> ContentThread -> IntakeRequest -> immutable BriefRevision
  -> DeterminationRequest -> five route assessments
  -> selected domain/angle ContentJob -> GenerationRun -> CanonicalContent
  -> one OutputRequest per eligible destination -> AdaptationRun
  -> ContentPackage -> RenderRun -> exact ReviewRequest
  -> human Post now -> PostRequest/PostRecord -> Posting Agent
  -> provider resources/outcome -> cleanup or explicit reconciliation
```

Components never call the next worker directly. Each stage claims its own row;
the sequential development runner merely polls the stages in a convenient order.

| Location | Current responsibility |
| --- | --- |
| `src/detection/` | Source configuration, bounded collection, immutable evidence, canonicalization, deterministic scoring, clustering, and shortlist. |
| `src/database/migrations.py`, `docs/contracts/*schema-v*.sql` | Explicit v1 detection, v2 editorial, v3 detection-safety, and v4 production forward migrations with recorded checksums and validation. |
| `src/workflow/store.py`, `workers.py`, `gemini_*.py` | Persisted commands/claims, fixture workers, and opt-in Gemini Intake, Determination, generation, and adaptation. |
| `src/workflow/static_renderer.py` | Shared local HTML/CSS + Playwright/Pillow renderer, profile enforcement, artifact validation/promotion. |
| `src/workflow/model_budget.py`, `readiness.py` | Priced Gemini admission and expiring destination readiness. |
| `src/workflow/preflight.py`, `scripts/check_smoke_readiness.py` | Read-only, non-network preview/production/delivery preflight with safe blocker reporting. |
| `src/workflow/delivery.py` | R2 transient relay, Instagram/X adapters, credentialed Posting Agent, cleanup, and read-only reconciliation. |
| `src/workflow/maintenance.py` | Storage admission samples and audited SQLite backup/checkpoint/restore/retention. |
| `src/dashboard/`, `scripts/serve_dashboard.py` | Read model, manifested asset serving, and narrow human SQLite commands on loopback. |
| `scripts/run_workflow.py` | Explicit one-pass or polling composition root for fixture, review-preview, production, and delivery modes. |
| `src/common/environment.py`, `gemini.py`, `diagnostics.py`, `legacy.py` | Literal environment loading, Vertex JSON client, safe diagnostics, and fail-closed retired boundaries. |
| `src/database/sqlite.py`, `src/intake/`, `src/determination/`, `src/pipelines/`, `src/posting/` | Incompatible legacy/reference family. Its operational entrypoints remain retired; do not wire it into the versioned workflow. |
| `scripts/com.contentfactory.*.plist` | Mac `launchd` templates only. Operators must review absolute paths and explicitly install them. |

## Runner modes

| Flags | Behavior |
| --- | --- |
| none | Deterministic fixture workers and non-deliverable placeholder artifacts. |
| `--gemini` | Gemini Intake and Determination; auto-registers five synthetic domain × Instagram/X capabilities. |
| `--gemini --review-preview` | Also enables Gemini domain generation/adaptation and real local review rendering. Synthetic destinations remain non-deliverable. |
| `--gemini --review-preview --production` | Uses the immutable v4 real-destination catalog, priced admission, production checkpoints/profiles, and storage gate; does not run posting adapters. |
| add `--delivery` | Also polls credentialed Posting, R2 cleanup, and reconciliation workers. Only a separately authorized Post now record is eligible. |
| add `--poll` | Repeats passes until Ctrl+C; `--poll-interval` defaults to five seconds. |

## Explicit hybrid scoring rollout

`setup_scoring.py --database <exact-existing-path>` remains the in-place path
for a deliberately retained same-normalization database. It adds safety v3 and
activates hybrid `attention_v2` without relabeling old observations. It is not
the active development-data choice and does not convert canonical identities.

## Normalized detection experiment

`setup_normalized_detection.py --database <new-path>` creates the selected
Option B database with `canonicalization_v2` and `attention_v2`. It refuses an
existing file and never migrates or alters the legacy database. Production v4
is allowed only on this active normalized experiment.

## Production setup and operation

### 1. Create the active development database

Decision 035 selected Option B: active development uses a fresh normalized
experiment and preserves the legacy database without migration.

```powershell
py scripts/setup_normalized_detection.py --database data/dev-normalized.db
py scripts/setup_production.py --database data/dev-normalized.db
```

The first command creates v1–v3 including the editorial workflow, activates
`detection-normalized-v3`, and refuses an existing file. The second command
refuses a database whose active release is not both `canonicalization_v2` and
`attention_v2`, then applies v4. It never converts a legacy identity namespace.
See [decision 035](archive/decisions.md#035---development-database-uses-fresh-normalized-experiment).

Install the pinned browser once in the selected Python environment:

```powershell
playwright install chromium
```

### 2. Supply secrets and explicit operating limits

Copy `.env.example` to the ignored `.env`. Production requires:

- Vertex project/location/model, Application Default Credentials, positive
  price inputs, daily warning/hard budgets, and a per-job hard budget;
- an absolute local production font path and optional expected SHA-256;
- artifact and backup roots;
- enabled Instagram and/or X account keys and numeric provider IDs;
- Instagram access token plus R2 S3 credentials, bucket, account ID, and a
  dedicated HTTPS custom public domain; and/or an X OAuth user access token.

Environment values do not activate accounts. They are either secrets resolved
at runtime or inputs validated and frozen by the next command.

### 3. Review and freeze the real destination catalog

Render and inspect representative fixture previews first. Then deliberately
record acceptance of the current static profiles:

```powershell
py scripts/configure_production.py --database data/dev-normalized.db \
  --approve-current-static-profiles
```

The command freezes all five domains against each enabled real destination,
the font fingerprint, adapter/profile versions, account IDs, and finite cadence
policy. It is idempotent only for identical immutable input; change requires a
new database/configuration release mechanism rather than silent mutation.

### 4. Establish readiness, backup, and storage evidence

These commands make read-only account calls; the R2 flag additionally authorizes
one random transient put/head/public-get/delete probe. They do not publish:

```powershell
py scripts/check_production_readiness.py --database data/dev-normalized.db \
  --live --confirm-transient-r2-write
py scripts/run_maintenance.py --database data/dev-normalized.db \
  --artifacts data/artifacts --backups data/backups --restore-verify
py scripts/check_smoke_readiness.py --database data/dev-normalized.db \
  --artifacts data/artifacts --backups data/backups --mode delivery
```

Readiness must stay current. A scheduler may use `--only-due`. Backup pruning is
never implicit; `--prune-backups` removes only surplus files that match prior
successful audit records and hashes. Unknown files are left alone.
The final command is offline and read-only: it checks schema/integrity,
dependencies, configured secret references, priced limits, immutable catalog,
font fingerprint, current storage, audited backup, and current persisted live
readiness. It returns exit code 2 while any blocker remains and never prints a
secret value. A green report still cannot prove ADC validity, provider scopes,
visual quality, or publication behavior.

### 5. Run workers and the dashboard

```powershell
py scripts/run_workflow.py --database data/dev-normalized.db \
  --artifacts data/artifacts --backups data/backups \
  --gemini --review-preview --production --delivery --poll

py scripts/serve_dashboard.py --database data/dev-normalized.db \
  --artifacts data/artifacts
```

Submit or refine an idea in the dashboard (or with `create_local_idea.py`). The
workers may produce independently reviewable Instagram/X packages. Editorial
acceptance does not publish. For each destination, recheck the exact asset/text
and click **Post now**; cadence may make “now” the earliest policy-compliant
time. The polling Posting Agent is the only new code path allowed to deliver it.

The workflow, readiness, maintenance, collector, scout, and dashboard plists are
templates—not installed services. Review their absolute Python/repository/data
paths, log locations, intervals, and environment handling before copying them
into `~/Library/LaunchAgents`.

## Safe fixture and review operation

For a no-provider demo, register one route and run the default workers:

```powershell
py scripts/enable_placeholder_route.py --confirm-local-placeholder
py scripts/create_local_idea.py "Explain a useful learning habit" --command-id demo-idea-1
py scripts/run_workflow.py
```

For Gemini-assisted review without any deliverable account binding:

```powershell
py scripts/check_smoke_readiness.py --database data/dev-normalized.db --mode preview
py scripts/run_workflow.py --database data/dev-normalized.db \
  --gemini --review-preview --poll
```

The lowercase single-dash aliases `-gemini` and `-poll` remain accepted. Gemini
tests use fakes; no routine verification command makes a live model/provider
call. Human messages are limited to 8,000 characters and frozen model input to
32,000 characters; do not paste credentials, private URLs, or personal data.

## Configuration actually consumed

Composition roots load the optional root `.env` literally. Process environment
values win, then explicit CLI arguments override path defaults.

| Setting | Current use |
| --- | --- |
| `CONTENT_FACTORY_DB_PATH` | Versioned database path; never share it with `src/database/sqlite.py`. |
| `CONTENT_FACTORY_ARTIFACT_ROOT`, `CONTENT_FACTORY_BACKUP_ROOT` | Rendered assets and audited backups/storage sampling. Production requires a backup root. |
| `CONTENT_FACTORY_FONT_PATH`, `CONTENT_FACTORY_FONT_SHA256` | Absolute reviewed production font and optional independent expected hash. |
| `GOOGLE_CLOUD_PROJECT`, `GOOGLE_CLOUD_LOCATION`, `GEMINI_MODEL` | Vertex connection/model (`gemini-2.5-flash` default). Project is required before a call. |
| `GEMINI_*COST*`, `GEMINI_*LIMIT*`, phase token maxima | Positive price snapshots and production reservation/admission policy. See `.env.example` for exact names/default token maxima. |
| `INSTAGRAM_ACCESS_TOKEN`, `INSTAGRAM_ACCOUNT_KEY`, `INSTAGRAM_USER_ID`, `META_GRAPH_API_VERSION` | Meta credential reference and immutable destination inputs. |
| `R2_ACCESS_KEY_ID`, `R2_SECRET_ACCESS_KEY`, `R2_ACCOUNT_ID`, `R2_BUCKET_NAME`, `R2_PUBLIC_DOMAIN` | Transient Instagram media relay. The public domain must be dedicated HTTPS, not `r2.dev`. |
| `X_USER_ACCESS_TOKEN`, `X_ACCOUNT_KEY`, `X_USER_ID` | X OAuth user credential and immutable destination inputs. |
| `YOUTUBE_API_KEY` | Current YouTube detection adapter. |
| `CONTENT_FACTORY_DASHBOARD_HOST`, `CONTENT_FACTORY_DASHBOARD_PORT` | Loopback dashboard, default `127.0.0.1:8787`. |
| `CONTENT_FACTORY_DASHBOARD_PATH`, `CONTENT_FACTORY_REPORT_LIMIT` | Static detection report path and clamped report limit. |

Secrets, signed URLs, and authorization headers are not persisted. Safe provider
IDs and typed diagnostics are bounded/redacted. This local-first boundary is not
a completed multi-user privacy/security model.

## Genuine human review and external gates

Code cannot decide or safely simulate these items for the owner:

1. Enter current Gemini prices and choose the daily warning, daily hard limit,
   per-job hard limit, and optional phase token maxima.
2. Inspect representative assets and approve—or reject/change—the bundled
   Instagram/X layouts, pinned font, alt text, copy, and brand quality.
3. Confirm real account IDs, destination selection, custom R2 domain, daily cap,
   minimum interval, and 48-hour authorization TTL before freezing configuration.
4. Run the explicitly authorized live readiness probes and verify Meta/X app
   access, scopes, quotas, account status, and R2 lifecycle policy.
5. Observe the first deliberately authorized post to each real destination and
   reconcile any externally ambiguous result; offline fakes cannot prove live
   provider behavior.
6. Review and install the Mac Mini `launchd` templates, then perform unattended
   restart, sleep/wake, load, backup/restore, disk-pressure, and log monitoring
   acceptance.

## Smoke-test boundary

There is no known repository-code blocker to a **supervised preview smoke** once
the preview preflight passes and the owner authorizes one bounded Gemini run.
A real delivery smoke additionally requires the immutable production catalog,
current normal storage evidence, a verified backup, resolved secret references,
current live destination readiness, exact asset/text review, and Post now for
one destination. Provider failures discovered by that run are evidence for a
specific repair; offline tests cannot responsibly pre-fix an unknown response.

The following do **not** block a one-item supervised smoke, but do block a claim
of unattended production readiness: lease renewal during long calls, capacity
admission, installed/supervised Mac services, off-device recovery, automated
artifact/SQL retention, and sustained load/restart evidence.

| Residual item | Why it remains | Supervised one-item smoke impact |
| --- | --- | --- |
| Gemini/account/profile/policy choices and live readiness | Owner authority, current provider state, and credentials cannot be inferred or safely simulated. | Blocking at the applicable preview/production/delivery level. |
| Routing/reference-quality corpus | Accepted labels and evidence standards are editorial judgments; generated self-labels would not be acceptance evidence. | Not a structural blocker; owner must review the smoke output. |
| Mid-call renewal, capacity, process isolation, full restart telemetry | Requires a separately reviewed concurrency/supervision design and sustained runtime evidence. | Not blocking for one supervised item; required before unattended or concurrent scale. |
| Detection storage admission | V1–v3 detection compatibility and collection evidence policy need a deliberate forward design; silently applying the v4 creative gate would change the stable milestone. | Human-idea smoke is unaffected; full unattended detection remains partially hardened. |
| Artifact/SQL retention and off-device recovery | Deletion policy is destructive and an off-device target is an operator/infrastructure choice. | Not blocking for one item; required before valuable history accumulates. |
| Canonical reuse and recurrence | Needs product policy for material new evidence, cooldown, and creative identity rather than speculative deduplication. | Not blocking the first content item. |
| Standalone payload schemas and visual goldens | In-code closed validators run today; an accepted visual golden requires owner approval. | Not a runtime blocker. |
| X threads | Optional Phase 1 extension needing per-step public-side-effect state. | Disabled and not part of the single-post smoke. |

## Remaining technical scope

- There is no integrated research/browser service; evidence identity is checked,
  but nuanced factual/reference quality still needs editorial review.
- Worker leases are fenced, use the documented initial durations, and expired
  claims recover conservatively. Basic process/stage heartbeats are visible,
  but there is no mid-call lease renewal or production capacity allocator.
- Detection workers do not yet share the v4 storage admission matrix.
- Retention covers verified database backups only; artifact/SQL retention,
  off-device copies, and an operator-led disaster-recovery runbook remain.
- Cross-revision canonical reuse, recurrence/cooldown/material-new-evidence,
  portfolio scheduling, richer observability, and X threads remain planned.

## Retired paths and verification

`run_intake.py`, `run_determination.py`, `run_pipeline.py`, `run_poc.py`,
`run_posting.py`, `smoke_test_o2_instagram.py`, and `cleanup_data.py` refuse their
superseded operational paths. Old Instagram/Bluesky publisher writes remain
blocked by `refuse_legacy_operation()`. The shared Vertex JSON client is restored
only for the versioned opt-in workflow workers.

`test_r2_public_asset_store.py` and `test_instagram_credentials.py` are separately
authorized external probes, not routine acceptance. Routine verification is:

```powershell
py scripts/run_tests.py
py scripts/check_docs.py
```

The offline suite covers migrations, fake Gemini/provider boundaries, budget and
storage gates, exact asset hashes, Post now/cancellation, uncertain publication,
cleanup/reconciliation, backup/restore, runtime heartbeats, and non-network
smoke preflight. Live Gemini, R2, Meta, and X calls;
visual quality approval; installed launchd behavior; and sustained unattended
operation remain explicitly unverified until the owner runs the gates above.
