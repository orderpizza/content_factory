# Architecture

## Runtime

The Mac Mini is the primary runtime. It should run collection, detection,
determination orchestration, pipeline execution, rendering, and SQLite storage.

GCP is used primarily for Vertex AI Gemini API calls. Do not move the database,
workers, scheduling, rendering, or queueing to GCP during the POC unless that is
explicitly requested.

## Component Flow

```text
Trend Detector
  -> DeterminationRequest
  -> Determination Layer and Decision
  -> ContentJob (recipe)
  -> Pipeline Runner
  -> Selected Pipeline
  -> ContentPackage
  -> Visual Renderer
  -> Ready ContentPackage
  -> Post Queue
  -> Posting Agent
  -> PostRecord
```

The arrows represent persisted handoffs through SQLite, not direct calls
between module implementations. SQLite is the common communication and state
boundary for the POC. A module writes its output and status to the database;
the next module discovers eligible work by reading the database.

The detector remains independently observable and LLM-free. Its persisted
handoffs feed determination. The current end-to-end target is one o2 English
publication; the Posting Agent portion remains under design and implementation.

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

The detector creates a frozen `DeterminationRequest` containing the candidate,
source evidence, trend history, and producing detection-run ID. Repeated
selection of the same candidate does not create duplicate pending or claimed
requests; a later request requires resolution and cooldown expiry.

Topic clustering and classification are important unfinished areas. As source
coverage grows, differently worded observations about the same event may
otherwise appear as duplicate trends. The initial clustering is deterministic
and conservative; local semantic methods may be evaluated later without
moving clustering into the Gemini determination layer.

The Scout is intended to run periodically on the Mac Mini. Source failures are
retried and persisted as source-health records. The dashboard is read-only
observability and is not a workflow control surface.

Retention is handled by a separate maintenance process. After the configured
hot-data period, detailed detector records are compressed into
`data/archive/`; observation history is compacted into monthly topic/source
summaries in `trend_history` before hot rows are removed. Content and
publication records are not part of detector cleanup.

Recent raw detail remains queryable, older detail is compressed into local
archives, and monthly topic/source summaries remain in SQLite. Detection runs,
handoff records, content jobs, and publication history are retained for audit.

### System Dashboard

The dashboard is a system-level observability component covering the complete
responsibility chain. The current trend dashboard is its first view, named
`Trend Detection`.

Future views include Overview, Trend Detection, Determination, Content Jobs,
Production, Visual Assets, Posting, and System Health.

The dashboard reads module-owned state and reporting data from SQLite. It must
not call module services, reach into private implementation details, or move
business logic into the UI. It remains read-only during the POC; orchestration
and workflow decisions stay with their owning components.

### Determination Layer

Receives persisted `DeterminationRequest` records. Gemini is isolated behind a
small Vertex client and used here for interpretation and content opportunity
decisions. It receives a
small catalog of available pipeline capabilities so it can select the correct
pipeline, target platform/account, format, audience, angle, objective, and
high-level visual profile.

It either rejects the candidate or produces one explicit `ContentJob` recipe in
the POC. It must not call pipeline-specific Python functions directly. Future
determinations may create multiple jobs for one trend, but that is outside the
current POC scope.

### Pipeline Runner

Finds pending `ContentJob` records in SQLite and dispatches them by
`pipeline_id`. For the POC, this can be a simple polling loop.

Do not introduce distributed queues or worker infrastructure.

### `o2_english_instagram` Pipeline

Consumes a `ContentJob` and produces a platform-specific `ContentPackage`
containing the content, native metadata, and required asset or visual
specification.

The pipeline owns how content is created and is platform- and format-specific.
It creates the content, asset or visual specifications, caption, and metadata
such as tags and hashtags. Gemini may be used here for creative generation and
context-sensitive metadata; validation of syntax, length, duplicates, banned
terms, and platform limits remains deterministic. The pipeline does not need to
know how the trend was detected.

The first extracted `o2_english` format is
`instagram_idiom_carousel` with profile
`o2_english_idiom_carousel_v1`. It has a fixed 5–8-slide idiom teaching
contract, a 1080×1920 Instagram rendering target, and four registered slide
templates (hook, explanation, monologue use case, and dialogue use case).
The pipeline Gemini boundary creates structured slide copy, caption, tags, and
hashtags. It cannot replace invalid or unavailable Gemini metadata with a
deterministic fallback.

The determination-selected visual profile constrains the pipeline. Pipeline
Gemini may refine that profile only from the pipeline's registered allowed
profiles. It must not invent a template ID or renderer configuration.

### Visual Renderer

Consumes a visual specification from a `ContentPackage` and creates image assets
deterministically using HTML/CSS and Playwright. It persists the rendered asset
references on the package; a package becomes ready for future posting only after
all required assets have been rendered.

The visual system deterministically resolves the concrete template from the
pipeline/profile/format. It owns fonts, backgrounds, shapes, characters, and
other low-level renderer settings; Gemini does not select these directly.

Do not use AI image generation by default.

### Posting Agent (Under Development)

The Posting Agent will consume finished platform-specific content, apply
duplicate and scheduling rules, publish it, and record publication history. It
will not use an LLM, generate captions or tags, or modify captions, hashtags,
or visual selections.

It is a system-level shared service separate from content pipelines. Its queue
state, attempts, failures, and publication records belong in SQLite for the
read-only dashboard.

The platform adapter, public-media strategy, retry policy, and Instagram Graph
API flow remain unresolved. They must be designed as a posting-layer concern,
never added to the `o2_english` pipeline or visual renderer.

## Storage

Use SQLite for POC state. Initial tables should remain minimal:

- `trends`
- `trend_observations`
- `topic_snapshots`
- `trend_candidates`
- `detection_runs`
- `determination_handoffs`
- `determination_decisions`
- `source_health`
- `content_jobs`
- `content_packages`

Posting-specific persistence evolves with the Posting Agent implementation.

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
