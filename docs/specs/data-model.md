# Data Model Specification

**Document role:** Tier 2 target design contract. It defines required behavior;
verify implementation conformance from code and tests.
**Owner:** SQLite persistence, migrations, boundary models, and their tests.
**Read this for:** Schema, migrations, worker state, IDs, audit records, or any
change to a persisted handoff. Read [the system guide](../system.md) first.
For the exact executable schema of the current v1–v4 implementation,
continue to the [SQLite record contract](data/records.md).

SQLite is the authoritative state store. Every worker claims work from and
writes its result to SQLite. The dashboard reads its reporting view and writes
only the narrow human command records defined in the [dashboard specification](dashboard.md),
including an immediate `PostRequest` for **Post now**.

## Conventions and invariants

- Use `INTEGER PRIMARY KEY AUTOINCREMENT` for permanent audit identities;
  enable foreign keys for every connection. Audit IDs are never reused.
- Store timestamps as UTC ISO-8601 `TEXT`.
- Use JSON `TEXT` only for structured, pipeline-specific values and name it
  `*_json`. Keep identity, status, ordering, and audit data relational.
- Messages, evidence snapshots, creative packages, decisions, attempts, and
  published records are append-only. Rework creates a new revision; it never
  overwrites history.
- Apply the bounded operational-data, redaction, and Gemini-input rules in
  [Reliability and safety](reliability.md#operational-data-minimization--operational_data_v1).
  Database rows contain safe hashes/summaries rather than credentials, signed
  URLs, raw provider bodies, or full model prompts/responses.
- Enforce status sets with SQLite `CHECK` constraints and enforce transitions
  through transactional service methods plus boundary tests.
- Acquire work in one short conditional transaction. Every claim stores owner,
  claimed time, lease expiry, and a monotonic `claim_version` fencing token. Do
  network/LLM/filesystem work outside a transaction, then finalize in a second
  short transaction that still matches the claimed state, owner, and version.
- Claimable work distinguishes `retry_wait` from terminal `failed`, records
  attempt count/limit, `retry_policy_version`, `next_attempt_at`, lease
  duration, and a persisted maximum-runtime deadline. It never lets an expired
  claimant commit after another worker has reclaimed the record.
- `row_version` is a positive monotonic integer on every mutable dashboard
  command target: `content_threads`, `review_requests`, `post_requests`,
  `post_records`, `reconciliation_requests`, and future mutable configuration
  activation records. Creation sets it to `1`; every permitted state or
  command-visible field transition increments it in the same transaction.
  It is distinct from worker-only `claim_version` fencing.
- The production schema uses versioned forward migrations. It must refuse an
  unknown/incomplete/newer schema rather than silently apply additive changes.

## Relationship map

```text
Candidate/evidence or human messages → ContentThread → IntakeRequest
  → BriefRevision → DeterminationRequest → DeterminationDecision
    → five DeterminationRoutes (selected/skipped/blocked/reused)
      → each selected route: ContentJob → GenerationRun → CanonicalContent
        → each frozen destination: OutputRequest → AdaptationRun → ContentPackage
          → RenderRun → RenderAssets → ReviewRequest → PostRequest → PostRecord
            → PostAttempt → PublicationResource → DeliveryCleanupTask
            → ReconciliationRequest → checks → human resolution
```

One decision may create several domain jobs, and one canonical object may serve
several output requests. No unique constraint on the determination request may
collapse this fan-out to one job; no unique constraint on the content job may
collapse it to one platform package. Required foreign keys preserve every branch.
Optional X threads additionally require ordered PublicationStep records before
their format is enabled. This is a record map, not direct worker calls.

## Atomic handoff-creation matrix

This matrix is the canonical inventory of who creates every cross-worker
handoff. Each row is one SQLite transaction; a failure rolls back all listed
new records and leaves no partial downstream input. An existing uniqueness
conflict is returned as the already-created durable result where its frozen
input matches, otherwise it is a typed conflict—not permission to create a
second record.

| Trigger and creator | Atomic persisted result | Uniqueness guard | Failure behavior |
| --- | --- | --- | --- |
| New human idea/rework — Dashboard command | New/continued thread, appended message, pending Intake Request, command receipt | client command ID; message sequence; one active Intake Request/thread | No message or request persists on a failed command. Duplicate submission returns its receipt. |
| Selected candidate — Trend Scout shortlist | candidate selection audit, seed trend thread, pending Intake Request, frozen candidate/evidence linkage | candidate can be selected once; `UNIQUE(seed_candidate_id)`; shortlist budget transaction | Candidate remains persisted/unselected or deferred; no worker call occurs. |
| Completed normal Intake — Idea Intake Agent | immutable Brief Revision, pending Determination Request, completed Intake Request | revision number/thread; `UNIQUE(revision_id)` determination request | Request stays claimed/retryable or fails safely; no partial revision. Coverage collision follows the separate merge transaction. |
| Determination completion — Determination Worker | completed request, immutable decision and five route rows; one ContentJob and initial GenerationRun per selected route; explicit reuse links | one decision/request, one route/decision/domain, one job/selected route, unique canonical content identity | All route/job creation rolls back together. Skipped/blocked routes create no job. |
| Successful generation — Pipeline Runner | succeeded GenerationRun, immutable CanonicalContent, all frozen OutputRequests and initial AdaptationRuns; slot transfer | canonical/run and canonical/job uniqueness; unique output identity | No partial canonical/output fan-out; no RenderRun yet. |
| Explicit output rework using unchanged canonical content — Determination finalization | completed decision/routes, canonical reuse link, scoped new OutputRequest and first AdaptationRun | one decision/request, unique output identity, canonical creative equality | No new generation or implicit sibling output; branch starts waiting for capacity. |
| Successful adaptation — Adaptation Worker | succeeded AdaptationRun, immutable ContentPackage, first pending RenderRun | package/output-request and package/adaptation-run uniqueness; one active render/package | No package without its RenderRun; siblings and canonical content are unchanged. |
| Successful render — Visual Renderer | succeeded Render Run, immutable manifest and asset rows, awaiting Review Request | asset role/ordinal; one active review/package/render/destination | Run returns to `retry_wait` or fails; no review request exposes partial assets. |
| Post now — Dashboard command | approved Review Request, immutable Post Request, initial pending Post Record, command receipt | review authorizes once; request/review and record/request uniqueness; client command ID | Approval is unchanged if transaction fails; no external call is made. |
| Delivery start — Posting Agent | claimed Post Record and append-only Post Attempt before any provider side effect | fenced post claim; unique attempt number/record | Claim mismatch leaves no attempt or provider call. |
| Media/container staging — platform adapter under the claimed attempt | `PublicationResource` for each staged remote/object resource and an eventual `DeliveryCleanupTask` for each R2 object | provider resource identity and resource/object cleanup uniqueness | Safe pre-final failure becomes record retry/failure with audit; cleanup remains independently claimable. |
| Possible final-publication uncertainty — Posting Agent | terminal `publication_unknown` Post Record and final-attempt evidence | final request marker and post-record fencing transaction | Never retry final publication automatically. A human may later create one Reconciliation Request; none is implied or automatically dispatched. |

Coverage collision is a special Intake finalization: it preserves the candidate
or human message, writes the documented merge evidence/message, closes the
unused seed thread, and creates downstream work only on the existing coverage
owner when permitted. It is never a second editorial handoff.

## Identity boundaries

| Identity | Stored with | Meaning and uniqueness |
| --- | --- | --- |
| Evidence | Observations/snapshots and decision | Frozen normalized evidence fingerprint; cooldown alone does not imply material change. |
| Opportunity | Candidate | `trend:<canonicalization_version>:<cluster_key>`; detection attention, not editorial coverage. |
| Coverage | Thread and revisions | Route-neutral editorial subject under `coverage_normalization_v2`, assigned by Intake; immutable unique non-null thread key. |
| Domain-angle coverage | Route and coverage reservation | Pipeline + normalized angle kind/target/sense/event scope; excludes account/platform/hook wording. Guards repeat treatment across threads/revisions. |
| Canonical content | ContentJob and CanonicalContent | Domain-angle identity + creative-input fingerprint (brief's creative scope, frozen evidence/reference versions, domain/content contract); excludes revision number alone, account/platform, retry number, and metadata/layout. |
| Output | OutputRequest and ContentPackage | Canonical ID/hash + explicit destination/platform/format + output contract and adapted-input version/fingerprint. No duplicate output because a worker restarted or a revision merely reused content. |
| Publication | PostRequest/PostRecord | Exact package/render/destination and explicit review cycle. At most one possible final send per publication identity; confirmed or uncertain output cannot silently re-enter another cycle. |

Identity serializers are deterministic over structured fields and persist their
versions and source components. Intake owns shared coverage; Determination owns
domain-angle selection. One shared topic can legitimately have several different
domain angles. Conversely, teaching the same expression/sense from a new trend
does not automatically justify a new English job.

A unique content identity blocks repeat model spending on unchanged creative
input even across revisions. A `domain_angle_reservations` guard points to
current and historical accepted work for each angle. A new generation under the
same angle requires explicit human rework or a permitted material-evidence
revision and a genuinely changed creative fingerprint. Automatic cooldown or
new hook wording cannot bypass that guard. Retain confirmed/uncertain
destination-publication history when assessing rework; never equate a fresh
package ID with permission to republish unchanged content.

`canonical_reuse_links` associates a new route/revision/output rework with the
prior canonical record and frozen reuse reason/fingerprint. It records reuse,
not fictional generation under the new job. Before adaptation admission, check the immutable output-input identity for
existing work. After adaptation/rendering, also compare the ordered final public
text and delivery asset hashes for the same destination, excluding audit IDs,
revision IDs, timestamps, and private tags from this duplicate fingerprint.
An identical pending, confirmed, or uncertain public output is linked/suppressed,
not offered as another publication merely because its package hash includes new
lineage. A typed duplicate outcome retains any incurred model cost. Exact
equality is enforced locally;
uncertain semantic duplicates remain an editorial review issue, not a claimed
perfect hash-based solution.

## Detection evidence — retained and extended

Retain `trends`, `trend_observations`, `topic_snapshots`, `trend_history`,
`source_health`, `source_collection_attempts`, `scout_evaluation_runs`, and `trend_candidates`. They remain
deterministic source evidence, never human ideas or content threads.

Add `detection_source_instances` as the persisted source registry. It holds a
stable source-instance ID, source-kind/version, provider display name,
endpoint/feed URL, declared delivery format where applicable, coverage note,
enabled state, expected poll cadence/availability interval, static trust weight,
independence group, language/region scope, local quota limit where applicable,
safe configuration JSON/fingerprint, required `configuration_release_id`, and audit timestamps. `source_health` and
every observation/run link to this record. A run stores the exact enabled-source
configuration snapshot it used; credentials never enter the database.

Add append-only `detection_cluster_aliases` with its exact normalized alias key,
target cluster key, canonicalization version, active state, recorded reason,
configuration version, and audit timestamps. An alias is operator-managed
deterministic configuration, never an LLM output or inference. Retain the
observation-to-cluster membership that was used for every scored candidate so a
later alias change cannot rewrite historical evidence.

Each evaluation appends an immutable `topic_snapshots` row for every scored
cluster. `trend_candidates` is the stable current lifecycle row, unique by
opportunity identity; it points to the latest snapshot while all earlier score
and evidence snapshots remain immutable. This separates historical scoring
evidence from selection/cooldown state and prevents a later evaluation from
creating a second seed thread for the same opportunity.

Extend candidate/snapshot records with:

- `evidence_fingerprint`, `score_formula_version`, and
  `canonicalization_version`;
- normalized score breakdown and cluster membership linked to exact observation
  IDs;
- cluster key, candidate opportunity identity, canonicalization version, and the
  exact alias-configuration version used;
- stable source-adapter/source-item IDs when a provider exposes them, canonical
  URL, provider timestamp, collection time, measurement window, and normalized
  activity; and
- candidate consumption and last determination outcome, last evaluated
  fingerprint, cooldown deadline, and shortlist policy/audit data: eligibility
  reason, rank, selected/deferred time, and selected thread ID.

Candidate eligibility uses an explicit closed state set rather than inferring
meaning from nullable timestamps: `observed`, `eligible`, `selected`,
`deferred_by_budget`, `rejected_cooldown`, `reconsiderable`, `consumed`, and
`migration_hold`.
`observed` means the opportunity is retained but currently fails one or more
score, reliability, history, or freshness gates; its exact reason is required.
`selected` means an Intake request was durably created; `consumed` means an
accepted route already owns that automatic opportunity. A `not_recommended`
decision moves the candidate to `rejected_cooldown`. Expiry alone makes it
`reconsiderable`; it does not authorize duplicate content. Re-evaluation also
requires a materially different evidence fingerprint under the versioned
Detection policy.

`thread_evidence_events` records later evidence mapped to an existing coverage
identity. It stores the candidate/thread FKs, prior and current evidence
fingerprints, comparator version, materiality outcome/reason, frozen evidence
snapshot, resulting Intake-request FK when material, and timestamps. Any later
revision is reached through that immutable Intake-request lineage rather than
backfilled onto the event. This append-only record is the audit bridge for
evidence refresh. Material evidence continues the existing thread; it never
creates a duplicate thread.

`source_collection_attempts` is one claimable provider operation for one source
instance and scheduled collection time. It freezes source configuration and
request parameters, records attempt ordinal, response/body hash or safe error,
provider and collection times, completeness, item counts, quota reservation,
and its exact immutable observation IDs on completion. Its terminal record is
never re-fetched or overwritten. `source_health` is append-only source-instance
health evidence derived from that collection attempt: requested/actual
measurement window, item count, completeness result, health
classification/reason, fallback mode, latency, and structured error category.

`scout_evaluation_runs` is a separate claimable, no-provider-call work item for
one 15-minute UTC evaluation slot and configuration-release fingerprint. When
claimed, `scout_evaluation_inputs` freezes the latest eligible collection and
health summary for every enabled source instance as of `input_frozen_at`; each
summary records whether it is `current`, `reused`, `degraded`, `unavailable`,
`failed`, or `quota_limited` and the exact reason. Immutable
`scout_evaluation_attempts` rows additionally enumerate every completed
collection attempt actually used in the current or baseline windows. It then creates candidate/topic score
snapshots and performs the shortlist transaction. It records aggregate counts,
frozen input hash, and safe error. A later successful collection creates a new
evaluation run; it never rewrites a completed evaluation's input. Completion
appends topic snapshots and observation memberships, then inserts or updates
the one stable candidate row for each opportunity identity. Shortlist
audit retains eligibility, rank, `selected_at`,
deferred/stale reason, and the frozen score/evidence used for any recurrence
comparison. A selected candidate’s exact evidence is copied into the first
revision’s `source_snapshot_json`.

## Thread and revision records

### `content_threads`

| Column | Requirement |
| --- | --- |
| `thread_id` | Primary key. |
| `origin` | `trend`, `human`, or migration-only `legacy`. |
| `seed_candidate_id` | Nullable FK to `trend_candidates`; required for `trend`. |
| `coverage_identity` | Canonical editorial coverage key. Null for a new seed thread; assigned atomically with Revision 1 under `coverage_normalization_v2`, then immutable and unique when present. |
| `status` | `open`, `cancelled`, or `closed`. This is administrative, not worker state. |
| `created_at`, `updated_at`, `closed_at`, `cancelled_at` | Audit timestamps. |
| `row_version` | Positive monotonic dashboard concurrency version; starts at 1 and increments on close, reopen, cancel, or collision closure. |
| `closure_actor`, `closure_reason` | Required audit fields when `closed` or `cancelled`; safe human-provided reason is optional. |

Enforce `origin != 'trend' OR seed_candidate_id IS NOT NULL` and
`UNIQUE(seed_candidate_id)`. Both trend and human seed threads begin without
coverage identity. Idea Intake assigns it atomically with Revision 1 under
`coverage_normalization_v2`; it is immutable thereafter. A rework stays in its
existing thread and creates another revision. On collision, the transaction
attaches a trend candidate as evidence to the existing owner or directs a human
to continue it, then closes the unused seed thread with
`coverage_collision_merged`; it does not create a second revision/job.

`closed` is an orderly archival state. It may be entered only when no
claimable/claimed intake, determination, generation, adaptation, render, review, or
delivery record remains for the thread; terminal failed, rejected, cancelled,
published, and `publication_unknown` history remains visible. A human must
explicitly reopen a closed thread before continuing it; reopening changes only
the administrative thread status and creates no revision by itself.

`cancelled` is an instruction to stop unfinished work. It is terminal for the
thread: it cannot be reopened, and a later materially new idea requires a new
thread. Cancellation does not delete or mutate immutable history. Its permitted
cascade and the final-publication boundary are defined in the Idea Intake and
Determination and Posting contracts.

The POC uses a strictly linear revision history: a new revision must name the
current latest revision as parent. Only one non-terminal Intake request may
exist per thread.

### `thread_messages`

Append-only human/agent conversation.

| Column | Requirement |
| --- | --- |
| `message_id` | Primary key. |
| `thread_id` | Required FK to `content_threads`. |
| `sequence_number` | Positive; unique within its thread. |
| `author_kind` | `human`, `intake_agent`, or `system`. |
| `body` | Non-empty original text. |
| `in_reply_to_message_id` | Optional message FK. |
| `created_at` | Timestamp. |

Messages are context, not production instructions. The Idea Intake Agent uses
them to ask a question or freeze a revision.

### `intake_requests`

An Intake request is the durable handoff to the Idea Intake Agent. It contains
the thread FK, optional current/parent revision FK, optional first/last
input-message FKs (null for a trend event without a human message), frozen
request context/version, and status (`pending`, `claimed`,
`retry_wait`, `needs_clarification`, `completed`, `failed`, or `cancelled`). It
also records claim owner/time/lease/version, attempt count/limit,
`next_attempt_at`, safe error, result message/revision FKs, and audit
timestamps.

`needs_clarification` is terminal for that individual request (and therefore
not claimable), while the thread remains open awaiting a later human command.

Creating a human thread, its first message, and its first Intake request is one
transaction. Continuing a thread appends the human message and creates the
next Intake request in one transaction. A clarification response creates a
new request; the prior request remains `needs_clarification`. A completed
request creates exactly one revision and its pending Determination request in
the same transaction. An evidence-refresh event uses the same handoff and
references the event that caused it.

### `brief_revisions`

One immutable agreed brief per numbered version.

| Column | Requirement |
| --- | --- |
| `revision_id` | Primary key. |
| `thread_id`, `revision_number` | Required FK and positive number; unique pair. |
| `parent_revision_id` | Optional revision FK; must be in the same thread. |
| `input_through_message_id` | Last message considered; may be null only when no human message exists. |
| `brief_json` | Required route-neutral brief, coverage inputs, audience, desired outcome, constraints, and explicit whole-brief/domain/output revision scope. |
| `source_snapshot_json` | Frozen candidate/detection evidence or original-conversation context. |
| `revision_reason` | `initial`, `human_rework`, `evidence_refresh`, `capability_recheck`, or `migration`. |
| `created_by` | `intake_agent`, `system`, or `system_migration`. |
| `source_intake_request_id`, `source_evidence_event_id`, `source_blocked_decision_id` | The Intake request, optional evidence event, and optional decision containing blocked routes that caused the revision. A capability recheck names that decision and the specific blocked routes and has no Intake request; migration is the other exception to the Intake-request requirement. |
| `created_at` | Freeze time. |

There is no editable draft revision. Conversation remains in messages until the
agent freezes the next immutable snapshot. A `capability_recheck` is the sole
non-conversational revision: the dashboard's explicit command copies the frozen
brief/source context unchanged, names the prior decision containing the blocked route(s), and creates a
new Determination request with a newly frozen routing-input snapshot. It never
changes editorial content or overwrites the old decision.

## Determination records

### `determination_requests`

This replaces trend-only `determination_handoffs`.

| Column | Requirement |
| --- | --- |
| `determination_request_id` | Primary key. |
| `revision_id` | Required unique FK: one evaluation per frozen revision. |
| `input_snapshot_json` | Exact brief, evidence, capability catalog, prompt/schema version sent to the evaluator. |
| `status` | `pending`, `claimed`, `retry_wait`, `completed`, `failed`, or `cancelled`. The decision outcome is stored separately. |
| `claim_owner`, `claimed_at`, `lease_expires_at`, `claim_version` | Fenced recovery metadata. |
| `attempt_count`, `attempt_limit`, `next_attempt_at` | Bounded retry metadata. |
| `created_at`, `completed_at`, `failure_reason` | Audit/recovery fields. |

### `determination_decisions` and `determination_routes`

One immutable decision per request stores aggregate outcome, opportunity value,
whole-decision rationale, warnings, evidence/coverage identities, and frozen
routing-policy/catalog/readiness fingerprints. It no longer contains one nullable
selected capability/recipe. The outcome derives from the five route rows under
[Intake and Determination](idea-intake-and-determination.md).

Each route has decision FK, stable pipeline ID/version, fit, disposition,
reason, nullable frozen angle, source support, output assessments, and optional
prior-work reuse reference. Enforce `UNIQUE(decision_id, pipeline_id)`, all five
catalog domains exactly once, and selected/blocked/reused angle requirements.
Only `selected` creates a new job. One fenced transaction writes the complete
decision/routes/job/run set and finishes the request.

## Production and rendering records

### `content_jobs`

An immutable domain/angle generation recipe belongs to one selected route:
`UNIQUE(determination_route_id)`, with required `content_identity` unique across
jobs. The determination-request FK is lineage, **not unique**. Recipe fields
freeze domain/angle, audience/objective, evidence/reference inputs, creative
fingerprint, domain/model/budget versions, priority, and bounded output plan.
The output plan is distribution intent, not platform-specific canonical copy.

A ContentJob has no claim/lease/lifecycle. Derive progress from its generation
and output children; an aggregate must not hide a failed sibling. Reused routes
link prior canonical work instead of inventing another job or charging again.

### `generation_runs` and `canonical_contents`

GenerationRun is the Pipeline Runner's claimable input: required job FK,
positive run number, frozen domain recipe/hash and versions, claim envelope,
safe errors, and status `waiting_capacity/pending/claimed/running/retry_wait/
succeeded/failed/cancelled`. Enforce unique job/run number and one active run/job.
Only audited safe terminal recovery may create another numbered run.

Checkpoint validated canonical draft and validation evidence/hash before
dependent work. The successful transaction inserts immutable CanonicalContent,
creates all OutputRequests/initial AdaptationRuns from the frozen plan, transfers
downstream reservations, releases the generation execution slot, and succeeds
the run. It creates no ContentPackage or RenderRun.

CanonicalContent has required unique job and successful generation-run FKs,
canonical identity/hash, pipeline/angle, common envelope/domain payload, sources,
claim mappings, validation evidence, and schema/model versions. It is
platform-neutral and has no worker status. See
[Content production](content-production.md) for its payload and validation.

### `output_requests` and `adaptation_runs`

OutputRequest is an immutable recipe with canonical-content FK/hash, originating
route/revision or explicit reuse-link FK, exact output binding/destination,
format, output/renderer/policy versions, adaptation-input fingerprint, and unique
output identity. One canonical record may have several OutputRequests; the
initial frozen plan allows at most one Instagram and one X destination.

AdaptationRun has required OutputRequest FK, positive run number, frozen input,
validated adapted-copy/metadata checkpoints and hashes, model-policy versions,
claim envelope, safe errors, and the same closed state set as GenerationRun.
Enforce unique output-request/run number and one active run/output request.
A safe retry resumes the same record; a safe terminal recovery creates another
numbered run without regenerating canonical content.

### `content_packages`

One immutable package per OutputRequest and successful AdaptationRun:
`UNIQUE(output_request_id)` and `UNIQUE(adaptation_run_id)`. Several packages
may reference the same canonical content/job. Remove the legacy unique
generation-run/job package constraints in the new forward production schema.

A package contains canonical lineage/hash, destination/platform/format, adapted
creative, caption or ordered X post text, tags/hashtags/alt text as applicable,
sources and claim mappings, output/schema/model versions, resolved
`visual_spec_json`, and content hash/time. No mutable ready/posting status.
Its creation atomically creates RenderRun number 1. A later output change is an
explicit scoped revision/new OutputRequest, never mutation of reviewed copy.

### Production reservations and reuse records

`production_admission_policies` defines versioned generation/adaptation
execution limits and per-destination unreviewed capacity.
`production_capacity_reservations` records explicit scope/slot, policy/release,
job/run/output lineage, active/released state, origin priority, and acquisition/
transfer/release audit. A partial unique index on active policy/slot enforces
capacity; a unique run alone cannot enforce a two-slot capacity limit.
The exact multi-reservation acquisition/release protocol belongs to
[Content production](content-production.md#admission-and-model-spending).

`domain_angle_reservations` and `canonical_reuse_links` retain the duplicate
guard and explicit reuse lineage described above. Required FK/uniqueness,
same-domain/same-angle checks, and append-only histories must be in the forward
schema before enabling production. New review cycles and terminal local recovery
reacquire appropriate capacity; they do not reset historical reservations.

### `render_runs` and `render_assets`

The package-creation transaction creates Render Run number 1. It is the Visual
Renderer's only claimable input. A later Render Run is permitted only through
an audited terminal rerender/recovery operation; only one can be active for a
package at a time. `render_runs` holds package FK, positive run number,
renderer-provider ID/version, resolved renderer-owned profile/template
selection, frozen input/specification hash, resolved font/asset input versions,
common fenced-claim and bounded-retry fields, status (`pending`, `claimed`,
`running`, `retry_wait`, `succeeded`, `failed`, `cancelled`), timestamps, safe
error category/text, and an output manifest. A retry-safe failure returns the
same run to `retry_wait` and increments its attempt envelope. It never
overwrites a succeeded run; a separately requested rerender creates a new run
number with a fresh frozen input/audit reason.

`render_assets` holds run FK, `asset_role`, unique ordinal within role, local
path, MIME type, dimensions, bytes, SHA-256, conversion/encoder version, and
timestamp. Roles include `preview_html`, `preview_png`, and
`delivery_jpeg`; destination-specific references may add stricter roles. The
delivery JPEG is generated and verified locally and is canonical review input.
The RenderRun frozen input records each unit's profile/template/theme IDs,
binding hash, local font/asset hashes, output dimensions, validation result,
and renderer/Chromium/encoder versions.
A successful complete run atomically freezes the output manifest and creates
one review request. R2 copies and signed delivery URLs are transport
derivatives, not canonical assets.

## Human review and delivery records

### `review_requests`

One review request exposes one exact package/render/destination review cycle:

- package and render-run FKs plus a positive review-cycle number, unique as a
  triple;
- required content-package hash and render-manifest hash copied at creation;
- status `awaiting_review`, `approved`, `changes_requested`, `rejected`,
  `invalidated`, `expired`, or `cancelled`;
- creation, expiry (`created_at + 14 days` for that cycle), decision, and
  terminal-state timestamps plus decision note, actor, and positive
  `row_version`.

Only one review request may be active per package/render/destination. Approval first revalidates
the package, manifest, asset hashes, policy freshness, and destination/profile
compatibility; it is terminal for that request and atomically creates one post
request plus its initial post record. `changes_requested` atomically appends a
human thread message and an Intake request for a new revision. Rejection is
terminal and preserves the creative/history. Any asset/package mutation or
explicitly superseding revision within this output/domain's scope invalidates the request; creative change always starts a
new revision. Unchanged sibling outputs are not invalidated by an output-local
rework. Only an explicit human command may create a later review cycle
for the unchanged package/render/destination triple; it is permitted only after
this request is `expired` or after a linked `not_published_cancel` reconciliation
decision. The new cycle has its own `created_at` and 14-day expiry, after
revalidating the exact asset bytes/hashes and compatible destination policy; it
never inherits the prior request's expiry. A confirmed-published package is
never eligible for another cycle.

### `post_requests`, `post_records`, and `post_attempts`

`post_requests` is immutable human authorization: unique review FK,
package/render FKs and approved hashes, destination, `delivery_mode`
(`immediate` only in the initial POC), request time, status (`approved`,
`cancelled`, `expired`, `fulfilled`), expiry time, publication identity, and
audit timestamps. It is
not worker-claimable. The initial POC does not persist a human-requested
delivery time or schedule.

`post_records` is the external delivery lifecycle: unique request FK,
policy-derived `eligible_at`, status (`pending`, `claimed`, `publishing`,
`retry_wait`, `failed`, `published`, `publication_unknown`, `cancelled`,
`expired`), the
common fenced-claim/bounded-retry fields, external post ID, final timestamps,
and typed error.
`publication_unknown` is terminal until human reconciliation, never automatic
retry.

`post_requests` and `post_records` each carry positive `row_version`. The
dashboard targets the Post Record version for cancellation/reconciliation and
revalidates its linked request in the same transaction; any allowed worker,
expiry, or dashboard state transition increments the affected row version.

`delivery_mode=immediate` records the human's requested urgency; the active
posting policy still owns the computed `eligible_at`. The architecture does
not infer whether immediate mode bypasses cadence. If the versioned policy does
not explicitly answer that question, creation/delivery is blocked rather than
guessed.

`posting_policies` stores IANA account time zone, daily cap, minimum interval,
policy version, and slot-reservation rule. For O2 `posting_policy_v1`, these
are `Asia/Seoul`, one post/account-day, 20 hours, and reservation only after a
possible final provider request. The policy-derived `eligible_at` and expiry
are copied to the Post Record audit trail.

The 48-hour immediate-request expiry is evaluated transactionally before a
claim and before the final provider request. If no attempt has begun by that
time, or staging began but the final marker has not committed, the authorization
and record both transition to `expired`; neither may
later be reclaimed. Both checks require `now < expires_at`. A final marker
committed before expiry retains its published/unknown outcome after expiry;
expiration never retries or cancels that possible external effect.
An exact reviewed package may have at most one
confirmed-published publication identity across all of its review cycles.
A temporary readiness failure (including token expiry or provider outage) blocks
delivery before a provider call without changing human approval. A changed
destination/account configuration, reviewed-hash mismatch, or incompatible
frozen-asset requirement invalidates the binding instead and requires a fresh
review cycle.

`post_attempts` has a record FK, unique attempt number, start/completion,
typed error, and `final_publication_request_sent_at`. Its status set is
`created`, `staging`, `ready_to_publish`, `final_request_sent`, `succeeded`,
`retryable_failed`, `failed`, `cancelled`, or `outcome_unknown`. Create it as
`created` before the first external side effect. Only `created`, `staging`, or
`ready_to_publish` can become `retryable_failed`; once the final request may
have been transmitted it becomes `final_request_sent` followed by `succeeded`
or `outcome_unknown`. The latter atomically makes the parent Post Record
`publication_unknown`; an absent response is never a safe retry.

Before the final marker, dashboard cancellation may atomically transition a
`created`, `staging`, or `ready_to_publish` attempt to `cancelled` with its
parent request/record. Every staged R2 resource receives a cleanup task in that
transaction; provider containers become audited `retained` resources with the
reason `cancelled_before_final_publish`. The final-marker transaction and
cancellation transaction both condition on the same current Post Record/request
state, so exactly one wins. `final_request_sent`, `succeeded`, and
`outcome_unknown` attempts cannot be cancelled.

### `publication_resources` and `delivery_cleanup_tasks`

`publication_resources` generalizes Instagram containers: attempt FK, optional
asset ordinal, resource type (`staged_media`, `carousel_child`,
`carousel_parent`, or later platform type), remote/object ID, status, safe
metadata, and timestamps. Its status set is `created`, `ready`, `published`,
`cleanup_pending`, `cleaned`, `retained`, or `failed`. Adapter creation begins
at `created`; provider readiness becomes `ready`; a confirmed parent post may
mark the published resource `published`; safe staging cleanup moves through
`cleanup_pending` to `cleaned`; and a provider object that cannot or should not
be deleted is `retained`. Never retain tokens or signed URLs.

`delivery_cleanup_tasks` owns R2 cleanup: resource FK, object key, status
(`pending`, `claimed`, `retry_wait`, `succeeded`, `failed`, `cancelled`), the
common fenced-claim/bounded-retry fields, error, and timestamps. Cleanup
failure stays visible but does not change a confirmed post to failed.

### Reconciliation records

`reconciliation_requests` is the durable operator/agent work item for one
`publication_unknown` Post Record. It stores reason, status (`pending`,
`claimed`, `retry_wait`, `needs_human`, `resolved`, `failed`, `cancelled`), the
common fenced-claim/bounded-retry fields, and audit timestamps. At most one is
active per Post Record.

It also carries positive `row_version`. A human reconciliation decision matches
the displayed request version and the exact completed check/evidence IDs; claim
fencing remains separate.

Each external inspection creates an append-only `reconciliation_check` with
request FK, provider query/matching-rule version, safe response summary/hash,
candidate external IDs, outcome (`confirmed_published`,
`confirmed_not_published`, `ambiguous`, or `provider_unavailable`), and time.
Automation may resolve only an unambiguous published match. A
`human_reconciliation_decision` records actor, exact check/evidence considered,
decision (`published`, `not_published_cancel`, or `leave_unknown`), note, and
time. No reconciliation path silently retries the final publication call.

## Cross-cutting records

- `configuration_releases` is immutable validated/rejected manifest audit:
  release name, scope key, schema ID/version, manifest JSON/hash, validation
  outcome/safe diagnostics, operator, and timestamps. `configuration_activations`
  is the mutable active/superseded scope pointer with row version and command
  receipt. Their full lifecycle is owned by the
  [Configuration control plane](configuration.md).
- `pipeline_capabilities` is the immutable release-materialized **domain**
  catalog: pipeline ID/version, enabled state, remit/goals/input constraints,
  generation prerequisites, and release FK. It contains no platform/account.
- `output_bindings` separately maps a domain to a configured destination,
  platform/format/output-contract version and compatible renderer/policy versions.
  `social_destinations` owns stable account identity and safe secret references.
  Neither stores secrets. Decisions freeze both registries.
- `capability_readiness` is one current mutable row per
  typed readiness subject (`domain` or `output_binding`) and release identity. It records the inspected
  configuration-release fingerprint, checked/valid-until times, status
  (`ready`, `degraded`, `blocked`, or `unknown`), typed blocking reasons,
  non-secret token-expiry time where applicable, renderer/profile availability,
  provider/media-domain readiness, monitor build/version, safe summary, and
  positive row version. `capability_readiness_checks` is append-only evidence
  for each inspection. The Readiness Monitor is its only writer; consumers
  freeze/read it but never infer readiness from local configuration.
- `teaching_references` and `teaching_reference_assertions` are immutable
  release-materialized O2 internal teaching policy. A reference records its
  stable internal ID/version, approval actor/time, active or superseded state,
  and configuration-release FK. Each assertion records its reference, stable
  assertion ID, allowed type/claim IDs, canonical target, and bounded approved
  text. Packages freeze reference/assertion IDs and hashes; an assertion change
  creates a new release/version rather than editing prior evidence. Neither
  table contains a source URL, external attribution, copyright notice, or text
  that must be rendered publicly.
- `posting_policies` remains release-materialized and keyed by
  destination/platform/account with daily and interval limits. Domain changes
  cannot create separate cadence quotas for the same social account.
- `human_command_receipts` provides command idempotency and audit for dashboard
  writes: unique client command ID, command kind, durable actor identifier,
  short-lived local browser-session identifier where applicable, target
  record/version read, target row version produced when applicable, safe payload
  hash, result-record references, and timestamp.
  The POC records `local_owner` for every dashboard command. Repeating the same
  ID/payload returns the original result; reusing it with different input is
  rejected.
- `model_invocations` replaces ambiguous `api_usage`: phase, applicable entity
  FKs including `generation_run_id` and `adaptation_run_id` plus their shared job budget owner, attempt ordinal, request/prompt/schema
  version and safe request hash, model/provider request ID, response hash,
  input, output, and total tokens; estimated cost; outcome (`started`, `succeeded`, `transport_failed`,
  `invalid_output`, `parse_failed`, `schema_failed`), safe error, start time,
  and completion time. `outcome` is the only Model Invocation lifecycle field;
  it is never called `status`. Insert and commit `outcome=started` before the provider call;
  finalize that row immediately after response or transport failure and before
  interpreting output. A stale `outcome=started` row is an uncertain-cost audit event,
  not evidence that no call occurred.
- `gemini_budget_reservations` records the UTC accounting day, model invocation
  or claim FK, frozen price-snapshot hash, phase token maxima, daily/job limits,
  computed worst-case reserved cost, settled cost when known, status, and audit
  timestamps. Monetary values are nonnegative integer micro-USD; no floating
  point admission arithmetic is permitted. Its status set is `reserved`, `settled`, `released`, or
  `uncertain`. Admission atomically creates `reserved`; a conclusively
  pre-provider cancellation may make it `released`; a completed invocation
  makes it `settled`; and a stale `outcome=started` invocation makes it
  `uncertain`. Only an explicit accounting-recovery transaction with evidence
  may change `uncertain` to `settled` or `released`. Daily admission counts
  settled cost plus the worst-case amount of `reserved` and `uncertain` rows.
  A unique active reservation binds one invocation/claim. A release without a
  valid matching price snapshot cannot create a reservation or start Gemini.
- `worker_heartbeats` keeps one current health row per worker instance: worker
  type, instance ID, start/last-seen time, state, current claim reference, build
  version, and safe health summary. Heartbeats update this row rather than
  generating append-only noise.
- `worker_runs` is append-only and records only substantive invocations that
  claim or process work: worker name/instance, claimed entity, start/end,
  status, and safe summary/error. It complements—not replaces—per-item
  state/leases and the current heartbeat row.
- `storage_samples` is append-only: sampled time, free/total bytes, threshold
  state, SQLite/WAL/artifact/backup bytes, and safe diagnostic summary. The
  latest sample drives the shared claim gate; it never contains file listings.
- `maintenance_runs` is append-only: kind (`sqlite_backup`, `restore_verify`,
  `wal_checkpoint`, or `artifact_retention`), start/end/status, safe counts,
  backup identity/checksum where applicable, and safe failure detail.
- `recovery_requests` is a claimable, append-only operator handoff for one
  terminal local record. It names the failed source record/type, typed reason,
  actor, command receipt, source row-version/fingerprint, safety assessment,
  status, claim envelope, and exactly one replacement run/task when approved.
  Only Generation Runs, Adaptation Runs, Render Runs, and Cleanup Tasks may be recovery targets.
  Recovery creates a new numbered run or a new cleanup task from immutable
  parent input; it never rewrites a failure, invokes a provider directly, or
  targets a Post Record/Attempt or `publication_unknown`.
- `retention_runs` is append-only: policy version, started/completed time,
  status, cutoff, per-table eligible/deleted/retained counts, summary hashes,
  and safe failure. It is the audit parent for preserved daily rollups made
  before high-volume detail deletion.
- `schema_migrations` stores forward migration version/name/time/checksum.

## Target record inventory and transition rules

The executable schema for the current implementation is owned by the
[SQLite record contract](data/records.md) and its linked v1–v4 canonical SQL.
The catalog below is the complete target inventory; some records are implemented
in those migrations and others remain planned. It is not a second DDL
definition. Any missing record/field/index requires a new forward migration
before dependent code is enabled.

The machine-contract maturity and schema versions are listed in
[Machine-checkable contracts](../contracts/README.md). Every named `*_json`
field below identifies one of those schema IDs or a field contract owned by
its focused specification; JSON validation is required before persistence and
again before a downstream consumer uses the value.

The target migration uses `INTEGER PRIMARY KEY AUTOINCREMENT` for every
permanent target-record identity, `TEXT NOT NULL`
UTC timestamps, `TEXT` JSON columns, `INTEGER` booleans constrained to `0/1`,
and explicit `CHECK` status sets. Required business references use `NOT NULL`
foreign keys; optional lineage references are nullable. All audit/history
foreign keys use `ON DELETE RESTRICT`; no published, review, attempt, model, or
evidence record is cascade-deleted. Mutable queue rows are updated only through
their owning transactional service; append-only records are never updated after
creation except for completion fields explicitly named by their contract.

Each claimable table has its own closed status set and transition matrix below;
there is no generic lifecycle that silently adds states to an entity. A worker
claim transition requires the expected prior status, owner, and `claim_version`;
lease expiry returns only the table's explicitly safe work to `retry_wait`.
Terminal rows cannot be reclaimed. Partial unique indexes enforce at most one
active claim/run/review/reconciliation item per owning entity; active means the
table's explicitly non-terminal status, never merely a nullable completion time.

The baseline migration must be reviewed as generated SQL plus typed boundary
models and tests. It may not infer a column, FK action, status, default, or
transition from legacy code.

### Column, foreign-key, and retention catalog

This is a planning catalog, not executable DDL. Phase 1 production additions
remain design-approved pending exact forward schemas and fixtures. Every named primary key (for example,
`thread_id` or `content_package_id`) is `INTEGER PRIMARY KEY AUTOINCREMENT`.
Every non-primary-key `*_id` is `INTEGER NOT NULL` and references the named
parent with `ON DELETE RESTRICT` unless the row says optional. `created_at` is `TEXT NOT NULL` UTC;
`updated_at`, `completed_at`, and `deleted_at` are nullable UTC `TEXT`. A
required scalar is `TEXT NOT NULL`, `INTEGER NOT NULL`, or `REAL NOT NULL` as
its name/value requires; a `*_json` value is validated `TEXT NOT NULL`; and a
boolean is `INTEGER NOT NULL CHECK (value IN (0,1))`. `status` is `TEXT NOT
NULL` with the exact documented `CHECK` set and has no implicit default. Queue
rows use explicit creation status; immutable/audit rows have no update path.
Every retained row has `created_at`; mutable registries additionally have
`updated_at`. "Audit" means retain the row indefinitely in SQLite backups;
"artifact" means retain its manifest/hash audit row indefinitely while T11 may
delete only the referenced physical bytes under its documented conditions.

| Table | Required columns beyond common `id` / timestamps | Parent FKs and uniqueness | Owner / retention |
| --- | --- | --- | --- |
| `detection_source_instances` | stable ID, kind/version, provider, endpoint, format nullable, coverage, enabled, cadence/availability, trust, independence, scope, quota nullable, config/fingerprint | unique stable ID/configuration release, as current SQL | Detection registry / audit |
| `configuration_releases` | release name, scope, schema ID/version, manifest/hash, validation outcome/diagnostics, operator | `UNIQUE(scope_key, release_name)`, immutable | Configuration Operator / audit |
| `configuration_activations` | scope, active release, active/superseded status, row version, actor/reason, command receipt | one active activation/scope | Configuration Operator / audit |
| `source_collection_attempts` | source config/request snapshot, scheduled/provider/collection times, response hash/safe error, completeness/counts, quota reservation, status, claim envelope | source instance; `UNIQUE(source_instance_id, scheduled_for, configuration_release_id)` | Trend Source Collector / audit |
| `scout_evaluation_runs` | evaluation slot, frozen-at/configuration fingerprint, frozen input hash, status, aggregate counts, safe error, claim envelope | `UNIQUE(evaluation_slot_start, configuration_release_id)` | Trend Scout + Shortlist / audit |
| `scout_evaluation_inputs` | source state, source-health/collection-attempt FKs nullable, exact reason, frozen input ordinal | evaluation run plus source instance; `UNIQUE(scout_evaluation_run_id, source_instance_id)` | Trend Scout / audit |
| `scout_evaluation_attempts` | measurement role and ordinal | evaluation run, source instance, and exact completed collection attempt; unique attempt within the run | Trend Scout / audit |
| `source_health` | collection attempt, window, item count, completeness, classification/reason, fallback, latency, error category | source instance and collection attempt; `UNIQUE(source_collection_attempt_id)` | Detection / audit |
| `trends` | canonical subject/key, first/last observed, safe current metadata | `UNIQUE(canonical_key)` | Detection / audit |
| `trend_observations` | source item ID nullable, canonical URL nullable, provider/effective/collection time, window, activity/rank, title snapshot, payload, activity-contributor flag | source collection attempt, source instance, and trend; `UNIQUE(source_collection_attempt_id, source_item_id)` where source item exists | Detection / audit |
| `source_item_events` | source ordinal/key nullable, closed rejection/exclusion disposition, safe reason, payload hash | source collection attempt and source instance; one event per rejected/excluded item/ordinal | Detection / audit |
| `topic_snapshots` | normalized cluster/key, score inputs, evidence snapshot/hash, formula/canonicalization version | scout evaluation run; unique cluster within its owning run | Detection / audit |
| `trend_history` | candidate/trend state event, old/new status, reason, score/rank snapshot | trend and candidate nullable | Detection / audit |
| `detection_cluster_aliases` | normalized alias, target key, canonicalization/config version, active, reason | `UNIQUE(alias_key, canonicalization_version, configuration_version)` | Detection configuration / audit |
| `trend_candidates` | stable opportunity identity, latest snapshot/evidence, current score/rank/breakdown, eligibility/status, cooldown, shortlist and consumption audit | latest topic snapshot and selected seed thread optional; `UNIQUE(opportunity_identity)` | Detection / audit |
| `candidate_observation_memberships` | ordinal, contribution, frozen observation snapshot | candidate, topic snapshot, and observation; unique observation and ordinal within the topic snapshot | Detection / audit |
| `content_threads` | origin, seed candidate nullable, coverage identity nullable, administrative status, closure audit, row version | seed candidate optional; `UNIQUE(seed_candidate_id)`, unique non-null coverage identity | Idea Intake / audit |
| `thread_evidence_events` | old/new evidence fingerprints, comparator/outcome, snapshot, result Intake FK nullable | candidate and thread; result intake optional | Detection + Intake / audit |
| `thread_messages` | sequence, author kind, body, reply ID nullable | thread; optional self-reply; `UNIQUE(thread_id, sequence_number)` | Dashboard / audit |
| `intake_requests` | revision/message/event references nullable as documented, context/version, status, claim envelope, result references nullable, safe error | thread plus optional parent references; one active request per thread | Idea Intake / audit |
| `brief_revisions` | revision number, parent nullable, input message nullable, brief/source snapshot, reason, creator, causation references | thread plus optional same-thread parent/source references; `UNIQUE(thread_id, revision_number)` | Idea Intake / audit |
| `pipeline_capabilities` | pipeline ID/version, enabled, goals/constraints, generation prerequisites | configuration release; unique pipeline/version/release | Domain catalog / audit |
| `production_admission_policies` | typed execution or destination scope, limits, priority, policy fingerprint | configuration release; unique scope/version/release | Production Admission / audit |
| `production_capacity_reservations` | scope/slot, job/run/output lineage, acquire/transfer/release audit | policy plus applicable owner; one active reservation per policy/slot | Production Admission / audit |
| `capability_readiness` | typed domain/output-binding subject, release, checked/valid-until, status/reasons, safe facts, row version | one current row per typed subject/release | Readiness Monitor / current health |
| `capability_readiness_checks` | input fingerprint, individual check outcomes, safe evidence/error, check time | readiness row | Readiness Monitor / audit |
| `teaching_references` | stable/versioned internal reference ID, approval/status, configuration release | `UNIQUE(reference_id, reference_version)` | Configuration Operator / audit |
| `teaching_reference_assertions` | stable assertion ID, type, canonical target, bounded approved text, allowed claim IDs | teaching reference; `UNIQUE(teaching_reference_id, assertion_id)` | Configuration Operator / audit |
| `determination_requests` | revision snapshot, status, claim envelope, failure fields | `UNIQUE(revision_id)` | Determination / audit |
| `determination_decisions` | aggregate outcome, rationale/warnings, identities and input fingerprints | unique determination request | Determination / audit |
| `content_jobs` | domain/angle recipe, creative fingerprint, output plan, budget versions, content identity | unique selected route; unique content identity; request lineage is not unique | Determination / audit |
| `generation_runs` | run number, frozen canonical input, checkpoint/hash, state and claim envelope | job; unique job/run number, one active run/job | Pipeline Runner / audit |
| `content_packages` | canonical hash, output-specific copy/metadata/visual spec, destination, content hash | unique OutputRequest and AdaptationRun; canonical/job are not unique | Adaptation Worker / audit |
| `render_runs` | positive run number, renderer/version, resolved visual inputs/hashes, manifest, status, claim envelope, safe error | package; `UNIQUE(content_package_id, run_number)`, one active run per package | Visual Renderer / audit |
| `render_assets` | role, ordinal, local artifact path, MIME/dimensions/bytes/SHA-256, encoder version | render run; `UNIQUE(render_run_id, asset_role, ordinal)` | Visual Renderer / artifact |
| `review_requests` | cycle, copied package/manifest hashes, destination key, status, expiry/decision fields, row version | package/render plus destination key; `UNIQUE(package_id, render_run_id, destination_key, review_cycle)` and one active triple | Dashboard / audit |
| `posting_policies` | platform/account/destination, IANA zone, cap, interval, version, reservation rule | release; unique destination/policy version/release | Posting configuration / audit |
| `post_requests` | approved hashes/destination/mode, expiry, status, publication identity, row version | review/package/render; `UNIQUE(review_request_id)`, `UNIQUE(publication_identity)` | Dashboard / audit |
| `post_records` | eligible/expiry, status, claim envelope, external ID nullable, error, row version | `UNIQUE(post_request_id)` | Posting Agent / audit |
| `post_attempts` | ordinal, status, error, final-request marker, start/end | post record; `UNIQUE(post_record_id, attempt_number)` | Posting Agent / audit |
| `publication_resources` | role, asset ordinal nullable, remote/object ID, safe metadata, status | post attempt; unique provider resource identity where non-null | Adapter / audit |
| `delivery_cleanup_tasks` | object key, status, claim envelope, safe error | publication resource; one active cleanup task per resource/object | Cleanup / artifact |
| `reconciliation_requests` | reason, status, claim envelope, row version | post record; one active request per record | Reconciliation / audit |
| `reconciliation_checks` | provider query/matching version, safe response hash/summary, candidate IDs, outcome | reconciliation request | Reconciliation / audit |
| `human_reconciliation_decisions` | actor, exact evidence/check reference, outcome, note | reconciliation request and check | Dashboard / audit |
| `human_command_receipts` | client command ID, kind, actor/session, target/version, payload hash, result references | target references nullable by command; `UNIQUE(client_command_id)` | Dashboard / audit |
| `model_invocations` | phase, entity FKs, ordinal, request/schema/hash, provider ID/response hash, usage/cost/outcome/error/start/end | applicable entity FKs nullable; unique phase/entity/ordinal | Gemini boundary / audit |
| `gemini_budget_reservations` | UTC day, worst-case/settled cost, status | invocation or claim; one active reservation per invocation/claim | Gemini boundary / audit |
| `worker_heartbeats` | worker type/instance, started/last seen, state, claim reference nullable, build, summary | `UNIQUE(worker_type, instance_id)` | Runtime / replaceable current-health row |
| `worker_runs` | worker/instance, claimed entity, start/end/status, summary/error | claim target reference | Runtime / audit |
| `storage_samples` | free/total and component byte counts, threshold state, safe summary | none | Storage Monitor / audit |
| `maintenance_runs` | kind, start/end/status, counts, backup identity/checksum nullable, safe error | none | Maintenance / audit |
| `recovery_requests` | target kind/ID, failure fingerprint/reason, safety decision, status, claim envelope, replacement reference nullable | one target request while nonterminal; command receipt | Recovery Worker / audit |
| `retention_runs` | policy/cutoff, start/end/status, per-table counts and hashes, safe error | none | Maintenance / audit |
| `determination_routes` | domain, fit/disposition/reason, angle, evidence, output assessments, reuse FK nullable | decision; unique decision/domain | Determination / audit |
| `canonical_contents` | common envelope/domain payload, angle and source support, validation, canonical hash | unique content job and generation run | Pipeline Runner / audit |
| `output_requests` | canonical hash, frozen destination/format/versions/input, output identity | canonical content and route/reuse link; unique output identity | Generation/rework finalization / audit |
| `adaptation_runs` | run number, frozen input, body/metadata checkpoint, claim envelope/status | output request; unique request/run number; one active run/request | Adaptation Worker / audit |
| `output_bindings` | domain, destination, format, output contract, renderer compatibility, enabled | domain capability, social destination, release; unique domain/destination/format/version/release | Configuration / audit |
| `social_destinations` | stable account key, platform, provider identity, safe secret refs | configuration release; unique platform/account/release | Configuration / audit |
| `domain_angle_reservations` | normalized angle identity, current accepted work pointer, revision permission audit | route/job; one current guard per angle, retained history | Determination / audit |
| `canonical_reuse_links` | creative equality fingerprint, reuse reason/scope | new route/revision and prior canonical content | Determination/rework / audit |
| `publication_steps` | optional-thread ordinal, immutable approved text/asset references, per-step marker, remote ID/outcome | post record and originating attempt; unique record/ordinal | Posting / audit; draft, thread mode disabled |
| `schema_migrations` | version, name, checksum, applied time | `UNIQUE(version)`, `UNIQUE(checksum)` | Migration system / audit |

The legacy detector table names in the first group are target retained evidence
tables, not permission to carry forward undocumented legacy columns. An adapter
may put source-specific opaque fields only in the named validated `payload_json`
or snapshot column; it must not add unreviewed schema at runtime.

### Claimable-record transition matrix

Every row below requires a short transaction and the current expected status.
`claim` additionally requires eligibility time, no live competing lease, the
configured attempt limit, and an incremented fencing `claim_version`; all
finalization requires matching owner and fencing version. Only the named owner
may make the transition. "Recovery" means a runtime service after lease expiry,
not an arbitrary worker action.

| Record | Allowed lifecycle | Actor and additional preconditions |
| --- | --- | --- |
| `source_collection_attempts` | `pending/retry_wait → claimed → running → completed/retry_wait/failed/cancelled` | Trend Source Collector; source instance is enabled and the scheduled time is due. Safe retry reuses this attempt only; a completed provider response is never re-requested. |
| `scout_evaluation_runs` | `pending/retry_wait → claimed → running → completed/retry_wait/failed/cancelled` | Trend Scout + Shortlist; its fixed slot/configuration release exists. It makes no provider call. Completion atomically persists all score snapshots/candidates and any permitted shortlist selections. |
| `intake_requests` | `pending/retry_wait → claimed → completed/needs_clarification/retry_wait/failed/cancelled` | Idea Intake; thread is open. `completed` atomically creates one revision and determination request. |
| `determination_requests` | `pending/retry_wait → claimed → completed/retry_wait/failed/cancelled` | Determination; revision/thread valid. `completed` atomically writes one decision/five routes and one job/run per selected route. |
| `generation_runs` | `waiting_capacity → pending → claimed → running → succeeded/retry_wait/failed/cancelled`; `retry_wait → claimed` | Production Admission Gate promotes only with an active capacity reservation; Pipeline Runner needs that reservation plus immutable parent job/recipe and capability snapshot. `succeeded` atomically creates canonical content plus all frozen output requests/adaptation runs. |
| `adaptation_runs` | `waiting_capacity → pending → claimed → running → succeeded/retry_wait/failed/cancelled`; `retry_wait → claimed` | Admission plus Adaptation Worker; frozen canonical/output input and reservations required; success atomically creates one package and first render run. |
| `render_runs` | `pending/retry_wait → claimed → running → succeeded/retry_wait/failed/cancelled` | Visual Renderer; package/hash/spec validate. Safe retry returns the same run to `retry_wait`; only audited terminal rerender/recovery creates another run number. `succeeded` atomically freezes manifest/assets and creates review availability. |
| `post_records` | `pending/retry_wait → claimed → publishing → published/retry_wait/failed/publication_unknown/cancelled/expired` | Posting Agent; request is approved/unexpired, exact review binding and policy validate. Retry only before final provider request. `publication_unknown` follows any possibly transmitted final request. |
| `delivery_cleanup_tasks` | `pending/retry_wait → claimed → succeeded/retry_wait/failed/cancelled` | Cleanup Worker; object may be safely deleted. Success records deletion but never deletes audit lineage. |
| `reconciliation_requests` | `pending/retry_wait → claimed → resolved/needs_human/retry_wait/failed/cancelled` | Reconciliation Worker; parent is `publication_unknown`. It may append checks, never publish; only an allowed unambiguous outcome resolves automatically. |
| `recovery_requests` | `pending/retry_wait → claimed → completed/rejected/retry_wait/failed/cancelled` | Recovery Worker; source is a terminal eligible local record and no ambiguous external effect exists. `completed` atomically creates a new linked numbered local run/task. |

`review_requests`, `post_requests`, `thread_messages`, `brief_revisions`,
decisions, routes, canonical content, output requests, packages, assets, attempts,
resources, checks, and command receipts
are not claimable. Their explicitly documented human or worker creation and
terminal state transitions are append-only audit actions. A `PostRequest` may
transition `approved → cancelled/expired/fulfilled` only by the documented
dashboard, expiry, or confirmed-publication transaction respectively.

### Non-claimable mutable-record transitions

These records do not use worker claims. Every state-changing command matches
the expected `row_version`, performs the listed side effects atomically, and
increments the resulting version. Immutable snapshots (`thread_messages`,
revisions, decisions, completed checks, reconciliation decisions and receipts)
are created once and never state-mutated. Attempts, publication resources,
model invocations and execution audit rows instead have immutable identity/input
and only the explicitly named lifecycle/completion fields may change through
their owning fenced transaction. Terminal outcomes are not reset or overwritten.
Append-only audit means preserving each attempt's identity and evidence, not
forbidding its documented start-to-completion transition.

| Record | Closed status set and legal transitions | Actor / required atomic side effect |
| --- | --- | --- |
| `content_threads` | `open → closed`, `open → cancelled`, `closed → open`; `cancelled` is terminal | Dashboard; closure requires no unfinished descendants, cancellation applies only permitted safe descendant cancellations, and collision closure records `coverage_collision_merged`. |
| `review_requests` | `awaiting_review → approved/changes_requested/rejected/invalidated/expired/cancelled`; every destination outcome is terminal | Dashboard approval creates one Post Request/Record; changes append a message plus Intake Request; invalidation/expiry/cancellation never alter package or assets. |
| `post_requests` | `approved → cancelled/expired/fulfilled`; all destinations terminal | Dashboard cancels only before final publication marker; expiry atomically expires Post Record; confirmed publication fulfills it. |
| `post_records` | Its worker-owned lifecycle is in the claimable matrix; dashboard may make pre-final `pending/retry_wait/claimed/publishing` work `cancelled` with its request | Dashboard or Posting Agent; cancellation transaction rechecks no final marker, cancels the active attempt, creates staged-R2 cleanup tasks/retained-container audit, and increments request/record row versions. |
| `reconciliation_requests` | Its worker-owned lifecycle is in the claimable matrix; human action may append one immutable decision against a completed check | Dashboard; decision exactly names its evidence and does not reset/retry the Post Record. |
| `configuration_activations` | `active → superseded`; a new activation is created as `active` | Configuration Operator; atomically validates/materializes a release, supersedes prior active scope pointer, creates new active pointer, and records command receipt. Release rows are immutable `validated`/`rejected`. |

Use primary/foreign keys plus the named unique constraints. Required polling and
reporting indexes include:

- `detection_source_instances(enabled, source_kind, stable_id)`;
- `source_collection_attempts(status, scheduled_for, next_attempt_at)` and unique source/schedule/configuration key;
- `scout_evaluation_runs(status, evaluation_slot_start, next_attempt_at)` and unique slot/configuration key;
- `trend_candidates(status, cooldown_until, evidence_fingerprint)` and cluster
  membership;
- `thread_evidence_events(thread_id, created_at)` and current fingerprint;
- unique trend-thread coverage identity;
- `pipeline_capabilities(enabled, pipeline_id)` and output binding/destination lookup;
- unique decision/domain route, selected route/job, canonical content identity, and output identity;
- `adaptation_runs(status, next_attempt_at, created_at)` and one-active-run-per-output-request;
- `production_capacity_reservations(policy_id, status, acquired_at)` and active-slot count;
- `generation_runs(status, next_attempt_at, created_at)` including `waiting_capacity` ordering;
- `intake_requests(status, next_attempt_at, created_at)`;
- `determination_requests(status, created_at)`;
- `content_jobs(priority DESC, created_at)` and unique content identity;
- one-active-run-per-job;
- `render_runs(status, next_attempt_at, created_at)` and one-active-run-per-package;
- `review_requests(status, created_at)`;
- unique post-request publication identity;
- `post_records(status, eligible_at, next_attempt_at)`;
- `reconciliation_requests(status, next_attempt_at, created_at)`;
- `delivery_cleanup_tasks(status, lease_expires_at)`;
- `thread_messages(thread_id, sequence_number)`;
- `brief_revisions(thread_id, revision_number)`;
- `model_invocations(thread_id, revision_id, created_at)`;
- `model_invocations(generation_run_id, created_at)`; and
- `gemini_budget_reservations(accounting_day, status)`; and
- unique `human_command_receipts(client_command_id)`.

Service methods also validate parent state: review requires complete verified
assets; post request requires approval; post attempt requires a claimable
record; a resource belongs to its creating attempt.

## Migration and cutover

V1–v4 are implemented as immutable forward SQL; never modify their checksums or
table definitions. Decision 035 authorizes a fresh normalized Option B database,
not an in-place identity conversion or a reset of the legacy database. V4 is
explicitly refused unless that database has active `canonicalization_v2` and
`attention_v2`. Future capacity/reuse/recovery/retention records still require
new reviewed migrations. Preserve every selected thread, Intake handoff,
creative record, approval, attempt, and detection evidence.

Migrate legacy `o2_english_instagram` lineage as legacy evidence, not as a second
active domain ID. The new domain is `english`; its old account remains a
separate Instagram destination. Do not manufacture platform-neutral canonical
content by stripping caption/slide fields from an old package, or claim a new
domain-generation success occurred. Preserve legacy package/review/publication
lineage under explicit legacy versions until a reviewed migration maps it
without invented approvals or paid calls.

Cutover requires backup, supported-version and FK checks, paused affected
workers, atomic migrations, row/hash/lineage reconciliation, typed boundary
tests, and rollback-by-restore verification. Unpublished legacy work remains on
migration hold pending fresh valid review; confirmed/uncertain history is
never automatically republished. Old reviewed 1080×1920 assets are not silently
converted to the new Instagram output profile.

No worker or dashboard start path resets or silently accepts an incompatible
database.
