# Machine-checkable contracts

This directory contains executable boundary contracts. JSON documents use
JSON Schema Draft 2020-12; SQL documents are canonical migration inputs routed
by the SQLite record contract. A producer validates JSON before it persists a
`*_json` field and a consumer validates again before use. Contract IDs and
applied SQL checksums are immutable: a breaking change creates a new
ID/version or forward migration rather than editing a deployed contract.

No schema permits credentials, authorization headers, signed URLs, raw
provider responses, or arbitrary unbounded opaque fields.

| Artifact | Narrative owner | Scope |
| --- | --- | --- |
| `detection-dashboard-schema-v1.sql` | `docs/specs/data/records.md` | Exact first-milestone SQLite schema. |
| `configuration-manifest-v1.schema.json` | `docs/specs/configuration.md` | Non-secret release manifest. |
| `brief-v1`, `determination-result-v1`, `recipe-v1`, `o2-creative-v1`, `visual-spec-v1` schemas | Their retained historical owner | Superseded, unimplemented drafts; do not use for Phase 1 production. |
| Remaining `*.schema.json` files | Their `x-owner` field | Draft later-stage boundaries; check Phase 1 conformance before adoption. |

## Phase 1 schema transition

The [registry](maturity.md) is authoritative for maturity. The five-domain design
requires new route-neutral brief/rework, multi-route/angle, canonical job/content,
domain-extension, output-request/adaptation/package, and compatible static
visual contracts. These versions must be authored with their fixtures and
forward SQL before enabling downstream workers; they are not silently provided
by the old single-route drafts.

Preserve IDs/checksums of deployed detection/configuration contracts. The
superseded JSON drafts remain for traceability and carry explicit maturity
metadata. Their presence or successful JSON parsing does not establish current
implementation readiness. Do not generate new production models from them.
