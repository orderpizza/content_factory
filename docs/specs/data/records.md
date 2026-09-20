# SQLite Records

**Document role:** Tier 2 record inventory and initialization contract.
**Owner:** SQLite schema and initialization.

## Executable schema

[application-schema.sql](../../contracts/application-schema.sql) is the complete
current schema (user_version 6). `database.current.initialize_database` executes
it atomically for an empty database, records the exact SHA-256 in
`schema_migrations`, enables WAL and validates foreign keys.
The ledger contains one current schema row; it is not a migration chain.

Store open validates version/checksum and foreign keys. Dashboard refresh
validates version/checksum but avoids rescanning all foreign keys each time.
Initialization refuses an incompatible database without converting it.
`setup_development.py` additionally refuses any existing filename.

## Record groups

| Group | Tables |
| --- | --- |
| Configuration | schema_migrations, configuration_releases, configuration_activations, detection_source_instances |
| Collection | source_collection_attempts, source_request_executions, source_health, source_execution_evidence, source_item_events |
| Source facts | trends, trend_observations |
| Scout freeze | scout_evaluation_runs, scout_evaluation_inputs, scout_evaluation_attempts, scout_frozen_evidence, scout_prominence_populations, scout_event_resolutions |
| Shortlist | topic_snapshots, trend_candidates, candidate_observation_memberships |
| Conversation | content_threads, thread_messages, intake_requests, brief_revisions, human_command_receipts |
| Planning | pipeline_capabilities, output_bindings, determination_requests, determination_decisions, determination_routes, content_jobs, generation_runs |
| Production | canonical_contents, output_requests, adaptation_runs, content_packages, render_runs, render_assets, review_requests |
| Delivery configuration | social_destinations, production_configurations, posting_policies, capability_readiness, capability_readiness_checks |
| Publication | post_requests, post_records, post_attempts, publication_resources, delivery_cleanup_tasks |
| Reconciliation | reconciliation_requests, reconciliation_checks, human_reconciliation_decisions |
| Cost and operations | model_invocations, gemini_budget_reservations, worker_heartbeats, worker_runs, storage_samples, maintenance_runs, artifact_reconciliations |

Use the DDL for exact columns, enums, indexes and immutable-trigger definitions,
not inferred tables from roadmap prose. JSON validity at SQL level is supplemented
by worker/store semantic validation before finalization.

## Transaction and evidence policy

Original observations, frozen evaluation input/resolution, topic snapshots,
briefs, decision routes, job recipes, canonical content and packages are immutable.
Current status/claim fields and shortlist projections may change under their
owning transactions.

Determination input is immutable even before claim. All source membership and
catalog evidence needed by the decision is persisted, not fetched afresh.
A replay of a frozen Scout evaluation uses its stored resolution, not a new
embedding inference. Foreign keys and unique identity constraints protect
cross-stage lineage.

`storage_samples.summary_json.growth` holds the first daily bounded table scan:
row counts and UTF-8 byte sums per JSON column, completion flag and duration.
The sample columns separately record physical database/WAL/artifact/backup bytes.
Measurement reads a consistent snapshot, exports no field contents, and creates
no parallel schema. Existing samples without growth metadata remain valid.

No data-retention command removes these records as part of normal planning.
Verified backups and restore checks use the current schema checksum.
