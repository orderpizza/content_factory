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

## Components

### Trend Detector

Discovers topics that appear to be gaining attention. The detector should prefer
relative growth, velocity, persistence, and source agreement over absolute
popularity alone.

The first implementation should use deterministic collection, normalization,
deduplication, and simple scoring. It should not require an LLM for every
observation.

### Determination Layer

Receives a `Trend` and decides whether content should be created. Gemini should
be isolated behind a small client/service and used here for reasoning.

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
- `content_jobs`
- `content_packages`
- `posts`

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
    database/
    common/
  tests/
  scripts/
  generated/
  data/
    content.db
```

Do not create folders for future pipelines until they are actually implemented.
