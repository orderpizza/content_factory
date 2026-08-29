# Content Factory

Local-first automated content factory POC. The Mac Mini is the target runtime,
SQLite is the persisted system boundary, and the current objective is one O2
English Instagram loop with human approval before public publication.

## Start here

Read [the system guide](docs/system.md) before changing architecture or code.
It is the Tier 1 Human–Agent Interface: the current target flow, responsibility
boundaries, and router to every focused contract.

## Documentation layout

- `docs/system.md` — Tier 1 architectural map and required-reading matrix.
- `docs/specs/` — Tier 2 component and cross-cutting contracts.
- `docs/pipelines/` — platform-format pipeline contracts.
- `docs/platforms/` — time-sensitive provider account/API facts.
- `docs/archive/` — historical rationale for targeted lookup only.

The active pipeline contract is
[O2 English Instagram](docs/pipelines/o2-english-instagram.md). Follow the
required-reading matrix in the system guide; do not infer architecture from
legacy code or this README.

## Non-Goals For The Initial POC

Do not add multiple pipelines, generic plugin architecture, distributed queues,
cloud workers, cloud databases, Kubernetes, vector databases, AI image
generation for every asset, multi-platform publishing, or model routing unless
explicitly requested.
