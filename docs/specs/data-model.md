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

## Timestamp contract

Every Content Factory-owned timestamp column and generated timestamp value uses
UTC-naive ISO-8601 second precision: `YYYY-MM-DDTHH:MM:SS`. The semantic
timezone is UTC. Writers use `common.timestamps.serialize_timestamp`; readers
use `parse_timestamp`, which treats persisted naive values as UTC for arithmetic.
External offset-bearing timestamps are converted to their UTC instant before the
timezone and fractional seconds are removed. IANA timezone names remain posting
policy configuration, not a timestamp storage format.

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

`pipeline_capabilities` and `output_bindings` define available routes. Bindings
carry destination/format readiness and the preserved production
`visual_configuration_approved` gate; the
[configuration contract](configuration.md#preserved-production-configuration)
owns its approval semantics. Renderer identity belongs to VisualRecipe; exact board geometry belongs to StoryboardPlan.
`social_destinations` and configuration/readiness records belong to the preserved
inactive delivery catalog; fixture bindings have no deliverable destination.

`determination_requests` freeze brief, evidence and catalog.
`determination_decisions` records aggregate editorial value;
`determination_routes` records exactly three selected/skipped/blocked assessments.
Selected routes atomically create `editorial_plan_runs`, freezing brief lineage,
source evidence and the latest 12 same-domain plans. `editorial_plans` freezes a
validated strategy. Plan, `content_jobs` and `generation_runs` commit atomically.
A unique non-null ContentJob editorial_plan_id and SQL lineage guards prevent
bypass or duplicate handoffs. Planning inputs and completed plans are immutable.

### Production and operations

`canonical_contents` is immutable platform-neutral output.
`output_requests` freezes destination plans. `visual_plan_runs` references an
output before any adaptation, and `visual_recipes` freezes its account identity,
curated archetype and complete deterministic selection provenance.
`adaptation_runs` references that recipe and owns bounded copy/metadata checkpoints.
`content_packages` preserves the same recipe ID, exact copy, units and semantic
claim-referenced visual cues. Package finalization creates StoryboardPlanRun. Its fenced finalization creates an
immutable StoryboardPlan and RenderRun atomically.
SQL guards enforce matching output → recipe → adaptation → package → storyboard plan → render
lineage and prevent changes to frozen visual inputs. The
[visual rendering contract](visual-rendering.md) owns recipe fields and selection.
`storyboard_plan_runs` uniquely references the package. `storyboard_plans` is
immutable and uniquely binds run/package/output, recipe, versions, total and board
JSON (`storyboard_plan_v2`). Each board explicitly freezes provider aspect ratio,
final slide aspect ratio and dimensions, and split/normalization strategy;
[visual rendering](visual-rendering.md) owns their closed mapping.
`render_runs.storyboard_plan_id` is required and unique; SQL guards prevent
lineage substitution. `model_invocations.claim_version` fences sequential boards
within one render claim.
`render_runs` and assets preserve actual local files;
`review_requests` references exact packages and assets.

`post_requests`, `post_records`, `post_attempts` and publication resources
separate human authorization from delivery. `reconciliation_requests` and
checks preserve uncertain outcomes without an automatic repost.
`model_invocations` and budget reservations preserve paid-call admission,
usage, cost and uncertainty. Storage samples, worker heartbeats/runs, maintenance
and artifact reconciliation provide operational evidence.

## Schema and record inventory

[`application-schema.sql`](../contracts/application-schema.sql) is the
authoritative schema, at version 14. All workers open and validate databases through
`database.current`: foreign keys are enabled, and the schema version and ledger
checksum must match the tracked contract. Initialization creates a fresh database
in WAL mode or validates an already-current database; it never resets or migrates
an incompatible database. Development setup requires a new filename.

Operator-managed primary databases use the filename
`db_YYYYMMDDHHMMSS.db`. The 14-digit suffix is the UTC timestamp, at
second precision, when the database is created. Setup generates this name; the
same primary path is shared by system processes and a filename is never reused.
This convention applies to development and review/runtime databases; isolated
test and acceptance databases remain in their harness-owned temporary or per-run
workspaces.

`scripts/setup_development.py` creates the next primary database using the
current UTC second and prints its path. System entrypoints select the root
`data/db_*.db` file with the greatest valid timestamp in its name. They never
create a database implicitly. A process that is already running keeps its
selected database; restart it after creating a newer database to switch over.

### Record groups

| Group | Tables |
| --- | --- |
| Configuration | schema_migrations, configuration_releases, configuration_activations, detection_source_instances |
| Collection | source_collection_attempts, source_request_executions, source_health, source_execution_evidence, source_item_events |
| Source facts | trends, trend_observations |
| Scout freeze | scout_evaluation_runs, scout_evaluation_inputs, scout_evaluation_attempts, scout_frozen_evidence, scout_prominence_populations, scout_event_resolutions |
| Shortlist | topic_snapshots, trend_candidates, candidate_observation_memberships |
| Conversation | content_threads, thread_messages, intake_requests, brief_revisions, human_command_receipts |
| Planning | pipeline_capabilities, output_bindings, determination_requests, determination_decisions, determination_routes, editorial_plan_runs, editorial_plans, content_jobs, generation_runs |
| Production | canonical_contents, output_requests, adaptation_runs, content_packages, visual_plan_runs, visual_recipes, storyboard_plan_runs, storyboard_plans, render_runs, render_assets, review_requests |
| Delivery configuration | social_destinations, production_configurations, posting_policies, capability_readiness, capability_readiness_checks |
| Publication | post_requests, post_records, post_attempts, publication_resources, delivery_cleanup_tasks |
| Reconciliation | reconciliation_requests, reconciliation_checks, human_reconciliation_decisions |
| Cost and operations | model_invocations, gemini_budget_reservations, worker_heartbeats, worker_runs, storage_samples, maintenance_runs, artifact_reconciliations |

Use the DDL for exact columns, enums, indexes and immutable-trigger definitions,
not a second field catalog. JSON validity at SQL level is supplemented
by worker/store semantic validation before finalization.


### Claimable-record transition matrix

| Boundary | Main states |
| --- | --- |
| Collection/Scout | pending → claimed → completed; bounded retry/failure |
| Intake | pending → claimed → completed / needs_clarification / failed / cancelled |
| Determination | pending → claimed → completed / retry_wait / failed / cancelled |
| Editorial planning | pending → claimed → succeeded / retry_wait / failed / cancelled |
| Generation/adaptation | pending → claimed → succeeded / retry_wait / failed / cancelled |
| Visual/storyboard planning/render | pending → claimed → succeeded / blocked / retry_wait / failed / cancelled |
| Review | awaiting_review → approved / changes_requested / rejected / invalidated |
| Delivery | pending → claimed → publishing → published / failed / publication_unknown |
| Reconciliation | pending → claimed → needs_human → resolved |

Claim owner, version and unexpired lease fence finalization. Reclaimed local
work cannot be completed by a stale owner. Closed/cancelled threads fence
downstream finalizers. Model invocation history prevents blind paid retries.

## Immutable finalization

Intake commits its brief and Determination request in one transaction.
Determination commits all routes/planning runs in one transaction. Editorial
Planning commits its plan/job/generation run in a separate fenced transaction. A SQL trigger
protects request input, revision and fingerprint after creation. Catalog changes
require a new request, not mutation at claim time.
Fresh setup never upgrades an existing database.

## Storage measurement evidence

`storage_samples.summary_json.growth` holds the first daily bounded table scan:
row counts and UTF-8 byte sums per JSON column, completion flag and duration.
The sample columns separately record physical database/WAL/artifact/backup bytes.
Measurement reads a consistent snapshot, exports no field contents, and creates
no parallel schema. Existing samples without growth metadata remain valid.

No data-retention command removes these records as part of normal planning.
Verified backups and restore checks use the current schema checksum.
