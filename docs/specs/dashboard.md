# Dashboard and Human–Agent Interface

**Document role:** Tier 2 current dashboard contract.
**Owner:** Local visibility and persisted human commands.

## Boundary

`scripts/serve_dashboard.py` serves a loopback-only HTTP interface. One read
transaction supplies each page; GET performs no state changes and never invokes
a worker, provider or model. POST commands validate CSRF, bounded form input,
command identity and row version before committing SQLite. Storage samples never
authorize or deny planning commands; downstream Post now admission is separate.

All displayed times are UTC. Navigation links Detection, ideas/threads, queues
and operations.
Thread links open a focused thread page rather than placing its details below
the Detection tables. `?view=threads` lists ideas; `?view=operations` shows queues
and runtime health.
Ten-second incremental polling calls read-only `/snapshot` only while visible.
The bounded JSON response contains the current view's server-rendered main fragment
(maximum 8 MB). A keyed DOM update preserves drafts, focus, open evidence and scroll;
only changed nodes are patched. Dirty forms retain their original row version so
concurrent changes still refuse safely. A removed target preserves the draft but
disables submission. Failed refreshes retain the last view and show a retry notice.
The Updated-at indicator reports the last successful snapshot; it is not a worker
heartbeat. Snapshot GET never samples storage, creates work or calls a provider.

## Detection visibility

Detection leads with compact stage tabs and counts for Raw Feed Items, Clusters,
Opportunities and ContentJobs. The default stage is Clusters. Exactly one dense
stage table occupies the primary list area; detail pages retain full evidence.
Queues and operations follow below. Wide operations tables scroll inside their
own panels on narrow screens:

| View | Meaning and traceability |
| --- | --- |
| Raw Feed Items | Individual normalized source observations, not streams or unique provider items across repeated polls. Item links show source, fetch attempt and the latest 50 frozen membership records. |
| Clusters | All scored clusters with attention score, Detection Selection state/reason, evaluation time and evidence links. |
| Opportunities | Selected Clusters with an actual trend thread, initial source-backed brief and Determination request. The initial request status/outcome and thread link expose decisions, refinements and routes. A selected label alone is insufficient. |
| ContentJobs | Persisted jobs from trend or human briefs, showing domain, angle, origin and latest GenerationRun status. Job detail retains the exact immutable brief/recipe/output plan. Generation status is not publication status. |

Search and source filters are literal/parameterized. The Cluster Selection state
filter affects only Clusters. Every stage has independent pagination (`raw_page`,
`cluster_page`, `opportunity_page`, `job_page`) and preserves the active stage,
filters and Cluster sort. Counts reflect filters. Raw/Cluster views use the active
Detection release; persisted Opportunities and ContentJobs remain accessible
across releases. Source filtering excludes human-origin jobs, which have no
Detection source. Cluster sorting uses only an allowlisted mapping: default
`cluster_sort=score_desc` orders globally by score, then updated timestamp and
ID; `cluster_sort=recent` orders by recently evaluated state. Selection remains
visible and filterable but never silently groups score order.

Cluster detail (`?cluster_id=N`) shows scoring components,
frozen source and semantic membership evidence, and up to 200 linked observations
with their credited contribution. Semantic membership does not manufacture
corroboration: non-anchor lexical members receive zero scoring credit.
`?raw_item_id=N` and `?job_id=N` open exact item and job details. SQL identifiers
remain visible only inside diagnostic evidence, not as a separate user concept.

The status legend and Source / Feed operations table distinguish collection-attempt
status from source-health classification. Raw Feed Items have no Selection status.
The [Detection lifecycle](detection.md#status-ownership) defines the four states
Scout currently writes and distinguishes reserved schema values from active behavior.

Scout evaluation links expose input fingerprint, slot, status, lease/error,
frozen source availability, model identity, thresholds, lexical clusters and
semantic pair signals. The full frozen resolution is expandable JSON evidence;
it is not recomputed by the dashboard.

Operations show active source configuration, latest collection/health/failure,
recent Scout evaluations, worker heartbeats with freshness, and recent
substantive worker runs. Idle polls do not append run history. Queue summaries
show Intake, Determination and Generation counts by persisted status.

## Human ideation and routing visibility

The thread list is paginated (20 by default); `?thread_id=N` opens a specific
thread. It shows origin, status, updated time, row version and Detection backlink.

- Ordered human/agent conversation; 50 messages per page, older/newer navigation.
- Submit idea and reply/refine forms, including clarification questions.
- Latest 20 Intake statuses, failure reasons, claim/lease/retry evidence.
- Current full brief; thread detail can page through every prior revision.
- Frozen source/conversation context and creation-time capability catalog.
- Determination status, outcome, opportunity value, rationale and warnings.
- All three route cards, including fit, stopping reasons, selected angle fields,
  output bindings and resulting immutable ContentJob recipe/output plan.
- Generation, adaptation, visual planning and rendering progress for each job,
  including blocked rendering reasons and exact English six-slide review assets.
- Recent Gemini invocation outcome, model, token usage, estimated cost and safe
  diagnostics.

Generation remaining `pending` is intentional when the runner uses
`--planning-only`. A failed request is not idle; a question requires a human
reply. A new revision does not overwrite older work.

## Commands

Supported forms persist `new_idea`, `continue_thread`, review approval,
rejection and changes. Delivery/provider controls and commands are not exposed.
Review acceptance does not create posting authorization.

Commands are idempotent by command ID, with compare-and-swap row versions where
needed. New ideas and replies redirect to their resulting thread. Form bodies
are limited to 100,000 encoded bytes, while human idea text remains 8,000
characters; this accommodates percent-encoded Unicode.

Asset responses are restricted to configured artifact roots and checked against
persisted size/hash manifests. HTML text is escaped, source links permit only
HTTP(S), assets use nosniff, and CSP permits only the fixed refresh script and
same-origin snapshot requests.

Advisory storage observation displays missing/stale/clock-invalid samples separately from
measured disk pressure, with last sample time, free bytes and a model-free recovery
command. None of these conditions prevents ideas, refinements, Intake, Detection,
Determination or ContentJob creation. Actual SQLite/OS write errors still fail.
Operations shows up to 31 daily growth measurements, component sizes,
row deltas and JSON-byte totals by table. Measurements can be partial under their
time limit; absence of samples never implies zero growth.

## Operational limits

This is a trusted-machine loopback interface, not a multiuser web application.
Do not expose it publicly. Do not enter credentials in conversations.

Catalog activation, retrying uncertain paid operations, reopening closed threads
and process start/stop are not dashboard commands. Use the documented explicit
operator entrypoints. The dashboard retains evidence, not a hidden worker
control channel.
