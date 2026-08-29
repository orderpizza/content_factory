# Content Factory

Local-first automated content factory POC.

The purpose of this repository is to prove one continuous O2 English loop with
human approval before any public publication:

```text
Trend Detection
  -> Trend Candidate
  -> Trend Shortlist
  -> Determination
  -> ContentJob
  -> One Content Pipeline
  -> Content Package
  -> Visual Rendering
  -> Ready ContentPackage
  -> Human Review
  -> Posting Agent
  -> Publication Record
```

This is intentionally a proof of concept, not the final production system.
Keep implementation choices small, local, and easy to inspect.

## Current Target

The current target, implementation status, operating policy, and deferred work
live in [docs/system.md](docs/system.md). The immediate goal is one O2 English
Instagram end-to-end path; Content Factory will later support multiple
platform-specific pipelines.

## Source Of Truth

Read these before making architectural or boundary changes:

- [docs/system.md](docs/system.md) — primary Human–Agent Interface
- [docs/specs/](docs/specs/) — task-scoped data model, dashboard, and reliability specifications
- [docs/pipelines/o2-english-instagram.md](docs/pipelines/o2-english-instagram.md) — active pipeline contract
- [docs/platforms/meta.md](docs/platforms/meta.md) — Meta-specific account and API reference

Historical decisions are retained in
[docs/archive/decisions.md](docs/archive/decisions.md) for targeted lookups,
not routine review.

The active o2 English Instagram contract is documented in
[docs/pipelines/o2-english-instagram.md](docs/pipelines/o2-english-instagram.md).

## Non-Goals For The Initial POC

Do not add multiple pipelines, generic plugin architecture, distributed queues,
cloud workers, cloud databases, Kubernetes, vector databases, AI image
generation for every asset, multi-platform publishing, or model routing unless
explicitly requested.
