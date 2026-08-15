# Content Factory

Local-first automated content factory POC.

The purpose of this repository is to prove one complete autonomous loop:

```text
Trend Detection
  -> Trend Candidate
  -> Determination
  -> ContentJob
  -> One Content Pipeline
  -> Content Package
  -> Visual Rendering
  -> Post Queue
  -> Posting Agent
  -> Published Content
  -> Publication Record
```

This is intentionally a proof of concept, not the final production system.
Keep implementation choices small, local, and easy to inspect.

## Current POC Scope

- One trend detector.
- One determination layer.
- One predefined content pipeline.
- One deterministic visual template.
- One posting platform.
- SQLite for state.
- Mac Mini as the primary runtime.
- Gemini API for LLM reasoning and generation where useful.

## Source Of Truth

Read these before making architectural or boundary changes:

- [docs/vision.md](docs/vision.md)
- [docs/poc.md](docs/poc.md)
- [docs/architecture.md](docs/architecture.md)
- [docs/interfaces.md](docs/interfaces.md)
- [docs/decisions.md](docs/decisions.md)

## Development Order

1. Repository structure, configuration, and SQLite.
2. Trend collector/detector.
3. Trend to determination.
4. ContentJob persistence.
5. One POC pipeline.
6. Visual renderer.
7. Posting queue.
8. Posting agent.
9. End-to-end autonomous test.
10. Observe failures and improve.

## Non-Goals For The Initial POC

Do not add multiple pipelines, generic plugin architecture, distributed queues,
cloud workers, cloud databases, Kubernetes, vector databases, AI image
generation for every asset, multi-platform publishing, or model routing unless
explicitly requested.
