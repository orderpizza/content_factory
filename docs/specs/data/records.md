# SQLite Record Contract

**Document role:** Tier 2 exact persistence contract for the current
detection-to-dashboard implementation milestone.
**Contract ID:** `detection_dashboard_schema_v1`.
**Owner:** SQLite schema, migrations, constraints, and persistence boundary
tests. Read the [Data Model](../data-model.md) first for identity, lineage, and
cross-record semantics.

The executable canonical DDL is
[`detection-dashboard-schema-v1.sql`](../../contracts/detection-dashboard-schema-v1.sql).
The application migration must execute those statements without maintaining a
second handwritten table definition. Its recorded migration checksum is the
SHA-256 of the UTF-8 SQL bytes. `PRAGMA user_version` must equal `1` after the
migration completes.

This contract deliberately contains only the records needed to collect,
evaluate, shortlist, and display trend opportunities. It remains immutable for
existing v1 databases. The optional local workflow scaffold is a separately
applied forward migration, [`editorial-workflow-schema-v2.sql`](../../contracts/editorial-workflow-schema-v2.sql);
it preserves every v1 handoff and is never applied by dashboard or worker
startup.

## Phase 1 extension boundary

The five-domain strategy's initial forward scaffold is v2. It creates the
persisted Intake, Determination, canonical-content, output-adaptation, render,
review, delivery, capability, and model-ledger boundaries used by the local
placeholder workers. It does not enable Gemini, account bindings, production
profiles, capacity/reuse policy, or provider delivery; those require the exact
reviewed contracts and operator configuration named in the Data Model.

The v2 human-idea command path supports both a new `ContentThread` and a
continuation of an open thread. A continuation appends one `thread_messages`
row and one pending `intake_requests` row atomically, rejects an active Intake
request, and uses the command receipt for retry idempotency. The Intake worker
freezes only the bounded conversation through that request's last-message
marker; later replies cannot leak into its revision.
Do not add future production fields to the applied detection migration or change
its checksum. Preserve current thread/Intake handoffs. Optional X threads require
a separate per-step publication schema and remain disabled until it is tested.

## Fixed conventions

- Every record identity is `INTEGER PRIMARY KEY AUTOINCREMENT`; audit IDs are
  never reused.
- Foreign keys are enabled on every connection. Required lineage uses `NOT
  NULL` and `ON DELETE RESTRICT`.
- Timestamps are UTC ISO-8601 `TEXT`. Code normalizes them before persistence;
  SQLite does not interpret local time.
- JSON is canonical UTF-8 JSON serialized with sorted object keys and compact
  separators. Every JSON column has `CHECK(json_valid(column))`.
- SHA-256 values are lowercase 64-character hexadecimal strings.
- Claimable rows carry the exact claim, attempt, retry, and error columns in
  the SQL contract. Network work never occurs while a write transaction is
  open.
- Dashboard reporting opens SQLite in read-only URI mode and performs neither
  migration nor repair.

## Current record groups

| Group | Records | Responsibility |
| --- | --- | --- |
| Migration and configuration | `schema_migrations`, `configuration_releases`, `configuration_activations` | Establish one validated active non-secret release and an auditable schema version. |
| Source registry and collection | `detection_source_instances`, `detection_cluster_aliases`, `source_collection_attempts`, `source_request_executions`, `source_health` | Freeze enabled source configuration, audit every reserved outbound execution (including retry quota), and record one bounded collection attempt plus its terminal health result. |
| Evidence | `trends`, `trend_observations`, `source_item_events` | Preserve canonical subjects, immutable observation snapshots, and explicit exclusions/rejections. |
| Evaluation | `scout_evaluation_runs`, `scout_evaluation_inputs`, `scout_evaluation_attempts`, `topic_snapshots`, `trend_candidates`, `candidate_observation_memberships` | Freeze source-level health plus every collection attempt used, append each score/evidence snapshot, and maintain one current candidate lifecycle per opportunity identity. |
| Selected handoff | `content_threads`, `intake_requests`, `thread_evidence_events` | Persist the terminal boundary of the current milestone without running Idea Intake. |
| Runtime visibility | `worker_heartbeats`, `worker_runs` | Show current worker freshness and substantive collection/evaluation executions. |

`topic_snapshots` is the immutable per-evaluation score/evidence record.
`trend_candidates` is the stable current lifecycle row keyed by
`opportunity_identity`; a new evaluation appends a snapshot, then updates the
candidate's `latest_topic_snapshot_id`, current score, evidence fingerprint,
and timestamps without erasing prior snapshots. Selection/consumption states
are not reset merely because another evaluation observes the same opportunity.
This division prevents both duplicate seed threads and loss of score history.

## Required transactions

### Migration

The explicit migration command must:

1. refuse an unknown nonzero `PRAGMA user_version`;
2. run the canonical SQL in one exclusive transaction against the displayed
   database path;
3. insert the migration version/name/checksum row; and
4. commit only after `PRAGMA foreign_key_check` returns no rows.

Application and dashboard startup must not call this command implicitly.

### Configuration activation

Applying a manifest validates it before opening the write transaction. The
transaction inserts one immutable release and its materialized source/alias
rows, supersedes the prior active `global` activation, creates the new active
activation, and commits. Reapplying the same release name and byte-equivalent
manifest returns the existing release; the same name with different bytes is
a conflict. A rejected manifest is retained only when the operator explicitly
requests validation audit; it is never activated.

A source stable ID is unique within a release, not globally. Reusing the same
stable ID in a later release represents the same logical source under a new
immutable configuration snapshot.

### Source collection

For one due source and schedule slot:

1. create or recover the unique `source_collection_attempts` row;
2. claim it conditionally, increment `claim_version`, and append one
   `source_request_executions` reservation before any outbound request;
3. atomically refuse the claim and record `quota_limited` when the source's
   UTC-day sum of reserved units would exceed its local ceiling;
4. perform the bounded provider operation outside SQLite;
5. in one fenced transaction, persist all valid observations and item events,
   persist exactly one `source_health` result, and complete or retry/fail the
   attempt; and
6. mark the request execution succeeded or failed and never call the provider
   again for a completed attempt.

Each safe retry recovers the same collection attempt but appends a distinct
request execution. The execution's reservation date, rather than the parent
attempt's schedule date, is the UTC-day quota boundary. A conservatively
reserved unit remains counted if the worker crashes before it can prove that
no request was sent.

Every valid observation resolves one `trends` row under the frozen
canonicalization version. The same provider item may create a new immutable
observation in a later collection attempt, but at most one in a single
attempt.

### Scout evaluation

For one 15-minute UTC slot and active release:

1. create or recover the unique `scout_evaluation_runs` row;
2. claim it and freeze exactly one `scout_evaluation_inputs` health/availability
   row for every enabled source instance plus one `scout_evaluation_attempts`
   row for every current or baseline collection attempt used by the score;
3. calculate all clusters, immutable `topic_snapshots`, and observation
   memberships outside the write transaction from that frozen input;
4. atomically append snapshots/memberships, insert or update the stable
   candidate rows, apply deterministic shortlist results, and complete the run;
   and
5. if selected, atomically create one trend `content_threads` row and one
   pending `intake_requests` row before setting the candidate to `selected`.

The unique opportunity identity and unique `content_threads.seed_candidate_id`
make restart/overlap idempotent. A candidate whose existing state is
`selected`, `consumed`, or `rejected_cooldown` is updated with its latest
evidence but does not silently become a new initial selection.

## State ownership

| Record | Legal lifecycle | Owner |
| --- | --- | --- |
| `source_collection_attempts` | `pending/retry_wait → claimed → running → completed/retry_wait/failed/cancelled` | Trend Source Collector |
| `source_request_executions` | `reserved → succeeded/failed`; append-only and never retried in place | Trend Source Collector |
| `scout_evaluation_runs` | `pending/retry_wait → claimed → running → completed/retry_wait/failed/cancelled` | Trend Scout + Shortlist |
| `trend_candidates` | `observed ↔ eligible`; `eligible → selected/deferred_by_budget`; `deferred_by_budget → observed/eligible/deferred_stale`; new current evidence may move `deferred_stale → observed/eligible`; `selected → consumed/rejected_cooldown`; `rejected_cooldown → reconsiderable`; `reconsiderable → selected/rejected_cooldown`; any pre-consumption state may enter `migration_hold` only during cutover | Trend Scout for observation/eligibility/selection; Determination later records consumption outcome |
| `content_threads` | `open → closed/cancelled`; `closed → open`; `cancelled` terminal | Idea Intake/dashboard in later stages; current Scout only creates `open` trend seeds |
| `intake_requests` | `pending/retry_wait → claimed → completed/needs_clarification/retry_wait/failed/cancelled` | Idea Intake; current Scout only creates `pending` |

The current dashboard is reporting-only, so it owns no write transition in this
milestone.

## Index and query contract

The SQL contract contains the write-side uniqueness and worker pickup indexes.
The first dashboard read model must use bounded, ordered queries for:

- candidates by status, descending score, and latest update;
- source instances with latest collection and health;
- observations by source/window and by trend/time;
- evaluation runs and their frozen inputs;
- candidate snapshots and evidence membership; and
- current worker heartbeat plus recent substantive runs.

Every list uses a deterministic ID tie-breaker and a caller-enforced maximum
page size of 100. Raw provider response bodies, credentials, signed URLs, and
unbounded JSON are never returned.

## Acceptance requirements

Boundary tests must prove that:

- a fresh database applies the canonical SQL once and records its checksum;
- startup against an absent, older, newer, or checksum-mismatched schema fails
  visibly without mutation;
- foreign keys and every closed status set reject invalid data;
- duplicate source schedules, evaluation slots, source items, opportunity
  identities, and selected seed threads are rejected or return the existing
  frozen result;
- a stale claim owner cannot finalize after a higher `claim_version` wins;
- a completed collection attempt is never refetched;
- a new evaluation preserves earlier topic snapshots and memberships; and
- the dashboard reporting connection cannot write, create, migrate, or repair
  a database.
