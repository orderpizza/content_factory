# Data Model

**Document role:** Tier 2 current persisted-boundary contract.
**Owner:** Identity, atomic handoffs and immutable evidence.

## Identity boundaries

Detection opportunity identity is separate from editorial coverage, domain
content identity and output identity. Lexical `canonicalization_v2` only handles
string equivalence. Local semantic resolution freezes an event partition for
each Scout run; it never mutates observations or completed evaluations.
`attention_v3` scores the strongest eligible lexical member, not pooled inferred
corroboration.

Human coverage identity uses `coverage_normalization_v2`: trimmed/casefolded
kind and whitespace-collapsed casefolded target. It is unique per thread and
does not include pipeline/platform/account. ContentJob identity derives from
the immutable revision/domain/angle recipe. Output identity additionally binds
canonical content to one destination/format.

## Record inventory and transition rules

### Detection

`configuration_releases`, activations and `detection_source_instances` freeze
source policy. Attempts, request executions, source health and item evidence
audit collection and quotas. `trends` and `trend_observations` retain normalized
source facts. `scout_evaluation_runs` claim each time slot; frozen inputs,
attempt memberships, evidence and prominence populations make replay stable.
`scout_event_resolutions` holds one immutable semantic partition per run,
including source/model/policy hashes and pair evidence.

`topic_snapshots` preserve scoring and source evidence.
`trend_candidates` is the implementation record for a Cluster's Detection
lifecycle. It is not a separate user-facing concept. Its projection is mutable;
memberships are immutable per snapshot. A selected Cluster becomes an Opportunity
only with the committed trend thread, initial system brief and Determination
request. There is no separate Opportunity table. Later topic snapshots do not
rewrite the selected brief. [Detection](detection.md#status-ownership) owns status
semantics; the dashboard follows persisted IDs, never inferred title matches.

### Planning

`content_threads` owns conversation and coverage. `thread_messages` is ordered
append-only history. `intake_requests` freeze their message boundary.
`brief_revisions` are numbered immutable children; source snapshots preserve
original Detection evidence during human refinement.

`pipeline_capabilities` and `output_bindings` define available routes.
`social_destinations` and production configuration/readiness apply only to real
delivery catalogs; fixture bindings have no deliverable destination.

`determination_requests` freeze brief, evidence and catalog.
`determination_decisions` records aggregate editorial value;
`determination_routes` records exactly five selected/skipped/blocked assessments.
`content_jobs` and `generation_runs` are created only for selected routes.
The decision, routes and jobs commit atomically.

### Production and operations

`canonical_contents` is immutable platform-neutral output.
`output_requests` freezes destination plans; `adaptation_runs` owns bounded
adaptation and metadata checkpoints. `content_packages` contains exact copy,
units and semantic visual intent. `visual_plan_runs` claim deterministic planning
and `visual_recipes` preserve the selected registry release, fingerprint and
bounded selection provenance. `render_runs` and assets preserve actual local files;
`review_requests` references exact packages and assets.

`post_requests`, `post_records`, `post_attempts` and publication resources
separate human authorization from delivery. `reconciliation_requests` and
checks preserve uncertain outcomes without an automatic repost.
`model_invocations` and budget reservations preserve paid-call admission,
usage, cost and uncertainty. Storage samples, worker heartbeats/runs, maintenance
and artifact reconciliation provide operational evidence.

### Column, foreign-key, and retention catalog

The only executable DDL is
[application-schema.sql](../contracts/application-schema.sql).
[SQLite records](data/records.md) maps table groups and initialization.
Foreign keys restrict deletion of referenced evidence. This development setup
does not migrate old schemas or auto-delete existing databases.

### Claimable-record transition matrix

| Boundary | Main states |
| --- | --- |
| Collection/Scout | pending → claimed → completed; bounded retry/failure |
| Intake | pending → claimed → completed / needs_clarification / failed / cancelled |
| Determination | pending → claimed → completed / retry_wait / failed / cancelled |
| Generation/adaptation/visual planning/render | pending → claimed → succeeded / retry_wait / failed / cancelled |
| Review | awaiting_review → approved / changes_requested / rejected / invalidated |
| Delivery | pending → claimed → publishing → published / failed / publication_unknown |
| Reconciliation | pending → claimed → needs_human → resolved |

Claim owner, version and unexpired lease fence finalization. Reclaimed local
work cannot be completed by a stale owner. Closed/cancelled threads fence
downstream finalizers. Model invocation history prevents blind paid retries.

## Immutable finalization

Intake commits its brief and Determination request in one transaction.
Determination commits all routes/jobs/runs in one transaction. A SQL trigger
protects request input, revision and fingerprint after creation. Catalog changes
require a new request, not mutation at claim time.

Schema version 7 and its checksum identify the current database contract.
Initialization is explicit and idempotent only for the exact current schema;
incompatible databases are refused unchanged.
