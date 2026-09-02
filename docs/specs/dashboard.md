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

Every state-changing command requires that anti-CSRF token, a unique
client-generated command ID, and the displayed target-record version. The
command receipt makes a duplicate click, browser retry, or refresh return the
original result rather than create another record. This protection adds no
confirmation step: one click on **Post now** immediately submits its durable
authorization command.

The dashboard exposes all non-secret operational state and safe diagnostics
needed to understand the system. It never displays environment values, access
tokens, authorization headers, credentials, signed URLs, or unredacted provider
payloads. Raw JSON and errors use the shared redaction rules in
[Reliability and safety](reliability.md).

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
5. record a human reconciliation decision against the exact completed checks.

Commands validate the displayed record version and write their narrowly defined
records in a short SQLite transaction. They never call Gemini, render assets,
start/retry a worker, stage R2 media, or call a social API. All reporting opens
SQLite read-only and never initializes, migrates, repairs, or resets it.

From the user’s perspective, **Post now** posts the selected content. The
dashboard records an immediate, explicit `PostRequest`; the Posting Agent
claims its policy-eligible `PostRecord` on its normal polling cycle and makes
the Instagram API call. This
durable handoff provides an audit trail, prevents duplicate clicks from causing
duplicate publication, and keeps the dashboard free of delivery logic.

### Human-action rules

- **New idea / revise:** opens or continues a thread; never edits a historical
  revision, job, package, review, or post. The message and Intake request are
  one transaction and duplicate submission uses a command idempotency key.
- **Post now:** approves the exact package/render hashes and atomically creates
  one `delivery_mode=immediate` Post Request plus its initial Post Record. Its
  actual eligibility follows the active posting policy; the UI shows whether
  that means now, the next compliant slot, or blocked configuration when the
  action is available. The click submits immediately without a confirmation
  dialog. **Reject** ends that review request without delivery. The initial POC
  deliberately has no human scheduling action or requested delivery time.
- **Request changes:** marks the review `changes_requested` and atomically
  appends the change note as a thread message plus a pending Intake request for
  a new revision. It never edits the reviewed package.
- **Cancel delivery:** is available only before an attempt sends the final
  publication request. It cancels the eligible Post Record and its
  authorization consistently and never deletes creative.
- **Publication unknown:** has no retry/publish control. The dashboard shows
  the audit and reconciliation result. A new publication needs a new explicit
  approval.

## Information architecture

Lists default to active, failed, stale, and blocked records first, then newest
completed work. Every view supports time, status, pipeline, account, source,
and thread filters plus ID/full-text search. Every row opens a detail view with
safe raw JSON, timestamps, parent/child links, and a full audit timeline.

| Area | Required visibility | Primary question |
| --- | --- | --- |
| System overview | Schema version, DB path/size, local disk headroom, worker freshness, active/stale/failed counts, O2 account, today’s posts, review count, Gemini totals | Is the system alive, safe, and progressing? |
| Worker health | Current `worker_heartbeats`, substantive `worker_runs`, claims, duration, last success/failure, lease expiry, backlog, cadence, next expected run, stale reason | Which component needs attention? |
| Detection | Enabled source-instance registry/configuration version, health/degradation, observations/snapshots, candidates, score inputs/fingerprint/formula version, cluster members, shortlist policy/rank/budget, consumed/not-recommended/cooldown/evidence change | Why was an opportunity selected, deferred, or blocked? |
| Threads and intake | New-idea entry, origin, complete conversation, Intake requests/claims, clarification state, revisions/parents, source evidence/events, linked work | What did I ask for and what changed? |
| Determination | Requests/leases, frozen input, capability snapshot, decision outcome/reasoning/alternatives/identities, Gemini usage, resulting job when accepted | Why did the system choose/refuse a route? |
| Production/content | Jobs/leases, recipe, package creative/caption/tags/hashtags/citations, identities/hashes, contract/model versions, validation | What was generated and is it valid? |
| Rendering | Runs/leases, renderer/template versions, manifest verification, ordered preview/assets/dimensions/checksums, failure/recovery | Are exact assets ready and trustworthy? |
| Review queue | Canonical final delivery-asset preview, content/manifest/asset hashes, caption/tags/hashtags, source/brief/decision context, package identity, age/freshness, Post now/reject/request-changes actions | What exact immutable output is ready for my decision? |
| Delivery | Requests, cadence, records, attempts, typed errors, final-request boundary, external IDs, R2 cleanup, unknown outcomes, reconciliation | What is queued, published, uncertain, or awaiting cleanup? |
| Costs/audit/search | Model attempts/tokens/cost, worker errors, migrations, deduplication decisions, full audit search | What happened and what did it cost? |

## Navigation and traces

The overview uses this vertical stage summary:

```text
Sources / Scout
  → Candidates / Threads
  → Intake / Determination
  → Content Jobs / Packages
  → Render Runs / Review Queue
  → Post Requests / Publication / Cleanup
```

Each stage displays `active`, `waiting`, `completed`, `failed`, `stale`, and
`blocked_by_human` counts. Selecting a count applies that filter to the owning
view. A trace view starts from any candidate, thread, revision, job, package,
review request, post request, or post record and displays every linked record
in chronological order.

### Review queue

This is the priority view. Order by oldest awaiting review, then descending
priority; filter by pipeline/account. A review card shows the final local
delivery assets—not a regenerated preview or R2 copy—alongside all metadata,
sources, destination, content hash, manifest hash, asset hashes, identity,
freshness, and warnings. The command includes the displayed record version;
approval revalidates every binding in its transaction. Approval confirms that
Instagram is public and irreversible. The initial POC has no scheduling
control: **Post now** is the only delivery authorization action and the active
posting policy determines its earliest eligible time.

### Delivery view

Keep human intent and external state distinct:

- `PostRequest`: what the human approved and when.
- `PostRecord`: what the delivery worker did.
- `PostAttempt`: which delivery stage was reached.
- `PublicationResource`: which remote object/container exists.
- `DeliveryCleanupTask`: whether transient media is still retained.
- `ReconciliationRequest` / `ReconciliationCheck`: what read-only
  investigation was authorized and observed.

No control retries a failure. Safe retries are worker policy. The only human
options are a new revision, a new approval, a pre-publication cancellation, or
reconciliation of an uncertain publication.

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
