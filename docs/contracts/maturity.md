# Canonical Contract Registry

**Registry version:** `contract_registry_v3`

**Last architectural review:** 2026-09-09

**Normative terms:** `must` is mandatory; `should` needs a recorded exception;
`may` is permitted discretion.

Maturity applies to the stated scope, not a claim that code exists:

- `approved_for_implementation`: exact current-slice contract is ready for its
  stated boundary.
- `design_approved`: Phase 1 architecture is accepted; executable schemas,
  configuration choices, implementation fixtures, and provider gates may remain.
- `draft`: not an enabled implementation contract; complete its listed gates.
- `superseded`: retained for lineage/old links, not new implementation.
- `legacy_reference`: immutable old version useful as reference, not assumed
  compatible with current platform output.

| Contract | Owner | Maturity | Dependencies | Provider facts |
| --- | --- | --- | --- | --- |
| `system.md` | Architecture/router | design_approved | all routed contracts | no |
| `specs/data-model.md` | Persistence semantics | design_approved | every persisted stage, future forward SQL | no |
| `specs/data/records.md` | Exact SQLite routing | approved_for_implementation (v1 detection; v2 local scaffold; optional v3 scoring safety) | versioned SQL/configuration | no |
| `specs/configuration.md` | Configuration | design_approved (v1 historical and v2 hybrid detection manifests implemented) | domain/output registries, data/runtime/reliability | no |
| `specs/detection.md` | Detection | approved_for_implementation (current ingestion slice); editorial recurrence integration is design_approved | data/configuration/runtime, Intake | source facts reverify |
| `specs/idea-intake-and-determination.md` | Intake/routing/angles | design_approved | domain catalog, data, dashboard, reliability, new schemas | model facts reverify |
| `pipelines/domains.md` | Five domain intelligence contracts | design_approved | Intake, production, evidence/reference fixtures | factual claim inputs must be supported |
| `specs/content-production.md` | Canonical generation and adaptation | design_approved | domains, outputs, data, runtime, reliability; new schemas | model facts reverify |
| `specs/platform-outputs.md` | Native static output composition | design_approved | production, new profiles, Meta/X verification | native limits reverify |
| `specs/visual-rendering.md` | Shared renderer | design_approved | new profile/visual schemas and fixtures, data/reliability | tool/runtime facts reverify |
| `specs/dashboard.md` | HAI | design_approved (detection/thread-first read model implemented; production commands pending) | data, routing, production, runtime, posting | no |
| `specs/runtime.md` | Worker runtime | design_approved | data, production, configuration, reliability | no |
| `specs/posting.md` | Posting Agent | design_approved; optional-thread state extension draft | data, outputs, runtime, reliability, provider contracts | reverify before enablement |
| `specs/reliability.md` | Safety and budgets | design_approved | data, production, runtime, configuration | provider facts reverify |
| `pipelines/o2-english-instagram.md` | Compatibility routing | superseded | domains, production, outputs | no |
| `platforms/meta.md` | Instagram delivery provider | draft | posting, outputs, configuration | reverify pinned API/endpoint fixtures |
| `platforms/x.md` | X delivery provider | draft | posting, outputs, configuration | not yet verified for configured access |
| `contracts/detection-dashboard-schema-v1.sql` | Exact SQLite | approved_for_implementation | data/records, detection/configuration | no |
| `contracts/editorial-workflow-schema-v2.sql` | Forward SQLite workflow scaffold | approved_for_implementation (local placeholder workers only) | data/records, workflow boundary tests | no |
| `contracts/detection-safety-schema-v3.sql` | Forward immutable scoring evidence | approved_for_implementation (offline tested; explicit migration only) | data/records, hybrid detection tests | no |
| `contracts/configuration-manifest-v1.schema.json` | Detection configuration | approved_for_implementation (detection only) | configuration | no |
| `contracts/configuration-manifest-v2.schema.json` | Hybrid detection configuration | approved_for_implementation (user-approved live/daily policy) | configuration, safety schema v3 | source facts reverify |
| `contracts/configuration-manifest-v3.schema.json` | Corrected normalization configuration | approved_for_implementation (separate development DB only; no implicit identity conversion) | configuration, normalized boundary tests, safety schema v3 | no provider change |
| `contracts/brief-v1.schema.json` | Former Intake payload | superseded draft | needs route-neutral coverage/rework scope version | no |
| `contracts/determination-result-v1.schema.json` | Former single-route payload | superseded draft | needs multi-route/angle result version | no |
| `contracts/recipe-v1.schema.json` | Former platform-bound job | superseded draft | needs domain job and separate output-request versions | no |
| `contracts/o2-creative-v1.schema.json` | Former slide-coupled English payload | superseded draft | needs canonical English extension and separate output schema | no |
| `contracts/visual-spec-v1.schema.json` | Former fixed static visual payload | superseded draft | needs compatible versioned Phase 1 profiles/bindings | no |
| Other `contracts/*.schema.json` | Named narrative owner | draft | validate against Phase 1 owner before reuse | no |
| `profiles/editorial-clean-v1.md` | Renderer legacy profile | legacy_reference | new Phase 1 profile versions/goldens required | pinned runtime reverify |

## Readiness gates

This registry describes design maturity, not observed implementation conformance.
[Current state](../current-state.md) and the [audit](../../audit_report.md) record
which code runs and known defects; approved contract labels do not waive those defects.

The approved five-domain/multi-angle strategy does not authorize execution of
draft production payloads. New brief/routing/recipe/canonical/domain-extension/
output/visual schemas, forward migrations, fixture sets, and configuration
manifests must be completed under their narrative owners before activation.
Existing detection SQL/configuration IDs and applied checksums stay unchanged.

The [target plan](../plans/target-implementation.md) orders remaining work:
executable boundaries, editorial evidence, operator account/policy choices,
native Meta/X facts, new static profiles, and optional-thread per-step safety.
Proposed numerical defaults are implementation starting points requiring a
validated production release, not implied user authorization to spend or post.
