# Current implementation and operations

The [architecture](architecture.md) describes the current review-only pipeline.
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
