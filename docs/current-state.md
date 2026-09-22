# Current implementation and operations

## System state

The application uses one current SQLite schema, version **8**, defined in
[application-schema.sql](contracts/application-schema.sql). Setup creates a
fresh database. Existing exact-v7 databases use the deliberate
`scripts/migrate_database.py --database <path>` timestamp upgrade; it preserves
records and instants, without a reset. Version and SQL checksum are checked on
store open. SQLite WAL, foreign keys, claim versions and immutable evidence
protect worker boundaries. Content Factory timestamps are UTC-naive
second-precision ISO strings (`YYYY-MM-DDTHH:MM:SS`).

Implemented planning paths:

- **Detection:** Hacker News, NASA RSS and Wikimedia daily collection;
  deterministic lexical canonicalization; pinned local MiniLM semantic event
  resolution; immutable Scout input and resolution; attention scoring and
  shortlist; direct source-backed brief and Determination request.
- **Human ideation:** dashboard/CLI ideas and replies; persisted conversation;
  Gemini Intake clarification or immutable brief. Refining a trend thread keeps
  its original Detection evidence.
- **Determination:** Gemini assesses all five domains; validates reasons,
  angles and ready frozen output bindings; commits five routes and a ContentJob
  plus pending GenerationRun for each selected domain.
- **Visual planning:** each platform ContentPackage carries bounded semantic
  `visual_intent`; a deterministic shared registry planner selects a coherent
  archetype/preset and approved safe variants, then commits one immutable
  VisualRecipe before a renderer claim. The source-controlled registry supplies
  reusable families, compositions, themes, typography, components and
  decorations as authoring primitives. Curated first-wave vocabulary, bold-cover,
  comparison, phrase-sheet, question-sheet, serif, dialogue, scenario and step
  archetypes use real per-unit layouts. `expression_breakdown_v1` is a tested,
  Instagram-only shared capability with a fixed six-slide English-expression
  grammar; it remains non-production until visual review. Its gallery uses
  deterministic avatar placeholders until local approved PNGs are installed at
  `assets/visual/avatars/`; production would require those assets and records
  their hashes. Experimental archetypes are preview-only.
  `scripts/render_visual_gallery.py` renders offline development samples under
  `data/artifacts/visual-gallery`. Instagram and X plan independently.
- **Dashboard:** four linked views: Raw Feed Items → Clusters → Opportunities
  → ContentJobs, with separate collection-attempt, source-health and Cluster
  Selection statuses. Semantic evidence, Scout runs, worker history, queues,
  conversation, briefs, frozen catalogs, route reasoning and model usage remain
  inspectable. Opportunities require an actual Determination handoff, not a score alone.

The deterministic default workers are fixtures, not editorial intelligence.
`--gemini --planning-only` is the intended live planning trial. It does not run
generation, adaptation, rendering or posting. Synthetic Instagram/X bindings
allow routing evaluation without delivery credentials.

Downstream Gemini generation/adaptation, Gemini sequential designer review rendering,
static Playwright rendering, review,
credentialed Instagram/X single-post adapters, R2 staging/cleanup, reconciliation,
budgets and maintenance exist. They require separate explicit preview/production/
delivery modes and are not activated by planning setup.

## Fresh setup

For an existing configured `.venv`, skip dependency installation. Fresh-machine
prerequisites are Python 3.10+ and uv (installed separately). From the repository
root, install the locked
dependencies; Chromium is needed for browser tests and real rendering:

```sh
uv sync --frozen --extra dev
.venv/bin/python -m playwright install chromium
```

These installation commands download dependencies. They do not call Gemini or
publish content. Copy the tracked `.env.example` to ignored `.env` if needed,
fill it locally, and follow [configuration](specs/configuration.md) for settings.

Create a new database on the Mac Mini:

```sh
.venv/bin/python scripts/setup_development.py --database data/development.db
```

This creates schema, active nonsecret Detection configuration, five development
capabilities with two synthetic platforms each, and an initial storage sample.
It refuses any existing filename and performs no collection or paid inference.
For an uncached model add `--download-model`; this downloads only the pinned
public model files, not application data. Local inference thereafter is offline.

YouTube is disabled unless setup uses `--include-youtube`; leave it disabled
while its API key is on hold. X delivery is also on hold; the synthetic X
routing binding does not call X.

`.env.example` lists supported settings. Keep actual values in ignored `.env`
or the process environment. Process values take precedence; restart each
process after editing settings. Set `CONTENT_FACTORY_DB_PATH=data/development.db`
so all processes use the same database. Explicit `--database` takes precedence.

## Planning session

First inspect local prerequisites without making a network call:

```sh
.venv/bin/python scripts/check_smoke_readiness.py --database data/development.db --mode planning
```

Then run each command in a separate terminal:

```sh
.venv/bin/python scripts/run_detection.py --database data/development.db --poll
.venv/bin/python scripts/run_workflow.py --database data/development.db --gemini --planning-only --poll
.venv/bin/python scripts/serve_dashboard.py --database data/development.db
```

Open http://127.0.0.1:8787. Submit an idea, inspect Intake status, answer any
question in the same thread, then inspect its brief, all five route assessments
and ContentJobs. `pending` GenerationRuns are the expected stopping point.

Detection checks due collection and Scout slots every 30 seconds. Workflow
checks Intake then Determination every 5 seconds; both intervals are adjustable
with `--poll-interval`. Ctrl+C stops cleanly. Without `--poll`, each runs once.
The embedding model is reused by a running Detection poller.

The Detection command makes public source reads. The Gemini workflow makes
paid calls under configured admission limits. No social credentials are needed.
A healthy collection need not produce a selected trend: selection gates are
deliberately conservative. Inspect observed/deferred clusters and score
evidence before changing thresholds.
Single-source history readiness needs seven healthy completed baseline days;
before that, selection requires two independent contributing groups within one
lexical scoring cluster. Semantic links do not satisfy that requirement by
pooling groups. A fresh database may therefore show observations without any
automatic ContentJobs during warm-up. Human ideation can be tested immediately.

CLI input is also supported:

```sh
.venv/bin/python scripts/create_local_idea.py "teach break the ice in business meetings" --database data/development.db
.venv/bin/python scripts/create_local_idea.py "focus on intermediate learners" --thread-id 1 --row-version 2 --database data/development.db
```

Use the actual thread ID and current row version shown by the dashboard.
Human refinement creates a new revision; it never rewrites prior work.

## Advisory storage monitoring, growth and diagnostics

Planning does not consult storage admission: dashboard/CLI ideas and refinements,
Intake, Detection, Determination and ContentJob creation work with missing, stale,
clock-invalid, warning, critical or emergency samples. Actual SQLite/OS write
failures still fail. The UI distinguishes unavailable measurements from measured
disk pressure. Downstream generation/delivery safety rules remain separate.
To refresh observability without starting Gemini or consuming jobs:

```sh
.venv/bin/python scripts/run_storage_monitor.py --database data/development.db --poll
```

Use the exact database shown by your dashboard; different paths do not share
storage samples. The workflow poller already samples storage, so the extra
process is optional. Refreshing measurements requires no schema reset.

The dashboard shows daily table/JSON growth and component sizes. Measurement
does not delete data. [Reliability](specs/reliability.md#storage-backup-and-retention)
owns sampling and downstream admission; [the roadmap](plans/target-implementation.md#storage-measurement-and-retention)
owns retention design and measurement review.

Safe JSON diagnostic logs rotate under `data/logs`; see [runtime](specs/runtime.md#diagnostic-logging)
for limits and [configuration](specs/configuration.md) for overrides. The dashboard
updates in place every ten seconds without erasing drafts or collapsing evidence.

## Project map

| Path | Responsibility |
| --- | --- |
| `src/database/current.py` | Explicit initialization and current schema validation |
| `src/detection/` | Source adapters, collection, normalization, semantic resolution, scoring, Scout |
| `src/workflow/store.py` | Transactions, claims, immutable handoffs, commands and production state |
| `src/workflow/catalog.py` | Shared catalog read model and domain remit |
| `src/workflow/gemini_intake.py`, `gemini_determination.py` | Real planning workers |
| `src/workflow/visual_registry.py`, `visual_planner.py` | Version-controlled visual capabilities and deterministic recipe selection |
| `src/workflow/development.py` | Fresh non-deliverable development setup |
| `src/dashboard/` | Detection, evidence, thread/decision and review read models |
| `scripts/serve_dashboard.py` | Loopback HTTP, CSRF commands and verified assets |
| `src/common/gemini.py`, `gemini_image.py` | Isolated Vertex JSON and single-attempt image transports |
| `src/workflow/gemini_image_renderer.py`, `static_renderer.py` | Explicit renderer dispatch, sequential designer rendering, deterministic overlays and local HTML rendering |
| `src/workflow/model_budget.py` | Priced phase/daily/job admission |
| `src/workflow/maintenance.py` | Storage sampling and verified SQLite maintenance |
| `scripts/run_storage_monitor.py`, `src/workflow/storage_growth.py` | Model-free storage freshness and daily size-only measurement |
| `src/common/operation_log.py` | Allowlisted, rotating process diagnostics |
| `config/releases/detection.json` | Nonsecret source and algorithm policy |
| `tests/` | Offline boundaries, full planning flows and production safety |

## Production setup and operation

Planning is intentionally separate from preview and delivery. To inspect real
generated assets, use `run_workflow.py --gemini --review-preview --poll`.
The default `--renderer auto` generates six individual 4:5 slides sequentially
for supported Instagram review carousels, initially `expression_breakdown_v1`.
Slide 1 anchors the visual style; later calls receive slide 1 and, from slide 3,
the previous raw slide as bounded style context. Each slide is normalized to
1080×1350 before deterministic branding overlays. Configure the separate
image model prices in [configuration](specs/configuration.md). `--renderer html`
keeps the existing deterministic renderer available. Other archetypes and
production retain HTML rendering; X is unchanged. Image generation and processing
failures do not auto-retry. No live call is part of routine verification.
Without `--planning-only`, workers may consume pending jobs.

For real destinations, configure explicit account/profile settings with
`scripts/configure_production.py`, run
`scripts/run_maintenance.py --restore-verify`, and use
`check_smoke_readiness.py --mode production` before a production trial.
Consult `--help` and [configuration](specs/configuration.md) for exact inputs.
Use a separate freshly configured database for a different catalog intent;
requests keep their creation-time catalog.

`--production` requires `--gemini --review-preview`, priced budgets and a backup
root. `--delivery` additionally composes credentialed adapters.
Only an exact dashboard **Post now** command authorizes public delivery.
Do not enable delivery for this planning trial.

## Verification and remaining limits

Run local verification without provider calls:

```sh
.venv/bin/python scripts/run_tests.py
.venv/bin/python scripts/check_docs.py
```

Coverage includes both planning paths, advisory storage conditions, frozen
Detection replay, job creation, budget/publication safety, and desktop/mobile
dashboard behavior. Browser tests check preserved drafts and incremental refresh.

`scripts/run_tests.py` uses fakes for Gemini, sources and social providers;
local HTTP and Playwright rendering are exercised. `scripts/check_docs.py`
checks current references, schema inventory and documented configuration.
Neither establishes live account access or editorial quality.

Live planning and editorial acceptance require a separate authorized trial.
Local preflight checks cached files/configuration, not ADC authorization or
provider availability. Semantic resolution is conservative but heuristic and
can miss equivalences; it does not pool cross-cluster scoring credit.

There is no automatic failed-model replay; a deliberate human reply can create
a new Intake revision in an open thread. Generation validates structure and
reference membership, not factual truth. Production is not ready merely because
fixtures pass. [The roadmap](plans/target-implementation.md) owns all remaining
capabilities and acceptance work.
