# Canonical Contract Registry

**Registry version:** `contract_registry_v5`

**Last architectural review:** 2026-09-13

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
| `specs/data/records.md` | Exact SQLite routing | approved_for_implementation (v1 detection; v2 editorial; v3 scoring safety; v4 production subset) | versioned SQL/configuration | no |
| `specs/configuration.md` | Configuration | design_approved (detection manifests and immutable v4 production materializer implemented) | domain/output registries, data/runtime/reliability | no |
| `specs/detection.md` | Detection | approved_for_implementation (current ingestion slice); editorial recurrence integration is design_approved | data/configuration/runtime, Intake | source facts reverify |
| `specs/idea-intake-and-determination.md` | Intake/routing/angles | design_approved | domain catalog, data, dashboard, reliability, new schemas | model facts reverify |
| `pipelines/domains.md` | Five domain intelligence contracts | design_approved | Intake, production, evidence/reference fixtures | factual claim inputs must be supported |
| `specs/content-production.md` | Canonical generation and adaptation | design_approved (bounded Gemini production/checkpoint/budget subset implemented) | domains, outputs, data, runtime, reliability | model facts reverify |
| `specs/platform-outputs.md` | Native static output composition | design_approved | production, new profiles, Meta/X verification | native limits reverify |
| `specs/visual-rendering.md` | Shared renderer | design_approved (local and pinned-font production subsets implemented) | profile/visual fixtures, data/reliability | tool/runtime facts reverify |
| `specs/dashboard.md` | HAI | design_approved (idea/review/Post now/cancel/reconciliation and operations summary implemented) | data, routing, production, runtime, posting | no |
| `specs/runtime.md` | Worker runtime | design_approved (polling/templates/basic heartbeats and initial leases implemented; renewal/capacity/unattended acceptance pending) | data, production, configuration, reliability | no |
| `specs/posting.md` | Posting Agent | approved_for_implementation for Instagram carousel/X single post; optional-thread extension draft | data, outputs, runtime, reliability, provider contracts | live reverify before first post |
| `specs/reliability.md` | Safety and budgets | design_approved (v4 budget/storage/backup/delivery-safety subset implemented) | data, production, runtime, configuration | provider facts reverify |
| `pipelines/o2-english-instagram.md` | Compatibility routing | superseded | domains, production, outputs | no |
| `platforms/meta.md` | Instagram delivery provider | draft reference; adapter offline-tested | posting, outputs, configuration | live account/app/API/R2 reverify |
| `platforms/x.md` | X delivery provider | draft reference; adapter offline-tested | posting, outputs, configuration | live account/access/API reverify |
| `contracts/detection-dashboard-schema-v1.sql` | Exact SQLite | approved_for_implementation | data/records, detection/configuration | no |
| `contracts/editorial-workflow-schema-v2.sql` | Forward SQLite workflow scaffold | approved_for_implementation (local fixtures plus opt-in Gemini review-preview path) | data/records, workflow/fake-Gemini/renderer boundary tests | no |
| `contracts/detection-safety-schema-v3.sql` | Forward immutable scoring evidence | approved_for_implementation (offline tested; explicit migration only) | data/records, hybrid detection tests | no |
| `contracts/production-workflow-schema-v4.sql` | Forward production workflow subset | approved_for_implementation (offline migration/boundary tested; explicit Option B migration only) | data/records, production workflow tests | live providers unverified |
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

The approved five-domain/multi-angle strategy does not itself authorize public
production. V4 implements a bounded, fail-closed production path over the v2
creative records: production configuration, budget admission, delivery-ready
rendering, one-destination authorization, provider attempts, cleanup,
reconciliation, and maintenance. It still requires explicit setup/configuration,
current readiness, credentials, and a human Post now command. Standalone JSON
contracts, reference-quality fixtures, reuse/recurrence, capacity admission,
mid-call lease renewal, complete supervision, X threads, and unattended/live-provider acceptance
remain open under their narrative owners.
Existing detection SQL/configuration IDs and applied checksums stay unchanged.

The [target plan](../plans/target-implementation.md) orders remaining work:
executable boundaries, editorial evidence, operator account/policy choices,
native Meta/X facts, new static profiles, and optional-thread per-step safety.
Proposed numerical defaults are implementation starting points requiring a
validated production release, not implied user authorization to spend or post.
