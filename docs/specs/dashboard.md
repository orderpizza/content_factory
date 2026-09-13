# Dashboard and HAI Specification

**Document role:** Tier 2 target design contract. It defines the required
Human–Agent Interface; verify implementation conformance from code and tests.
**Owner:** Dashboard read model, narrow human commands, health presentation,
and operational visibility.
**Read this for:** Dashboard/UI work, human idea/review flows, health display,
alerts, or reporting. Read [the system guide](../system.md) first and the
[data model](data-model.md) before changing persisted records.

The dashboard is Content Factory’s sole operational visibility surface. It is
utilitarian by design: complete, fresh, auditable visibility matters more than
visual polish. Every material record must be traceable from source evidence to
external publication.

## Local access and command trust

The POC dashboard is a continuously available local service on the Mac Mini.
It binds only to the loopback interfaces; it is not reachable from the LAN or
the public internet. Opening the local dashboard is the POC's operator-access
boundary. A future non-loopback deployment requires an explicit authentication
and authorization design before any human command is enabled.

The initial POC has one durable dashboard actor, `local_owner`. There is no
user-login or multi-user account system. The dashboard may maintain a
short-lived local browser session solely to issue a same-origin anti-CSRF token;
that session is not the actor identity.

Every state-changing command against an existing target requires that anti-CSRF
token, a unique client-generated command ID, and the displayed target
`row_version`. The
command receipt makes a duplicate click, browser retry, or refresh return the
original result rather than create another record. This protection adds no
confirmation step: one click on **Post now** immediately submits its durable
authorization command.

The dashboard exposes all non-secret operational state and safe diagnostics
needed to understand the system. It never displays environment values, access
tokens, authorization headers, credentials, signed URLs, or unredacted provider
payloads. Raw JSON and errors use the shared redaction rules in
[Reliability and safety](reliability.md).

Idea and change-request inputs display a concise warning: **Do not paste
credentials, tokens, private URLs, or personal data.** The dashboard rejects
input above the canonical operational-data limit before creating a command.
It never shows authoritative message text in generic error, worker, or raw
provider-diagnostic views.

## Boundary

The dashboard reads its reporting state from SQLite and writes only these
types of human command:

1. atomically open/continue a `ContentThread`, append its human message, and
   create the pending `IntakeRequest`;
2. decide `post_now`, `request_changes`, or `reject` on an awaiting review
   request;
3. cancel an eligible `PostRecord` before its final publication request;
4. create a read-only `ReconciliationRequest` for terminal
   `publication_unknown`; and
5. record a human reconciliation decision against the exact completed checks;
6. close, reopen, or cancel a `ContentThread` under its lifecycle
   preconditions; and
7. request a capability re-evaluation for an eligible blocked Determination
   decision; and
8. open a permitted fresh review cycle for an unchanged expired or auditable
   `not_published_cancel` item.
9. request a permitted terminal-local-work recovery; the request is durable
   work for the Recovery Worker, never a dashboard retry or reset.

Commands validate the displayed target `row_version`, atomically increment it
when they change that target, and write their narrowly defined records in a
short SQLite transaction. They never call Gemini, render assets,
start/retry a worker, stage R2 media, or call a social API. All reporting opens
SQLite read-only and never initializes, migrates, repairs, or resets it.

From the user’s perspective, **Post now** posts the selected content. The
dashboard records an immediate, explicit `PostRequest`; the Posting Agent
claims its policy-eligible `PostRecord` on its normal polling cycle and makes
the selected Instagram or X API call. This
durable handoff provides an audit trail, prevents duplicate clicks from causing
duplicate publication, and keeps the dashboard free of delivery logic.

### Human-action rules

- **New idea / revise:** opens or continues a thread; never edits a historical
  revision, job, package, review, or post. The message and Intake request are
  one transaction and duplicate submission uses a command idempotency key.
- **Post now:** approves the exact package/render hashes and atomically creates
  one `delivery_mode=immediate` Post Request plus its initial Post Record. Its
  actual eligibility follows `posting_policy_v1`; the UI shows **Posts now** or
  the exact next policy-calculated eligible account-local time, daily-cap/interval reason, and
  record expiry. The click submits immediately without a confirmation dialog.
  **Reject** ends that review request without delivery. The initial POC
  deliberately has no human scheduling action or requested delivery time.
- **Request changes:** marks the review `changes_requested` and atomically
  appends the change note as a thread message plus a pending Intake request for
  a new revision. It never edits the reviewed package.
- **Close / reopen thread:** closing is available only when no unfinished
  descendant work remains; it archives the thread without changing history.
  Reopen is explicit and changes only the closed thread back to `open`; the
  next human message creates the next Intake request in the usual way.
- **Cancel thread:** cancels permitted unfinished descendants and invalidates
  an awaiting review or a pre-final-request delivery authorization. It is not
  permitted to alter a delivery whose final publication request may have been
  sent; that descendant remains published or uncertain while other unfinished
  descendants may be cancelled. It never removes historical creative, audit,
  published, or uncertain-publication records.
- **Re-evaluate route:** is available for blocked routes in the current decision only when the
  thread is open, the decision is current, no competing request is active, and
  the safe routing-input fingerprint changed. It creates one auditable
  `capability_recheck` revision/request; it neither sends a chat message nor
  calls Gemini from the dashboard.
- **Cancel delivery:** is available only before an attempt sends the final
  publication request. It cancels the eligible Post Record and its
  authorization consistently and never deletes creative.
- **Publication unknown:** has no retry/publish control. The dashboard shows
  the audit and reconciliation result. A new publication needs a new explicit
  approval.
- **Recover local work:** is available only for a terminal `failed` Generation
  Run, Adaptation Run, Render Run, or Cleanup Task whose recorded failure has no ambiguous
  external side effect. It records the displayed failure ID, reason, actor,
  command ID, and row version. It never resets that record, never offers a
  recovery control for `publication_unknown`, and never retries delivery.

## Information architecture

Lists default to active, failed, stale, and blocked records first, then newest
completed work. Every view supports time, status, pipeline, account, source,
and thread filters plus ID/full-text search. Every row opens a detail view with
safe raw JSON, timestamps, parent/child links, and a full audit timeline.

The current detection dashboard starts with a title-free compact operator
surface, rather than a `Trend Opportunities` header or configuration summary.
Its first row places the live **Ingestion feed** beside **Opportunities** across
the full viewport width. The feed shows newly persisted normalized observations;
the opportunities list is limited to candidates that passed shortlist selection
and created the next `ContentThread` / `IntakeRequest` handoff. This makes the
incoming signal and the work handed downstream visible together.

The compact detection slice uses `YYYY-MM-DDTHH:MM:SS` for all persisted UTC
timestamps, without fractional seconds or a rendered timezone suffix. It shows
filtering, source health, Scout evaluations, worker state, and recent worker
runs below the first row. The full future candidate/thread trace remains
planned for the wider HAI navigation and must preserve source evidence,
score/formula version and rank, shortlist outcome/reason, coverage identity,
linked thread/revision, determination outcome, per-domain angles/dispositions,
child destination bindings, and downstream outcomes.

The primary navigation is: **Trend Opportunities**, **Ideas and Threads**,
**Review Queue**, **Pipeline Portfolio**, **Worker Operations**, **Delivery and
Reconciliation**, **Costs and Audit**, and **System Storage**. These are views
over the same SQLite record model, not separate subsystem stores. A global
pipeline/account selector lists only currently enabled capabilities by default,
but an **include disabled/historical** switch exposes retired configuration and
its history. Portfolio rows are one per domain with expandable platform/account/format
children. Domain rows show canonical generation state/cost; output children show
adaptation/render/review/delivery state/cost. Canonical cost is counted once; an error in
any row remains visible even when a global aggregate is healthy. Pagination,
search, and filter chips are required rather than a fixed layout assumption, so
the design accommodates a larger pipeline portfolio without hiding it.

| Area | Required visibility | Primary question |
| --- | --- | --- |
| System overview | Schema version, DB path/size, local disk headroom, active configuration release/fingerprint, worker freshness, active/stale/failed counts, configured domain/destination portfolio, safe delivery-configuration health including account/token state, today’s posts, review count, Gemini totals | Is the system alive, safe, and progressing? |
| Worker health | Current `worker_heartbeats`, substantive `worker_runs`, claims, duration, last success/failure, lease expiry, backlog, cadence, next expected run, stale reason, capability-readiness monitor state | Which component needs attention? |
| Detection | Enabled source-instance registry/configuration version, health/degradation, observations/snapshots, candidates, score inputs/fingerprint/formula version, cluster members, shortlist policy/rank/budget, consumed/not-recommended/cooldown/evidence change | Why was an opportunity selected, deferred, or blocked? |
| Threads and intake | New-idea entry, origin, complete conversation, Intake requests/claims, clarification state, revisions/parents, source evidence/events, linked work | What did I ask for and what changed? |
| Determination | Requests/leases, frozen input/catalog, aggregate outcome plus five route fit/disposition/reason rows, selected angles and distinct reader value, output readiness, duplicate/reuse links, model usage, all resulting jobs | Why did each domain respond, skip, reuse, or block? |
| Production/content | Domain jobs/GenerationRuns, canonical content/claims/sources/hash, output requests/AdaptationRuns, native package copy/metadata, versioned checkpoints and scoped rework | What was generated once, adapted per destination, or reused? |
| Rendering | Runs/leases, renderer/template versions, manifest verification, ordered preview/assets/dimensions/checksums, failure/recovery | Are exact assets ready and trustworthy? |
| Review queue | Canonical final delivery-asset preview, content/manifest/asset hashes, caption/tags/hashtags, source/brief/decision context, package identity, age/freshness, Post now/reject/request-changes actions | What exact immutable output is ready for my decision? |
| Delivery | Requests, cadence, records, attempts, typed errors, final-request boundary, external IDs, R2 cleanup, unknown outcomes, reconciliation | What is queued, published, uncertain, or awaiting cleanup? |
| Costs/audit/search | Model attempts/tokens/cost, worker errors, migrations, deduplication decisions, full audit search | What happened and what did it cost? |
| Production capacity | Policy/version, active and available unreviewed slots, slot holders/release reason, waiting Generation/Adaptation Runs, origin-priority order, estimated wait age | Why is a job waiting before it spends model budget? |
| System storage | Latest storage sample/threshold state, free space, SQLite/WAL/artifact/backup sizes, latest backup, last restore verification, retention/quarantine/cleanup counts | Can the Mac Mini safely continue to create and preserve work? |
| Recovery | Eligible terminal local failures, Recovery Requests, safety rejection reason, linked replacement run/task, and terminal outcome | What can safely be resumed without rewriting history or repeating publication? |
| Capability readiness | Typed domain or output-binding readiness, platform/destination/account, release fingerprint, checked/valid-until times, ready/degraded/blocked/unknown state, token-expiry warning, renderer/profile/media-domain/provider check results, safe blocking reasons | Can Determination or Posting safely use this route now? |

## Navigation and traces

The overview uses this vertical stage summary:

```text
Sources / Scout
  → Candidates / Threads
  → Intake / Determination
  → Domain Routes / Angles / Canonical Content
  → Output Requests / Adapted Packages
  → Render Runs / Review Queue
  → Post Requests / Publication / Cleanup
```

Each stage displays `active`, `waiting`, `completed`, `failed`, `stale`, and
`blocked_by_human` counts. Selecting a count applies that filter to the owning
view. A trace view starts from any candidate, thread, revision, job, package,
review request, post request, or post record and displays every linked record
in chronological order. The canonical trace order is source instance/observation
→ snapshot/cluster/candidate → evidence event or thread → messages/Intake
request → Brief Revision → Determination request/decision → domain route/angle
→ Content Job/GenerationRun → CanonicalContent → OutputRequest/AdaptationRun
→ ContentPackage → Render Run/assets → Review Request → Post Request/
Record/Attempt → publication resources, cleanup, and reconciliation. Missing
downstream links are shown as an explicit current stopping state, not blank
space that the operator must interpret.

### Review queue

This is the priority view. Order by oldest awaiting review, then descending
priority; filter by pipeline/account. A review card shows the final local
delivery assets—not a regenerated preview or R2 copy—alongside all metadata,
sources, destination, content hash, manifest hash, asset hashes, identity,
freshness, and warnings. The command includes the displayed Review Request
`row_version`;
approval revalidates every binding in its transaction. The card identifies the
exact Instagram or X destination and warns that delivery is public and may be
irreversible. Show X's complete post text or ordered thread text, not only its
image. One platform's approval never approves its sibling. The initial POC has no scheduling
control: **Post now** is the only delivery authorization action and the active
posting policy determines its earliest eligible time.

The queue separately exposes `awaiting_review`, `expired`, `invalidated`, and
other terminal review outcomes. An unchanged expired item may display **Open a
new review cycle** only when the freshness policy permits it; the action
revalidates the exact bytes/hashes/destination and creates a distinct cycle
whose 14-day expiry starts at the new request's creation. It never revives the
old approval. A package
with a confirmed publication identity never exposes that action. A resolved
`not_published_cancel` outcome may also make the exact package eligible for a
new cycle, with the reconciliation evidence linked on the card.

### Delivery view

Keep human intent and external state distinct:

- `PostRequest`: what the human approved and when.
- `PostRecord`: what the delivery worker did.
- `PostAttempt`: which delivery stage was reached.
- Optional `PublicationStep`: the exact confirmed prefix and uncertain/unsent
  suffix for a thread; unavailable until its versioned safety contract is enabled.
- `PublicationResource`: which remote object/container exists.
- `DeliveryCleanupTask`: whether transient media is still retained.
- `ReconciliationRequest` / `ReconciliationCheck`: what read-only
  investigation was authorized and observed.

No control retries a failure. Safe retries are worker policy. The only human
options are a new revision, a new approval, a pre-publication cancellation, or
reconciliation of an uncertain publication.

## Phase 1 routing-quality workspace

Trend Opportunities expands one candidate/thread into five domain assessments,
then canonical results and their Instagram/X branches. Preserve zero-output
decisions and explicit stopping reasons. A domain filter is distinct from an
account/platform filter; an unconfigured account is not a missing domain.

Show one-pipeline selection, multi-pipeline selection, intentional weak-fit
skips, whole-trend rejection, dependency blockers, reuse, and technical failures
separately. Do not optimize the UI around producing five packages per trend.
Top-level candidate/decision counts use distinct IDs; expanding two destinations
does not double the number of evaluated trends or canonical generations.

For operator-reviewed routing fixtures, display expected acceptable domains/
angles/skip reasons versus actual results, fixture/policy/model version,
false-positive forced routes, missed useful routes, duplicate-angle warnings,
and cost per evaluated trend/canonical/output. Qualitative angle/source-support
review is required alongside counts. Do not fabricate quality percentages,
revenue, or monetization success from publication volume.

A change request records whether it targets one output, a domain's canonical
content, or the common brief. Scope is visible before paid work; already
approved/in-flight siblings remain untouched unless an explicit permitted
cancellation wins. A blocked sibling can be rechecked without regenerating
completed routes under the Intake preconditions.

The current dashboard implements the human boundary for the bounded production
slice. It renders Detection/workflow state in one read-only transaction, while a
separate loopback POST executes only new-idea, thread-reply, preview
accept/reject/request-changes, exact production Post now, eligible pre-final
cancel, and explicit reconciliation request/resolution commands through
`WorkflowStore`. Commands validate the process CSRF token, command ID, and
applicable displayed row version. It serves only currently hash-valid manifested
PNG/JPEG files below the artifact root and shows the exact review text/images.
Editorial acceptance alone creates no PostRequest; the separately displayed Post
now button requires a production-ready package and current destination readiness.
Messages appear once per thread. Recovery requests, configuration editing,
routing replay/quality evaluation, and the full portfolio/lease controls above
remain unimplemented. Opportunity counts/list rows remain one per selected
candidate, independent of its number of Intake requests.
See [current implementation](../current-state.md) for operational limitations.

The current read view pauses automatic refresh while hidden and refreshes on
return, using a fixed CSP-hashed script. Editing a filter pauses automatic
reload to preserve input. Detection worker heartbeat age is labeled separately
from its last reported state using the runtime's 20/45-minute thresholds. The
production summary shows the latest storage state, conservative current-UTC-day
Gemini budget usage/warning, destination readiness/expiry, delivery states, and
cleanup counts. Full per-worker lease/backlog/capacity health and alerting remain
target requirements.

Each HTTP refresh verifies schema version and migration-ledger checksums inside
its consistent read snapshot. It does not rescan every foreign key on every
10-second refresh. Explicit setup and normal worker/store startup retain full
foreign-key validation; lightweight reporting is not an integrity-check verdict.

## Freshness and stale-state presentation

Every worker updates its current `worker_heartbeats` row on each poll and
creates `worker_runs` only for substantive claimed work. The dashboard
calculates freshness from that heartbeat, last substantive success, active
lease, and the configured cadence—not a browser or in-memory flag. The worker schedule, poll behavior, and worker-specific
fresh/warn/stale thresholds are owned by the
[worker runtime specification](runtime.md).

| Component | Refresh behavior | Fresh / warn / stale |
| --- | --- | --- |
| Dashboard, visible | 10 seconds | One consistent local SQLite snapshot; no external call | ≤20 s / >20 s / >60 s or read failure |
| Dashboard, hidden | No polling; refresh on return | Avoid needless local load | Shows prior snapshot age |

The dashboard also displays the Storage Monitor sample at its five-minute
cadence, backup age, restore-verification age, and the active shared claim gate
(`normal`, `storage_warning`, `storage_critical`, or `read_only_emergency`). It
does not declare a worker broken merely because a claim is deliberately blocked
by that gate.

Do not call an active leased item stale before its `lease_expires_at`. After
expiry, label the individual record **stale claim**, separately from ordinary
backlog. `publication_unknown` is terminal and high visibility, never an item
for automatic stale recovery.

The dashboard’s 10-second visible refresh is intentionally faster than workers
so human state changes appear promptly without API cost. Manual browser refresh
is the same read-only operation.

## Alerts and visual language

- **Green:** worker/work is within its fresh window.
- **Amber:** waiting on review, degraded source, due soon, lease nearing expiry,
  or late cadence that is not stale.
- **Red:** failed worker/item, stale claim, invalid manifest, unsafe config,
  cleanup failure beyond policy, or `publication_unknown`.
- **Gray:** intentionally disabled or no work exists.

Never mask errors with a green aggregate. Every amber/red count links to the
specific records with safe error summary, last success, owning worker, and the
only allowed next action.

## Acceptance requirements

Implementation and boundary tests must demonstrate that:

- reporting connections cannot initialize, migrate, repair, or mutate SQLite;
- each human command validates target version and a unique command idempotency
  key, and duplicate submission returns the original result;
- message + Intake-request creation and approval + request/record creation are
  atomic;
- review shows and approves the exact canonical delivery assets and stored
  hashes, and stale/mismatched output cannot be approved;
- cancellation racing a worker claim/final-request marker cannot cancel or
  duplicate an external publication;
- no dashboard action directly invokes Gemini, a renderer, a worker, R2, or a
  social API; and
- worker freshness and publication uncertainty remain correct after browser
  close/reopen and worker restart.
