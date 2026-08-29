# Dashboard and HAI Specification

**Status:** Approved target design; current dashboard is read-only and partial.
**Owner:** Dashboard read model, narrow human commands, worker freshness, and
operational visibility.
**Read this for:** Dashboard/UI work, human idea/review flows, worker cadence,
alerts, or reporting. Read [the system guide](../system.md) first and the
[data model](data-model.md) before changing persisted records.

The dashboard is Content Factory’s sole operational visibility surface. It is
utilitarian by design: complete, fresh, auditable visibility matters more than
visual polish. Every material record must be traceable from source evidence to
external publication.

## Boundary

The target dashboard has a read model over SQLite and only four human command
paths:

1. append a human message to a `ContentThread` (new idea or revision);
2. decide `approve_now`, `schedule`, or `reject` on an awaiting review request;
3. cancel an unclaimed/scheduled `PostRequest` before its final publication
   request; and
4. record a reconciliation decision for terminal `publication_unknown` after a
   read-only external investigation.

Commands validate the displayed record version and write their narrowly defined
records in a short SQLite transaction. They never call Gemini, render assets,
start/retry a worker, stage R2 media, or call a social API. All reporting opens
SQLite read-only and never initializes, migrates, repairs, or resets it.

### Human-action rules

- **New idea / revise:** opens or continues a thread; never edits a historical
  revision, job, package, review, or post.
- **Approve now:** creates one immediate `PostRequest`; **schedule** creates
  one scheduled request; **reject** ends that review request without delivery.
- **Cancel delivery:** is available only before an attempt sends the final
  publication request. It records cancellation and never deletes creative.
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
| Worker health | `worker_runs`, current claims, duration, last success/failure, lease expiry, backlog, cadence, next expected run, stale reason | Which component needs attention? |
| Detection | Runs, source-instance health/degradation, observations/snapshots, candidates, score/fingerprint/version, cluster members, shortlist, consumed/rejected/cooldown/evidence change | Why was an opportunity selected, deferred, or blocked? |
| Threads and intake | New-idea entry, origin, complete conversation, clarification state, revisions/parents, source evidence, linked work | What did I ask for and what changed? |
| Determination | Requests/leases, frozen input, capability snapshot, decision/reasoning/alternatives/identities, Gemini usage, job/rejection | Why did the system choose/refuse a route? |
| Production/content | Jobs/leases, recipe, package creative/caption/tags/hashtags/citations, identities/hashes, contract/model versions, validation | What was generated and is it valid? |
| Rendering | Runs/leases, renderer/template versions, manifest verification, ordered preview/assets/dimensions/checksums, failure/recovery | Are exact assets ready and trustworthy? |
| Review queue | Final asset preview, caption/tags/hashtags, source/brief/decision context, package identity, age, approve/schedule/reject/revise actions | What is ready for my decision? |
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
assets—not a regenerated preview—alongside all metadata, sources, destination,
identity, and warnings. Approval confirms that Instagram is public and
irreversible. Scheduling shows the computed cadence slot before the command is
written.

### Delivery view

Keep human intent and external state distinct:

- `PostRequest`: what the human approved and when.
- `PostRecord`: what the delivery worker did.
- `PostAttempt`: which delivery stage was reached.
- `PublicationResource`: which remote object/container exists.
- `DeliveryCleanupTask`: whether transient media is still retained.

No control retries a failure. Safe retries are worker policy. The only human
options are a new revision, a new approval, a pre-publication cancellation, or
reconciliation of an uncertain publication.

## Freshness, cadence, and stale-state policy

Use local SQLite polling. Every worker writes a `worker_runs` heartbeat at
start and completion, including no-work polls. Freshness is calculated from
heartbeat, last success, active lease, and configured cadence—not a browser or
in-memory flag.

| Component | Normal cadence | Behavior | Fresh / warn / stale |
| --- | --- | --- | --- |
| Dashboard, visible | 10 seconds | One consistent local SQLite snapshot; no external call | ≤20 s / >20 s / >60 s or read failure |
| Dashboard, hidden | No polling; refresh on return | Avoid needless local load | Shows prior snapshot age |
| Trend Scout | 15 minutes | Collect, normalize, persist complete scored set, then shortlist | ≤20 min / >20 min / >45 min |
| Trend Shortlist | Same Scout transaction | Select from just-persisted scored set | Same as parent Scout run |
| Idea Intake Agent | 30 s with unread human messages; 5 min health poll otherwise | Clarify or freeze revision | ≤1 min / >1 min / >3 min with pending input |
| Determination Worker | 30 seconds | Drain pending requests; no Gemini call when empty | ≤1 min / >1 min / >3 min with pending work |
| Pipeline Runner | 30 seconds | Drain pending jobs | ≤1 min / >1 min / >3 min with pending work |
| Visual Renderer | 30 seconds | Drain pending render runs | ≤1 min / >1 min / >3 min with pending work |
| Review availability | Created atomically after successful manifest | No separate worker | Next dashboard refresh (≤10 s) |
| Posting Agent | 15 seconds | Claim due approved/scheduled records; safe retries only | ≤30 s / >30 s / >90 s when due work exists |
| Cleanup Worker | 5 minutes | Drain safe cleanup tasks | ≤10 min / >10 min / >20 min with pending cleanup |
| Publication reconciliation | Human request; optional 15-min check while unknown exists | Read-only external lookup, no retry/publish | Show last check; warning until resolved |

Do not call an active leased item stale before its `lease_expires_at`. After
expiry, label the individual record **stale claim**, separately from ordinary
backlog. `publication_unknown` is terminal and high visibility, never an item
for automatic stale recovery.

The 10-second dashboard cadence is intentionally faster than workers so human
state changes appear promptly without API cost. Manual browser refresh is the
same read-only operation.

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
