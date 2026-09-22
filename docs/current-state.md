# Current implementation and operations

## System state

The current schema is **9**, defined by
[application-schema.sql](contracts/application-schema.sql). The schema adds the
explicit blocked visual-planning/render states and restricts platform bindings to Instagram.
Use a fresh development database with a new filename. Existing databases are
refused by version/checksum validation; setup never resets or migrates them.
All persisted timestamps are UTC-naive ISO-8601 seconds (`YYYY-MM-DDTHH:MM:SS`).

Automatic Detection and human ideas both feed three-domain Determination:
`english`, `ai_tech`, `psychology`. Each selected domain creates a ContentJob and
one Instagram output. Detection uses configured public sources, local MiniLM
and deterministic scoring. Human Intake can clarify before freezing a brief.

`--gemini --planning-only` stops at pending GenerationRuns. Without review-preview,
the workflow runs planning only; default workers are deterministic fixtures.
`--gemini --review-preview` enables canonical generation, Instagram adaptation,
visual planning and Gemini review rendering. English expression breakdowns
produce six 1080×1350 PNG review slides. AI/Tech and Psychology stop at rendering preparation
with VisualPlanRun `blocked` and “Gemini visual renderer not implemented for this domain.”
Other English formats are also blocked explicitly. No HTML fallback is active.

The dashboard exposes Raw Feed Items, Clusters, committed Opportunities, ideas,
Determination routes, jobs, adaptation/render progress and exact review slides.
Accept/reject/request-changes commands do not publish. Generic posting/delivery
records and R2 staging are preserved outside this pass; provider delivery is not
implemented in the current baseline. The deterministic visual library, local
assets and HTML gallery renderer are preserved inactive.

## Fresh setup

Use the existing `.venv`. On a fresh machine install Python 3.10+ and uv, then:

```sh
uv sync --frozen --extra dev
.venv/bin/python -m playwright install chromium
```

Chromium supports browser tests and inactive visual-library tooling. Copy
`.env.example` to ignored `.env` if needed and configure values locally; process
environment overrides the file. See [configuration](specs/configuration.md).
Create a new database (choose another filename if this one exists):

```sh
.venv/bin/python scripts/setup_development.py --database data/baseline.db
```

Setup registers all three domains with one synthetic Instagram binding each and
an initial storage sample; it makes no provider call. `--download-model` explicitly
provisions the pinned public MiniLM files if uncached. Set
`CONTENT_FACTORY_DB_PATH=data/baseline.db` so every process uses the same database.

## Planning and review sessions

Check local prerequisites without network calls:

```sh
.venv/bin/python scripts/check_smoke_readiness.py --database data/baseline.db --mode planning
```

Run each process in a separate terminal:

```sh
.venv/bin/python scripts/run_detection.py --database data/baseline.db --poll
.venv/bin/python scripts/run_workflow.py --database data/baseline.db --gemini --planning-only --poll
.venv/bin/python scripts/serve_dashboard.py --database data/baseline.db
```

Open http://127.0.0.1:8787. Submit ideas or answer clarification in the same thread.
Inspect frozen evidence, all three routes and jobs. To generate review content,
replace the planning workflow process with:

```sh
.venv/bin/python scripts/run_workflow.py --database data/baseline.db --gemini --review-preview --poll
```

This makes paid Gemini calls under configured budgets. It can consume pending
jobs. Review rendering uses one 5:4, 2K storyboard call for the supported English
format, adaptive splitting and transparent overlays. Original PNG/JPEG bytes are
retained for debugging; only the six processed PNGs are review assets. Failures
do not trigger automatic paid retries. See [visual rendering](specs/visual-rendering.md).

Detection polls due work every 30 seconds; workflow polls every five seconds.
`--poll-interval` changes the delay, and Ctrl+C stops cleanly. A healthy collection
need not select an Opportunity. A single-source history needs seven healthy
completed baseline days; before then selection requires two independent groups
within one lexical cluster. Semantic links do not pool scoring credit.
Human ideation is immediately available for every domain.

```sh
.venv/bin/python scripts/create_local_idea.py "teach break the ice in business meetings" --database data/baseline.db
.venv/bin/python scripts/create_local_idea.py "focus on intermediate learners" --thread-id 1 --row-version 2 --database data/baseline.db
```

Use the actual thread ID and version. Refinement creates immutable new work.

## Monitoring and maintenance

Planning ignores storage admission, including missing/stale/critical samples;
actual SQLite/OS errors still fail. Generation/adaptation/render gates remain
separate. The workflow refreshes advisory samples; an independent model-free
monitor is also available:

```sh
.venv/bin/python scripts/run_storage_monitor.py --database data/baseline.db --poll
```

The dashboard shows daily row/JSON growth and component sizes. Measurement never
deletes data. [Reliability](specs/reliability.md#storage-backup-and-retention)
owns backup/retention and [runtime](specs/runtime.md#diagnostic-logging) owns safe
rotating diagnostics. The dashboard refreshes every ten seconds, preserving drafts.

## Project map

| Path | Responsibility |
| --- | --- |
| `src/database/current.py` | Explicit initialization and schema validation |
| `src/detection/` | Public collection, normalization, semantic resolution, scoring and Scout |
| `src/workflow/store.py` | Transactions, claims, immutable handoffs and commands |
| `src/workflow/catalog.py` | Three editorial remits and catalog read model |
| `src/workflow/gemini_intake.py`, `gemini_determination.py` | Planning workers |
| `src/workflow/gemini_generation.py`, `gemini_adaptation.py` | Canonical content and Instagram copy |
| `src/workflow/gemini_image_renderer.py` | English storyboard, local processing and explicit rendering boundary |
| `src/workflow/visual_registry.py`, `visual_planner.py` | Frozen semantic recipes and preserved visual registry |
| `src/workflow/static_renderer.py`, `visual_primitives.py` | Preserved inactive HTML visual library |
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
posting occurs. Browser tests and inactive gallery rendering run locally.
Tests protect the accepted English mechanics, not the aesthetic or factual
quality of every model response. Live editorial results require human review.
