# Current implementation and operations

## System state

The current schema is **17**, defined by
[application-schema.sql](contracts/application-schema.sql).
Use a fresh development database with a new filename. Incompatible databases are
refused by version/checksum validation; setup refuses any existing path.
The inactive production configuration contract is `production_configuration_v2`;
[configuration](specs/configuration.md#preserved-production-configuration) owns
its visual-approval semantics. No existing database is upgraded automatically. Schema 17 separates canonical
claim references and structured Adaptation lines from earlier contracts. Existing
schema-16 databases remain intact and must be opened by their matching code;
this release requires fresh setup, with no incidental migration.
All persisted timestamps are UTC-naive ISO-8601 seconds (`YYYY-MM-DDTHH:MM:SS`).

Automatic Detection and human ideas both feed three-domain Determination:
`english`, `ai_tech`, `psychology`. Each selected domain creates an EditorialPlanRun; a validated immutable
EditorialPlan creates a ContentJob and
one Instagram output. Detection uses configured public sources, local MiniLM
and deterministic scoring. Human Intake can clarify before freezing a brief.

`--gemini --planning-only` stops at pending GenerationRuns. Without review-preview,
the workflow runs planning only; default workers are deterministic fixtures.
`--gemini --review-preview` enables canonical generation, deterministic visual planning,
archetype-aware Instagram adaptation and Gemini review rendering. English supports
deterministically planned 4–6-slide review carousels; AI/Tech and Psychology produce 4–14 slides. All domains
use persisted text-aware render pagination independently of content pagination,
with sequential Gemini
board calls with explicit supported provider ratios, equal-grid splitting (or the
accepted adaptive split for a six-panel English board) and
proportional center-fit normalization into uniformly 4:5, 1080×1350 PNGs. Each account/domain has three curated archetypes; the accepted English, AI/Tech
and Psychology explainers remain safe baselines. Canonical semantics and bounded
recent-use penalties choose the immutable recipe before adaptation. One deterministic
prompt compiler guides the shared image renderer. See the
[archetype catalog and contracts](specs/visual-rendering.md).
Unsupported domain/archetype combinations block explicitly; invalid package
shapes fail before the image call. No HTML fallback is active. Explicit human slide/domain constraints are extracted
locally, Editorial Planning IDs/scoring/qualification attachment are deterministic,
and Adaptation selects required teaching claims into explicit body-line arrays.
Only explicit retryable text-provider responses can retry within durable attempt
limits; contract failures stop without repeated paid calls. Text transport uses a
finite configurable 180-second deadline (maximum 300 seconds) and 600-second
fenced claims. `gemini-3.7-flash` on Vertex `global` with API `v1` is the current
GA text recommendation; operator pricing remains required. Startup and invocation
traces report the effective model, endpoint, deadline, retry attempt and runtime
prompt/schema fingerprint. See [configuration](specs/configuration.md) and
[reliability](specs/reliability.md).

The dashboard exposes Raw Feed Items, Clusters, committed Opportunities, ideas,
Determination routes, editorial plans and failures, jobs, adaptation/storyboard/render progress and exact review slides.
Accept/reject/request-changes commands do not publish. Generic posting/delivery
records and R2 staging are preserved inactive; provider delivery is not
implemented in the current baseline. The former deterministic visual library is
reference-only under `archive/deterministic_visual_library/`; it is not runnable
or reachable from the workflow.

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

## Optional live acceptance and regression

The permanent live acceptance/regression framework is opt-in, isolates each run
from production development databases, and is never part of normal CI. Its
definitions live in [`acceptance/`](../acceptance/README.md); runtime databases,
results, raw boards and review slides live in ignored `data/acceptance/`.
[`docs/acceptance/`](acceptance/README.md) owns its architecture, golden-scenario
and invariant philosophy, current conclusions and historical reports.

These commands are for owner-run paid acceptance only, after configuring local
Gemini credentials and budgets. Use a fresh database filename (setup refuses an
existing path), so the workflow cannot consume unrelated pending work:

```sh
.venv/bin/python scripts/setup_development.py
.venv/bin/python scripts/create_local_idea.py "English only: teach break the ice in a first meeting, using six slides: hook, meaning, use cases, examples, short dialogue, takeaway."
.venv/bin/python scripts/create_local_idea.py "AI/Tech only: explain a hypothetical AI workflow for drafting a neutral opening question for a meeting. No current product or availability claims. A human must review tone and accuracy."
.venv/bin/python scripts/create_local_idea.py "Psychology only: explain hesitation in an unfamiliar group as an observation. Social uncertainty is one possible explanation; people may simply need time. Offer an optional low-stakes question, without diagnosis or asserted motives."
.venv/bin/python scripts/run_workflow.py --artifacts data/artifacts/acceptance-review --gemini --review-preview --poll
```

In another terminal:

```sh
.venv/bin/python scripts/serve_dashboard.py --artifacts data/artifacts/acceptance-review
```

Open http://127.0.0.1:8787, answer any Intake clarification and inspect the
Determination selections. Manually compare the English baseline, AI/Tech clarity
and visible caveats, and Psychology qualification across each ordered review.
These are human-review acceptance cases, not assertions of live model quality.
Stop the workflow with Ctrl+C when finished. This flow does not publish.

## Opt-in Gemini acceptance harness

The framework supports isolated stage, chain and full-journey runs, dry-run
planning, production-ledger evidence and machine-readable results. It can carry
selected Human and frozen Detection journeys through StoryboardPlan, production
prompt compilation, Gemini image boards, split/overlay processing and a final
ReviewRequest. It preserves raw boards and final slides in the isolated run,
plus a local static gallery; visual quality remains a human-review decision.
Dry-run does not require live opt-in. Real calls require both
`CONTENT_FACTORY_ENABLE_LIVE_GEMINI_TESTS=1` and `--live-gemini`, plus an
explicit finite acceptance USD ceiling; normal CI never invokes the text or
image clients.

The permanent `visual` acceptance profile covers board/review mechanics. The
`fidelity` profile compares the same frozen six-slide English package under
6, 4+2, 2+2+2 and six singleton calls. Text budgets are provisional; these forced
experiments record policy violations for calibration. No paid fidelity experiment
has been run for this implementation. See [runner operation](../acceptance/README.md)
for dry-run and explicitly opt-in live commands. The [historical visual acceptance
report](acceptance/history/pass3/visual-acceptance.md) remains unchanged evidence.
Gemini-rendered text still requires human review; posting remains disabled.

The former Psychology hardening and spot-check matrices are retained as
historical Pass 2 evidence rather than active acceptance profiles. They do not
define the current or future Psychology policy; see the [history retention
policy](acceptance/history/README.md).

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
| `archive/deterministic_visual_library/` | Reference-only former generic visual library; never imported or run |
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
