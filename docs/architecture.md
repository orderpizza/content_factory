# Architecture

## Runtime

The Mac Mini is the primary runtime. It should run collection, detection,
determination orchestration, pipeline execution, rendering, scheduling, posting,
and SQLite storage.

GCP is used primarily for Vertex AI Gemini API calls. Do not move the database,
workers, scheduling, rendering, or queueing to GCP during the POC unless that is
explicitly requested.

## Component Flow

```text
Trend Detector
  -> Determination Layer
  -> ContentJob
  -> Pipeline Runner
  -> POC Pipeline
  -> ContentPackage
  -> Visual Renderer
  -> Post Queue
  -> Posting Agent
  -> PostRecord
```

During the current development phase, the system intentionally stops after
the detection output. The Scout runs independently and writes ranked
`TrendCandidate` records to SQLite. Determination will consume those records
later; it is not part of the current detector validation loop.

```text
Scheduled Scout
  -> Source observations
  -> Normalization and clustering
  -> Historical snapshots
  -> Deterministic scoring
  -> TrendCandidates
  -> SQLite and read-only dashboard
```

## Components

### Trend Detector

Discovers topics that appear to be gaining attention across independent
signals. The detector is deterministic and must not consume LLM tokens.

Enabled sources are Hacker News, configured RSS/Atom feeds, and Wikimedia
pageviews. Reddit and YouTube adapters are implemented but remain disabled
until credentials/access are configured. Google Trends and other platform
sources remain roadmap items. The complete source roadmap is maintained in
`docs/poc.md`.

New sources should implement the common source contract and convert their data
into observations. A source being listed in the roadmap does not make it part
of the active Scout configuration.

The detector stores raw observations, topic snapshots, source health, and
ranked candidates in SQLite. It uses historical baselines, velocity,
acceleration, persistence, unusual activity, and source agreement. Every
candidate should retain an explainable score breakdown and evidence sources.

After scoring, the detector applies a downstream selection boundary. All scored
candidates remain persisted for dashboard visibility and later tuning, but only
fresh candidates meeting `CONTENT_FACTORY_MINIMUM_TREND_SCORE` and fitting
`CONTENT_FACTORY_TOP_N_CANDIDATES` are marked `pending_determination`.
Determination consumes that shortlist rather than every scored topic.

Topic clustering and classification are important unfinished areas. As source
coverage grows, differently worded observations about the same event may
otherwise appear as duplicate trends. The initial clustering is deterministic
and conservative; local semantic methods may be evaluated later without
moving clustering into the Gemini determination layer.

The Scout is intended to run periodically on the Mac Mini. Source failures are
retried and persisted as source-health records. The dashboard is read-only
observability and is not a workflow control surface.

### System Dashboard

The dashboard is a system-level observability component covering the complete
responsibility chain. The current trend dashboard is its first view, named
`Trend Detection`.

Future views include Overview, Trend Detection, Determination, Content Jobs,
Production, Visual Assets, Posting, and System Health.

The dashboard consumes module-owned reporting/read models. It must not reach
into private module implementation details or move business logic into the UI.
It remains read-only during the POC; orchestration and workflow decisions stay
with their owning components.

### Determination Layer

Receives eligible `TrendCandidate` records after the detector has been observed
and tuned. Gemini should be isolated behind a small client/service and used here
for interpretation and content opportunity decisions.

Determination produces a `ContentJob`. It must not call pipeline-specific Python
functions directly.

### Pipeline Runner

Finds pending `ContentJob` records in SQLite and dispatches them by
`pipeline_id`. For the POC, this can be a simple polling loop.

Do not introduce distributed queues or worker infrastructure.

### POC Pipeline

Consumes a `ContentJob` and produces a `ContentPackage`.

The pipeline owns how content is created. It does not need to know how the trend
was detected.

### Visual Renderer

Consumes a visual specification from a `ContentPackage` and creates image assets
deterministically using HTML/CSS and Playwright.

Do not use AI image generation by default.

### Posting Agent

Consumes finished content, applies duplicate and scheduling rules, publishes or
schedules the content, and records publication history.

The posting agent is separate from the content pipeline.

## Storage

Use SQLite for POC state. Initial tables should remain minimal:

- `trends`
- `trend_observations`
- `topic_snapshots`
- `trend_candidates`
- `source_health`
- `content_jobs`
- `content_packages`
- `posts`

Trend candidates have lifecycle/status fields and cooldown state so a topic can
continue updating without being repeatedly sent downstream.

Add tables only when needed to complete the POC loop.

## Suggested Repository Shape

```text
content_factory/
  AGENTS.md
  README.md
  .env.example
  .gitignore
  docs/
    vision.md
    poc.md
    architecture.md
    interfaces.md
    decisions.md
  src/
    intelligence/
    determination/
    pipelines/
      poc/
    visual/
    posting/
    dashboard/
    database/
    common/
  tests/
  scripts/
  generated/
  data/
    content.db
```

Do not create folders for future pipelines until they are actually implemented.
