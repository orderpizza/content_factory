# SQLite Record Contract

**Document role:** Tier 2 exact persistence router for detection v1, editorial
workflow v2, detection safety v3, production v4, and semantic event resolution v5.
**Contract IDs:** `detection_dashboard_schema_v1`, `editorial_workflow_schema_v2`,
`detection_safety_schema_v3`, `production_workflow_schema_v4`, `semantic_events_schema_v5`.
**Owner:** SQLite schema, migrations, constraints, and persistence boundary
tests. Read the [Data Model](../data-model.md) first for identity, lineage, and
cross-record semantics.

The executable canonical DDL is
[`detection-dashboard-schema-v1.sql`](../../contracts/detection-dashboard-schema-v1.sql).
The application migration must execute those statements without maintaining a
second handwritten table definition. Each recorded migration checksum is the
SHA-256 of the UTF-8 SQL bytes. `PRAGMA user_version` advances from `1` through
explicit v2, v3, v4, and v5 migrations. Every applied SQL file/checksum remains
immutable.

Checkout execution reads the canonical SQL in `docs/contracts`. Distribution
builds copy those exact bytes into `content_factory_resources/contracts`; an
installed wheel loads that resource when no checkout contract exists. There is
one editable DDL source, not a separate handwritten package schema. The installed
wheel regression applies all five schemas with the active manifest outside the
checkout and compares every packaged SQL checksum.

This contract deliberately contains only the records needed to collect,
evaluate, shortlist, and display trend opportunities. It remains immutable for
existing v1 databases. The optional local workflow scaffold is a separately
applied forward migration, [`editorial-workflow-schema-v2.sql`](../../contracts/editorial-workflow-schema-v2.sql);
it preserves every v1 handoff and is never applied by dashboard or worker
startup. The optional [v3 safety migration](../../contracts/detection-safety-schema-v3.sql)
then sets `user_version=3` without replacing either earlier migration or handoff.

The explicit [v4 production migration](../../contracts/production-workflow-schema-v4.sql)
requires an active Option B release (`canonicalization_v2` + the current
normalized attention formula). It
refuses a legacy normalization release without writing, then advances the same
database to `user_version=4`.

### Semantic resolution persistence

[`semantic-events-schema-v5.sql`](../../contracts/semantic-events-schema-v5.sql)
adds `scout_event_resolutions`: a unique Scout-run FK, source snapshot hash,
canonical resolution JSON and hash, and creation timestamp. The JSON contains
the exact lexical observation membership, resolved partition, model/policy and
pair outcomes/signals. Both update and delete are forbidden. Local inference
finishes before the fenced write transaction; scoring requires the committed
record and does not invoke the encoder on replay. Setup requires schema v4 and
refuses unfinished frozen evaluations inside the exclusive migration transaction.
Applied SQL checksums and frozen records remain intact. The applied v1 SQL's
alias table is audit storage only, with no active reader, writer or configuration
path; `scout_event_resolutions` is the sole current event-resolution model.

### V3 evidence extension

`scout_frozen_evidence` stores one canonical, hashed source/health/report-day
snapshot per evaluation. `source_execution_evidence` retains bounded normalized
items and rejection diagnostics for each received response, including incomplete
responses that must not contribute scoring observations. Raw response bodies are
not stored. `scout_prominence_populations` stores each complete ranked population
once per run/source kind; candidate breakdowns reference its run, kind, hash and
size rather than copying the entire population into every candidate.
All three tables reject updates, as do `trend_observations` after v3. Workers
never rewrite prior contribution flags; they resolve contributors from frozen
evaluation inputs. This extension is activated only by an explicit migration.

### V4 production extension

V4 preserves earlier creative rows and adds the bounded real-operation subset:

- immutable production configuration, destinations, posting policies, and
  materialized domain/destination bindings;
- expiring readiness state plus append-only readiness checks;
- priced Gemini reservations, adaptation body/metadata checkpoints, and
  production render/profile/manifest fields;
- exact PostRequest/destination/manifest binding, attempts, safe remote
  resources, cleanup, and human-directed reconciliation; and
- storage samples, maintenance audit, and artifact reconciliation records.

SQL constraints and immutability triggers protect the most safety-critical
states. Store methods additionally validate full structured payloads, hashes,
row versions, readiness, storage, policy, and legal transitions. V4 does not add
X thread steps, canonical reuse, recurrence, recovery-work requests, worker
heartbeat enforcement, or a capacity allocator.

## Phase 1 extension boundary

The five-domain strategy's initial editorial scaffold is v2. It creates the
persisted Intake, Determination, canonical-content, output-adaptation, render,
review, delivery, capability, and model-ledger boundaries used by the local
placeholder workers. The opt-in runner also uses these same Intake,
Determination and model-ledger rows for bounded Gemini decisioning with in-code
response validation. V4 extends rather than replaces those rows for real account
bindings, production profiles, model-budget admission, provider delivery, and
maintenance. Capacity/reuse/recurrence remain outside this extension.

The v2 human-idea command path supports both a new `ContentThread` and a
continuation of an open thread. A continuation appends one `thread_messages`
row and one pending `intake_requests` row atomically, rejects an active Intake
request, and uses the command receipt for retry idempotency. The Intake worker
freezes conversation through that request's last-message marker; later replies
are excluded. Each human message is bounded; the canonical serialized conversation
is limited to 32,000 characters without truncation. Oversize input becomes a
visible `input_too_large` failure. Continuations require the displayed positive
thread row version, with receipt lookup and version checks under one write lock.
See [current implementation](../../current-state.md).

V2 by itself is not the production Data Model inventory: its JSON fields have
syntactic validation rather than standalone production schemas and its
capabilities may be local fixtures. V4 supplies the additional fail-closed
production records; closed in-code model schemas and semantic validators remain
part of the worker boundary.
Local claims now recover expired no-model work within attempt limits, fence stale
finalizers by owner/version/lease, and cancel downstream finalization when the
parent thread is closed. Claims with model history or delivery risk fail closed
for explicit recovery review. Synthetic approval cannot create PostRequests;
production review/delivery revalidates persisted and physical assets. Required
future fields/states need forward migrations,
not in-place changes to the scaffold SQL. The table groups and transition
requirements below describe the v1 slice unless explicitly marked otherwise.
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
| Source registry and collection | `detection_source_instances`, `source_collection_attempts`, `source_request_executions`, `source_health` | Freeze enabled source configuration, audit every reserved outbound execution (including retry quota), and record one bounded collection attempt plus its terminal health result. |
| Semantic resolution | `scout_event_resolutions` | Immutable lexical-to-resolved partition and model/pair evidence bound to one frozen Scout source snapshot. |
| Evidence | `trends`, `trend_observations`, `source_item_events` | Preserve canonical subjects, immutable observation snapshots, and explicit exclusions/rejections. |
| Evaluation | `scout_evaluation_runs`, `scout_evaluation_inputs`, `scout_evaluation_attempts`, `topic_snapshots`, `trend_candidates`, `candidate_observation_memberships` | Freeze source-level health plus every collection attempt used, append each score/evidence snapshot, and maintain one current candidate lifecycle per opportunity identity. |
| Selected handoff | `content_threads`, `intake_requests`, `thread_evidence_events` | Persist trend/human handoff and route-neutral Intake conversation. |
| Runtime visibility | `worker_heartbeats`, `worker_runs` | Show current worker freshness and substantive collection/evaluation executions. |
| Editorial workflow | v2 brief, determination, route, job, generation, canonical, output, adaptation, package, render, review, post, capability, receipt, and model-ledger tables | Persist the complete creative/review lineage used by fixture and Gemini modes. |
| Production control/delivery | v4 production configuration, destination/policy/readiness, budget/checkpoint, attempt/resource/cleanup/reconciliation tables | Freeze real account/profile/policy input and audit every authorized side effect. |
| Operations | `storage_samples`, `maintenance_runs`, `artifact_reconciliations` | Gate production work and retain backup/checkpoint/restore/retention evidence. |

The shared workflow poller now reuses the v1 runtime-visibility tables without a
schema change. It upserts one `worker_heartbeats` row per logical stage/instance
on every pass. A non-idle returned result appends `worker_runs`, using
`claim_type`/`claim_id` as the safe result-record type and ID; storage samples
already have append-only history and are not duplicated there. This is basic
freshness/result visibility, not the target active-claim, restart-count, or
lease-renewal model.

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
Legacy `database.sqlite.Database.initialize` refuses any nonzero schema version
before running legacy DDL. Versioned store constructors close their connection
when validation fails; read-only file URIs encode filesystem path characters.

### Configuration activation

Applying a manifest validates it before opening the write transaction. The
transaction inserts one immutable release and its materialized source
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
3. compare plausible recent lexical clusters locally outside the write
   transaction, then freeze the event partition and resolver evidence under
   the running owner/version/lease fence in `scout_event_resolutions`;
4. calculate scores from that committed partition without inference, then
   atomically append snapshots/memberships, insert or update the stable
   candidate rows, apply deterministic shortlist results, and complete the run;
   and
5. if selected, atomically create one trend `content_threads` row, immutable
   source-backed `brief_revisions` row and pending `determination_requests`
   row before setting the candidate to `selected`. No trend Intake is created.

Freeze creation is fenced by running state, owner and claim version under a
write transaction. A non-null input hash marks a completed freeze even when
there are zero attempt rows. A retry reuses both that list and `input_frozen_at`
plus its frozen event resolution for score windows/recency; selection budget accounting uses the retry execution
time. Contribution winners are resolved from the frozen set without rewriting
observations; v3 additionally enforces evidence immutability in SQLite.

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
| `trend_candidates` | `observed ↔ eligible`; `eligible → selected/deferred_by_budget`; active `shortlist_v2` keeps `deferred_by_budget` as a durable queue entry; `selected → consumed/rejected_cooldown`; `rejected_cooldown → reconsiderable`; `reconsiderable → selected/rejected_cooldown`; any pre-consumption state may enter `migration_hold` only during cutover | Trend Scout for observation/eligibility/selection; Determination later records consumption outcome |
| `content_threads` | `open → closed/cancelled`; `closed → open`; `cancelled` terminal | Detection creates open trend seeds; Dashboard/Idea Intake own human continuation and later lifecycle actions |
| `intake_requests` | `pending/retry_wait → claimed → completed/needs_clarification/retry_wait/failed/cancelled` | Idea Intake for human conversations; Detection does not create trend Intake requests |

The dashboard keeps reporting on a read-only connection and opens a separate
short write transaction only for human commands: new/continued Intake,
approve/reject/request-changes, production Post now, eligible pre-final cancel,
and explicit reconciliation request/resolution. Editorial acceptance alone
creates no PostRequest. The model ledger records Intake, Determination,
generation, and adaptation calls; v4 reservations and production adaptation
checkpoints add the current price/cost and restart boundaries.

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
