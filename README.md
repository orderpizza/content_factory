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

## Current Detection Phase

The detector currently runs independently of Gemini. Its Scout collects free
source signals, stores historical observations and snapshots in SQLite, ranks
explainable `TrendCandidate` records, and exposes a read-only live dashboard.

Current sources are Hacker News, configured RSS/Atom feeds, and Wikimedia
pageviews. The detector is still being tuned before the determination/LLM phase
begins. Important remaining work includes semantic clustering/classification,
source expansion, and careful scoring revision because these directly control
which candidates are consumed downstream.

The system is ultimately intended for monetized content, but monetization
evaluation belongs in determination. Detection measures attention and evidence;
it does not decide whether a topic is commercially useful.

## Development Order

1. Repository structure, configuration, and SQLite.
2. Deterministic Scout and detection history.
3. Detection clustering, classification, scoring, and observation.
4. TrendCandidate to determination.
5. ContentJob persistence.
6. One POC pipeline.
7. Visual renderer.
8. Posting queue.
9. Posting agent.
10. End-to-end autonomous test.
11. Observe failures and improve.

## Non-Goals For The Initial POC

Do not add multiple pipelines, generic plugin architecture, distributed queues,
cloud workers, cloud databases, Kubernetes, vector databases, AI image
generation for every asset, multi-platform publishing, or model routing unless
explicitly requested.
