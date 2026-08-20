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
  -> Ready ContentPackage
  -> Post Queue
  -> Posting Agent
  -> Publication Record
```

This is intentionally a proof of concept, not the final production system.
Keep implementation choices small, local, and easy to inspect.

## Current Target

The current target, implementation status, acceptance criteria, and deferred
work live in [docs/current.md](docs/current.md). The immediate goal is one o2
English Instagram end-to-end path; Content Factory will later support multiple
platform-specific pipelines, including Bluesky.

## Source Of Truth

Read these before making architectural or boundary changes:

- [docs/current.md](docs/current.md) — current target and status
- [docs/system-flow.md](docs/system-flow.md) — detailed system flow, handoffs, AI boundaries, and lifecycle states
- [docs/poc.md](docs/poc.md)
- [docs/architecture.md](docs/architecture.md)
- [docs/interfaces.md](docs/interfaces.md)
- [docs/decisions.md](docs/decisions.md)
- [docs/roadmap.md](docs/roadmap.md)
- [docs/runbooks/](docs/runbooks/) — local operating procedures

The controlled o2 Instagram integration path is documented in
[docs/runbooks/local-runtime.md](docs/runbooks/local-runtime.md).

## Non-Goals For The Initial POC

Do not add multiple pipelines, generic plugin architecture, distributed queues,
cloud workers, cloud databases, Kubernetes, vector databases, AI image
generation for every asset, multi-platform publishing, or model routing unless
explicitly requested.
