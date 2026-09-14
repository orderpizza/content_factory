# Machine-checkable contracts

This directory contains executable boundary contracts. JSON documents use
JSON Schema Draft 2020-12; SQL documents are canonical migration inputs routed
by the SQLite record contract. Production producers must validate JSON before
persistence and consumers must validate again before use. Schema v4 adds exact
SQL persistence constraints; current Gemini payloads use closed in-code JSON
schemas plus semantic validation rather than standalone JSON Schema files.
Contract IDs and
applied SQL checksums are immutable: a breaking change creates a new
ID/version or forward migration rather than editing a deployed contract.

Production contracts must reject credentials, authorization headers, signed URLs,
raw provider responses and unbounded opaque fields. SQL JSON validity checks
alone cannot enforce that policy; a shared semantic/redaction boundary is still needed.

| Artifact | Narrative owner | Scope |
| --- | --- | --- |
| `detection-dashboard-schema-v1.sql` | `docs/specs/data/records.md` | Exact first-milestone SQLite schema. |
| `editorial-workflow-schema-v2.sql` | `docs/specs/data/records.md` | Explicit v1→v2 local workflow scaffold; default fixtures plus opt-in Gemini Intake/Determination/generation/adaptation and local review rendering with in-code validation. |
| `detection-safety-schema-v3.sql` | `docs/specs/data/records.md` | Explicit v2→v3 immutable scoring/partial-response evidence; preserves editorial handoffs. |
| `production-workflow-schema-v4.sql` | `docs/specs/data/records.md` | Explicit v3→v4 real destinations, budgets, checkpoints, delivery, reconciliation, storage, and maintenance records. |
| `semantic-events-schema-v5.sql` | `docs/specs/data/records.md` | Immutable per-evaluation semantic partition, source hash and model/pair evidence. |
| `configuration-manifest-v4.schema.json` | `docs/specs/configuration.md` | Lexical normalization, bounded local semantic resolver policy, recency-neutral `attention_v3`, and durable `shortlist_v2`. |
| `brief-v1`, `determination-result-v1`, `recipe-v1`, `o2-creative-v1`, `visual-spec-v1` schemas | Their retained historical owner | Superseded, unimplemented drafts; do not use for Phase 1 production. |
| Remaining `*.schema.json` files | Their `x-owner` field | Draft later-stage boundaries; check Phase 1 conformance before adoption. |

## Phase 1 schema transition

The [registry](maturity.md) is authoritative for maturity. The five-domain design
requires route-neutral brief/rework, multi-route/angle, canonical job/content,
domain-extension, output-request/adaptation/package, and compatible static
visual contracts. The v2 SQL establishes the durable editorial path, and its
opt-in runner exercises Gemini for the route-neutral Intake and
five-route Determination boundaries, per-domain canonical generation, and
Instagram/X adaptation using closed in-code response schemas and offline fakes.
The local renderer creates real review assets. The v4 SQL then implements the
bounded production subset: immutable real destinations/profiles, priced budget
reservations, adaptation checkpoints, exact Post now authorization, Instagram/X
single-post delivery audit, cleanup/reconciliation, and local maintenance.
It is opt-in and live providers remain unverified. Reference-quality evaluation,
reuse/recurrence, capacity allocation, X threads, and unattended acceptance
remain outside the implemented contract.

Preserve IDs/checksums of deployed detection/configuration contracts. The
superseded JSON drafts remain for traceability and carry explicit maturity
metadata. Their presence or successful JSON parsing does not establish current
implementation readiness. Do not generate new production models from them.
