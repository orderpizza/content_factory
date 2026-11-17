# Current implementation and operations

The [architecture](architecture.md) describes the current generation/review pipeline and offline delivery authorization.
Authoritative settings and budgets are in [configuration](specs/configuration.md),
and the schema/bootstrap contract is in [data model](specs/data-model.md).

Repository cleanup does not erase ignored local Mac Mini databases, logs,
artifacts or secrets. Do not delete them as part of remote cleanup. Any local
cleanup needs separate authorization, verified paths and recoverable backups.

## Fresh setup

Use the existing `.venv`. On a fresh machine install Python 3.10+ and uv, then:

```sh
uv sync --frozen --extra dev
.venv/bin/python -m playwright install chromium
```

Chromium supports browser tests. Copy
`.env.example` to ignored `.env` if needed and configure values locally; process
environment overrides the file. See [configuration](specs/configuration.md).
Create a new database using the [database filename convention](specs/data-model.md#schema-and-record-inventory):
setup chooses `data/db_YYYYMMDDHHMMSS.db` automatically, with the creation time
in UTC. It never overwrites an existing database and prints the path it created.

```sh
.venv/bin/python scripts/setup_development.py
```

Setup registers all three domains with one synthetic Instagram binding each and
an initial storage sample; it makes no provider call. `--download-model` explicitly
provisions the pinned public MiniLM files if uncached. System entrypoints
automatically select the matching database with the latest UTC timestamp in its
filename. Start or restart processes after creating a database so they select it.

## Planning and review sessions

Check local prerequisites without network calls:

```sh
.venv/bin/python scripts/check_smoke_readiness.py --mode planning
```

For a review session, run each process in a separate terminal:

```sh
.venv/bin/python scripts/run_detection.py --poll
.venv/bin/python scripts/run_workflow.py --gemini --review-preview --poll
.venv/bin/python scripts/serve_dashboard.py
```

Open http://127.0.0.1:8787. Submit ideas, answer clarification in the same thread,
and inspect evidence, all three routes, jobs and exact review slides.
The Gemini workflow makes paid calls under configured budgets and can consume
pending jobs. [Visual rendering](specs/visual-rendering.md) owns storyboard
processing and the no-automatic-paid-retry boundary.

For planning without generation, use `--gemini --planning-only` instead of
`--gemini --review-preview`. Run only one workflow mode against the session.

Detection polls due work every 30 seconds; workflow polls every five seconds.
`--poll-interval` changes the delay, and Ctrl+C stops cleanly. A healthy collection
need not select an Opportunity. A single-source history needs seven healthy
completed baseline days; before then selection requires two independent groups
within one lexical cluster. Semantic links do not pool scoring credit.
Human ideation is immediately available for every domain.

```sh
.venv/bin/python scripts/create_local_idea.py "teach break the ice in business meetings"
.venv/bin/python scripts/create_local_idea.py "focus on intermediate learners" --thread-id 1 --row-version 2
```

Use the actual thread ID and version. Refinement creates immutable new work.

## Offline database migration for delivery revisions

Schema 19 is required. Startup/bootstrap never migrates a database. For an existing
schema-18 operator DB, first stop all writers (including the dashboard and review
LaunchAgents) and record its exact path. Keep its artifact tree and independent
verified backups. Use an unused backup filename outside the selected primary DB
pattern so backup discovery cannot select it as the current database.

```sh
.venv/bin/python scripts/install_review_baseline.py --stop
.venv/bin/python scripts/migrate_delivery_database.py --database /absolute/operator/db_YYYYMMDDHHMMSS.db
.venv/bin/python scripts/migrate_delivery_database.py --database /absolute/operator/db_YYYYMMDDHHMMSS.db \
  --apply --writers-stopped --backup /absolute/backups/pre-v19.db
```

The default is a read-only dry run: validate the exact v18 checksum, executable
schema, integrity and foreign keys, then exercise the additive migration on an
in-memory snapshot. Apply creates an exclusive SQLite backup (including committed
WAL contents), validates it, checks the stopped DB still matches it under the write
lock, and commits DDL/version/ledger together. Existing rows and the v18 ledger
entry remain; already-current databases validate idempotently. No data reset,
automatic discovery, paid call or provider call occurs.

If interrupted before commit, SQLite rolls back the migration; inspect and rerun
the dry run. Keep any partial backup as diagnostic evidence and use a new backup
path. After commit, rollback means stopping writers and restoring the verified
pre-v19 backup to a **new** DB path with matching v18 code; do not copy over an open
DB or leave unrelated WAL/SHM sidecars beside a restored file. Preserve the v19 DB
and artifacts. Restoring v18 cannot retain later v19 approval/authorization writes;
there is no destructive down-migration. Test restore on a separate copy before
resuming operation. No operator DB is migrated by a code checkout or test run.

## Exact JPEG delivery review

Use an explicit schema-19 database and an existing English PNG review that already
has its frozen account/destination binding. A default development fixture binding
without a destination is ineligible; these commands never assign one retroactively.
The source review must be awaiting or editorially approved, unexpired, with an open
thread and intact local artifacts. The source caption and aggregate alt text are
preserved. Create a UTF-8 JSON array containing one complete alt description per
image in slide order, such as `image-alt.json`. This is human input, not generated
copy. Keep English quality/design refinement deferred to the final phase.

Preparation can run before readiness. Approval and Post now require the existing
active destination, enabled delivery/visual approval and a current ready observation;
no command here probes a provider or fabricates readiness. Post now also requires
a recent admissible storage sample from the existing storage monitor. The account
argument is the frozen account key, not necessarily the domain name `english`.
Replace every uppercase placeholder below with displayed values.

```sh
.venv/bin/python scripts/review_delivery.py --database /absolute/operator/db_YYYYMMDDHHMMSS.db prepare \
  --source-review-id PNG_REVIEW_ID --account ACCOUNT --destination instagram:ACCOUNT \
  --artifacts /absolute/artifacts --output /absolute/artifacts/new-delivery \
  --image-alt-text /absolute/image-alt.json --command-id UNIQUE_PREPARATION_ID
.venv/bin/python scripts/review_delivery.py --database /absolute/operator/db_YYYYMMDDHHMMSS.db report \
  --review-id NEW_JPEG_REVIEW_ID --output /absolute/review-before-approval.html
```

Open the local HTML report and inspect **every JPEG**, the caption, aggregate and
per-image alt text, account/provider ID and destination. Copy the displayed hashes
in order. The report embeds exact JPEG bytes, escapes text and makes no network
request. Approval is an independent explicit action:

```sh
.venv/bin/python scripts/review_delivery.py --database /absolute/operator/db_YYYYMMDDHHMMSS.db approve \
  --review-id NEW_JPEG_REVIEW_ID --row-version DISPLAYED_VERSION --fingerprint DISPLAYED_FINGERPRINT \
  --account ACCOUNT --destination instagram:ACCOUNT --reviewed-images HASH1 HASH2 HASH3 HASH4 HASH5 HASH6 \
  --confirm-reviewed-all --command-id UNIQUE_JPEG_APPROVAL_ID
.venv/bin/python scripts/review_delivery.py --database /absolute/operator/db_YYYYMMDDHHMMSS.db report \
  --review-id NEW_JPEG_REVIEW_ID --output /absolute/review-after-approval.html
```

Supply exactly the number of images in the report (4–6). Approval creates no
request or send. Use the **new** version/fingerprint from the second report only
when independently choosing Post now:

```sh
.venv/bin/python scripts/review_delivery.py --database /absolute/operator/db_YYYYMMDDHHMMSS.db post-now \
  --review-id NEW_JPEG_REVIEW_ID --row-version NEW_VERSION --fingerprint NEW_FINGERPRINT \
  --account ACCOUNT --destination instagram:ACCOUNT --command-id UNIQUE_POST_NOW_ID
```

Post now appends the existing approved PostRequest and pending PostRecord, subject
to cadence/expiry. It does not run delivery. There is **no production send command**,
real adapter, R2 upload, paid Gemini call or publication in Phase 3B1. Do not run the
simulation against this DB. Reusing an identical command ID returns its original
result; changed arguments, stale fingerprints, altered/missing assets, wrong
account/destination or revoked readiness fail closed. A different delivery revision
for the same canonical content/destination cannot create a second authorization.

Corrections require a new preparation directory/revision and human approval; old
records are retained. The CLI accepts no arbitrary candidate import. Failed
preparation may leave an unregistered directory that cannot become delivery work;
inspect it and choose a new directory for a new command rather than overwrite it.
[Posting](specs/posting.md) owns the full state and future adapter contract.

## Instagram integration status

Phase 3B2 has fake-provider state-machine tests and fail-closed readiness primitives,
but no live delivery command or authenticated preflight. Do not construct a live
adapter from those primitives. An Instagram staging object marked for manual
ingestion-safety retention is not eligible for the automatic cleanup queue; no
operator release procedure or safe retention duration is established yet. See the
[posting contract](specs/posting.md#offline-instagram-login-protocol-experiment-phase-3b2-incomplete)
for the remaining activation prerequisites and evidence limitations.

## Offline delivery rehearsal

These commands use synthetic content and fake providers only. `init` creates a new
retained temporary directory by default and prints its path, JPEG paths, caption,
alt text, review identity and state. It does not approve anything. Optional
`--workspace /path/to/new-directory` refuses an existing directory. No production
DB is selected, `.env` loaded, credential read or network connection made.

```sh
.venv/bin/python scripts/simulate_delivery.py init
.venv/bin/python scripts/simulate_delivery.py report --workspace /printed/workspace
```

Inspect every listed **JPEG**, caption and alt text. For a deliberately simulated
authorization, copy the displayed identity and version into the explicit command:

```sh
.venv/bin/python scripts/simulate_delivery.py post-now --workspace /printed/workspace \
  --review-id 1 --row-version 1 --review-identity DISPLAYED_IDENTITY \
  --destination instagram:simulation --command-id unique-review-command
.venv/bin/python scripts/simulate_delivery.py run --workspace /printed/workspace
```

Post now only writes authorization; `run` executes one fake-provider attempt.
Use a fresh workspace per scenario. `run --outcome unknown` rehearses a lost final
response; `run --outcome outage` fails before the final marker. Repeated/restarted
runs do not resend successful or uncertain posts. Retryable staging observes the
store's bounded retry delay. Reports always label results simulated and expose
hashes, authorization, attempts, fake sends, cleanup and reconciliation evidence.
No arguments or environment settings can switch this command to real publishing.

For an uncertain post, request an unavailable lookup and inspect the resulting
check/version before explicitly resolving it:

```sh
.venv/bin/python scripts/simulate_delivery.py reconcile --workspace /printed/workspace \
  --post-id 1 --command-id unique-reconcile-command
.venv/bin/python scripts/simulate_delivery.py resolve --workspace /printed/workspace \
  --request-id 1 --check-id 1 --row-version DISPLAYED_VERSION \
  --decision leave_unknown --note "Synthetic evidence is inconclusive" \
  --command-id unique-resolution-command
.venv/bin/python scripts/simulate_delivery.py cleanup --workspace /printed/workspace
```

Resolution also supports `published` or `not_published_cancel` for explicit
synthetic manual decisions; none authorizes reposting. `cancel --post-id ID
--row-version VERSION --command-id ID --workspace PATH` works before the final
marker. Cleanup processes due fake objects separately from publication state.
Keep the workspace for inspection; no automatic deletion or operator data cleanup
occurs. See [posting](specs/posting.md) for the full boundary and real-integration gaps.

To prepare candidates from an existing English PNG review without changing its DB:

```sh
.venv/bin/python scripts/prepare_delivery_artifacts.py --database /explicit/operator.db \
  --review-id 1 --artifacts /configured/artifact/root --output /new/candidate-directory
```

The output parent must exist. This writes only a new local candidate directory;
PNG approval is not copied. This export cannot be imported as authorization. Use
the [separate revision workflow](#exact-jpeg-delivery-review) to prepare directly
from trusted source evidence and persist a new JPEG review. Existing source records
remain unchanged; schema 19 migration is always explicit.

## Verification and live acceptance

Run offline checks as described in [testing](testing.md). Live review sessions
and the Mac Mini Gemini poller below make paid calls and require explicit
authorization, credentials and finite budgets. The isolated acceptance runner's
commands are maintained in [its guide](../acceptance/README.md).

## Monitoring and maintenance

Planning ignores storage admission, including missing/stale/critical samples;
actual SQLite/OS errors still fail. Generation/adaptation/render gates remain
separate. The workflow refreshes advisory samples; an independent model-free
monitor is also available:

```sh
.venv/bin/python scripts/run_storage_monitor.py --poll
```

The dashboard shows daily row/JSON growth and component sizes. Measurement never
deletes data. [Reliability](specs/reliability.md#storage-backup-and-retention)
owns backup/retention and [runtime](specs/runtime.md#diagnostic-logging) owns safe
rotating diagnostics. The dashboard refreshes every ten seconds, preserving drafts.

### Continuous review-only Mac Mini baseline

After explicit setup of a new current-schema database, install the supported
review-only baseline with one shared set of absolute paths:

```sh
.venv/bin/python scripts/install_review_baseline.py --install \
  --artifacts data/artifacts/review-baseline \
  --backups data/backups/review-baseline
```

It writes five user LaunchAgents: one Detection poller, one Gemini
`--review-preview` workflow poller, one loopback dashboard at
http://127.0.0.1:8787, one model-free storage monitor, and a daily 03:15 local
backup/restore-verification pass. The first four have launchd restart policy;
the backup worker is scheduled rather than continuously restarted. Secrets stay
in the local `.env` and are not copied to plist files. Logs are PID-rotated by
the workers and service stdout/stderr goes under `data/logs/review-baseline`.

The installer never creates or migrates a database. Preview generated plists
without loading them by replacing `--install` with `--write-only`; inspect all
five load states with:

```sh
.venv/bin/python scripts/install_review_baseline.py --status
```

Use a new dashboard port through `--port` when 8787 is already occupied. Before
calling the baseline healthy after restart, run `--status`, open the loopback
dashboard, and inspect the persisted worker heartbeats, storage sample and latest
successful backup/restore-verification evidence.

### Review baseline lifecycle

Install (or reinstall) the five owned LaunchAgents with the `--install` command
above. Inspect their load state with:

```sh
.venv/bin/python scripts/install_review_baseline.py --status
```

Stop only the active review-baseline services while retaining their plist files:

```sh
.venv/bin/python scripts/install_review_baseline.py --stop
```

Run the `--install` command again to restart/reinstall the baseline. To stop it
and remove only its five plist files, use:

```sh
.venv/bin/python scripts/install_review_baseline.py --uninstall
```

Do not kill worker PIDs to stop the baseline: launchd `KeepAlive` restarts the
continuously running services. `--stop` and `--uninstall` are idempotent and do
not affect unrelated LaunchAgents.

## Operator entrypoints

| Script in `scripts/` | Responsibility |
| --- | --- |
| `setup_development.py` | Fresh database, Detection release, three-domain catalog and initial storage sample |
| `run_detection.py` | Due collection and Scout; `--skip-collection` or `--skip-scout` narrows a pass |
| `run_workflow.py` | Planning or Gemini review workers, with advisory storage monitoring |
| `serve_dashboard.py` | Live loopback dashboard and persisted human commands |
| `create_local_idea.py` | Submit an idea or reply/refine a thread |
| `run_storage_monitor.py` | Independent model-free storage/growth observation |
| `run_maintenance.py` | Verified backup/checkpoint; explicit restore verification or backup pruning |
| `install_review_baseline.py` | Write/load/status the five review-only Mac Mini LaunchAgents |
| `check_smoke_readiness.py` | Read-only local planning/preview prerequisite checks |
| `migrate_delivery_database.py` | Explicit v18→v19 dry run, verified backup and additive offline migration |
| `review_delivery.py` | Production-source preparation, read-only local report, separate JPEG approval and Post now; never sends |
| `prepare_delivery_artifacts.py` | Read-only PNG review export to a new, unapproved JPEG candidate |
| `simulate_delivery.py` | Isolated synthetic review, explicit fake Post now, delivery/recovery and read-only report |
| `run_tests.py` | Offline suite, including local browser and packaging checks |
| `check_docs.py` | Documentation links, schema, sources, domain and environment consistency |

Explicit maintenance example:

```sh
.venv/bin/python scripts/run_maintenance.py --backups data/backups --restore-verify
```

Maintenance does not prune backups unless `--prune-backups` is supplied.

## Project map

| Path | Responsibility |
| --- | --- |
| `src/database/current.py` | Explicit initialization and schema validation |
| `src/detection/` | Public collection, normalization, semantic resolution, scoring and Scout |
| `src/workflow/store.py` | Transactions, claims, immutable handoffs and commands |
| `src/workflow/catalog.py` | Three editorial remits and catalog read model |
| `src/workflow/gemini_intake.py`, `gemini_determination.py` | Intake and domain eligibility |
| `src/workflow/editorial_planning.py` | Closed editorial strategy, immutable plans and bounded history |
| `src/workflow/content_contract.py` | Resolved copy capacity, bounded English content count and deterministic semantic QA |
| `src/workflow/model_trace.py` | Execution-time request capture and existing-ledger cost projections |
| `src/workflow/gemini_generation.py`, `gemini_adaptation.py` | Canonical content and Instagram copy |
| `src/workflow/active_visual_profiles.py`, `visual_planner.py` | Curated account identities/archetypes and deterministic planning evidence |
| `src/workflow/storyboard_planner.py`, `render_text_policy.py` | Immutable text-aware render pagination, measurements and provisional capacity budgets |
| `src/workflow/gemini_prompt_compiler.py` | Deterministic storyboard prompt compilation |
| `src/workflow/active_review_renderer.py`, `gemini_image_renderer.py` | Atomic review assets, Gemini storyboards and shared local processing |
| `src/dashboard/` | Evidence, progress and review read models |
| `src/common/gemini.py`, `gemini_image.py` | Isolated single-attempt model transports |
| `config/releases/detection.json` | Active nonsecret source and algorithm policy |
| `tests/` | Offline behavior, safety, image fixtures and dashboard checks |

## Verification

```sh
.venv/bin/python scripts/run_tests.py
.venv/bin/python scripts/check_docs.py
```

These use fake providers and temporary databases; no paid inference or public
posting occurs. Browser tests run locally.
Tests protect the accepted English mechanics, not the aesthetic or factual
quality of every model response. Live editorial results require human review.
