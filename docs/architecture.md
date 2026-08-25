# Architecture

## System Model

Content Factory is a set of independently observable components that exchange
work through persisted SQLite handoffs:

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

The arrows are persisted handoffs, never direct calls between module
implementations. A writer stores its output and status; the next component
discovers eligible work by reading SQLite. See [poc.md](poc.md) for active
scope limits and operating simplifications.

## Components

### Trend Detector

Discovers topics gaining attention across independent signals. It normalizes
source observations, maintains history, calculates explainable deterministic
scores, and writes candidates plus their evidence. It never calls an LLM.

The detector creates a frozen `DeterminationRequest` containing candidate
metadata, evidence, history, and the producing detection-run ID. Candidate
lifecycle remains separate from handoff lifecycle: one candidate may continue
to accumulate evidence while a particular handoff is resolved or cooling down.

Source adapters implement a common observation contract. Source-health records
and failures are persisted so one unavailable source does not stop the rest of
the detector. Source selection, scoring thresholds, clustering maturity, and
retention policy are active POC concerns; see [poc.md](poc.md).

### Determination Layer

Consumes persisted `DeterminationRequest` records and decides whether to
consume a candidate. An accepted decision creates an explicit `ContentJob`
recipe selecting a registered pipeline, destination, format, audience, angle,
objective, source context, and high-level visual profile.

Gemini belongs here for interpretation and opportunity decisions. Determination
does not create content, select low-level renderer configuration, or invoke a
pipeline directly.

### Pipeline Runner

Discovers pending `ContentJob` records and dispatches each to the pipeline
identified by `pipeline_id`. It is a boundary between generic orchestration and
platform- and format-specific production.

### Content Pipeline

A pipeline consumes one `ContentJob` and creates a platform-specific
`ContentPackage`. It owns creative content, native metadata, and the required
asset or visual specification. Gemini may be used for creative generation and
context-sensitive metadata; deterministic validation enforces syntax,
uniqueness, policy, and platform constraints.

A pipeline may refine a high-level visual profile only from its registered
allowed profiles. It must not invent renderer configuration or change its
selected destination.

### Visual Renderer

Consumes a package visual specification and produces deterministic final
assets. It owns low-level layout, template resolution, fonts, backgrounds,
shapes, and other renderer settings. Rendering updates the persisted package;
the package becomes ready for posting only after all required assets exist.

The renderer does not generate creative metadata or use an LLM by default.

### Posting Agent

Consumes ready packages, applies destination-specific scheduling, duplicate,
and delivery rules, publishes through a platform adapter, and records
publication history. It is a shared system service separate from pipelines.

The Posting Agent never calls an LLM or generates or modifies captions, tags,
hashtags, visual choices, or asset order. Queue state, attempts, failures,
external delivery artifacts, and publication records are persisted for audit.

### System Dashboard

The dashboard is a system-level observability consumer. It reads
module-owned SQLite state and reporting data to present detection,
determination, production, rendering, posting, and health views. It does not
call module services, depend on private implementation details, or create or
mutate workflow state.

## Storage And Observability

SQLite is the shared persisted state boundary. The core records include trends,
observations, snapshots, candidates, detection runs, determination handoffs
and decisions, content jobs and packages, posting records, and `api_usage`.

`api_usage` is an append-only observability ledger for successful external LLM
calls. It records phase, owning entity, model, token counts, an optional cost
estimate, and completion time. It is not an orchestration queue or creative
state.

Each component persists explicit statuses at its boundary. The dashboard and
operators use those states to understand progress without reaching into another
component's private implementation.

## Pipeline Documentation

Each pipeline maintains its own contract, format specification, and delivery
detail:

- [o2 English Instagram](pipelines/o2-english-instagram.md) — implementation
  contract and delivery specification

Future pipeline documents should follow the same structure rather than adding
format rules to this system document.
