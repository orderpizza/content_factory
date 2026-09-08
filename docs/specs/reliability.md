# Reliability and Safety Specification

**Document role:** Tier 2 target design contract. It defines required behavior;
verify implementation conformance from code and tests.
**Owner:** Cross-cutting worker recovery, duplicate prevention, artifact
integrity, external-side-effect safety, configuration boundary, and operational
acceptance.
**Read this for:** Recovery/idempotency work, Gemini/R2/render safety, or any
external side effect. For the normal Posting Agent lifecycle, read
[Posting Agent](posting.md) as well. Read
[the system guide](../system.md) first and [the data model](data-model.md) for
the exact records and constraints.

## Scope

Content Factory remains local-first: Mac Mini, SQLite handoffs, deterministic
detection, Gemini only in Idea Intake/Determination/domain generation/output adaptation, and
small platform adapters. These policies do not justify distributed queues,
direct module calls, or new cloud runtime infrastructure.

The target design requires human review and explicit delivery authorization
before every public post. The policies below are prerequisites for unattended
delivery after that authorization.

## Worker claims, recovery, and concurrency

The [data model](data-model.md) owns every exact state set. Each claimable item
has explicit state, conditional claim, claim owner/time, lease expiry,
monotonic `claim_version`, bounded attempt metadata, safe error, and terminal
outcome. Transient failure enters `retry_wait` with `next_attempt_at`; terminal
`failed` is never polled as retryable work.

Every finalize/update condition includes the claimed state, owner, and
`claim_version`. Safe expired leases resume the same record under a higher
fencing version, and a former owner can no longer commit. Determination must distinguish
`no_work`, `accepted`, `not_recommended`, `blocked`, `failed`, and `cancelled`;
non-acceptance never stops later work. Decision, all domain route rows, every selected-route job/initial run, and
request completion share one transaction. No partial fan-out is permitted.

Detection has two persisted recovery boundaries. A `SourceCollectionAttempt`
is the only record permitted to call a provider; a retry reuses that attempt
and no completed response is fetched again. A `ScoutEvaluationRun` is a
separate, no-provider-call operation that freezes a set of completed collection
attempts and source-health states before scoring. Its retry reuses exactly that
frozen input. A later source response is evaluated only by a later evaluation
slot, never substituted into a completed or retrying run.

Thread cancellation is an additional fenced finalization condition for every
pre-publication worker. A cancellation that commits first prevents a worker
from creating its next downstream handoff or an external delivery attempt. A
worker that already crossed the final platform-publication marker must preserve
the result as published or `publication_unknown`; cancellation never makes an
ambiguous external side effect retryable or reversible.

Use short SQLite transactions, configured busy timeout, and WAL only after Mac
Mini multi-process verification. Never hold a transaction during Gemini, R2,
or social API work. Database uniqueness conflicts are successful idempotent
outcomes when they represent work already created.

The exact worker schedule, poll behavior, and stale thresholds live in the
[worker runtime specification](runtime.md). A stale `publishing` post is never
safe to retry; it becomes `publication_unknown`.

### Idempotency guards at claim boundaries

Every worker checks whether its durable output already exists before performing
claim-bound work. The exact guard queries are listed in the data model's
uniqueness constraints.

- Pipeline Runner checks whether `CanonicalContent` already exists for the
  claimed `job_id` before domain generation.
- Determination Worker checks whether `DeterminationDecision` already exists
  for the claimed handoff before evaluation.
- Adaptation Worker checks whether `ContentPackage` already exists for the
  claimed `OutputRequest` before adaptation.
- Visual Renderer checks whether each individual asset file already exists on
  disk before re-rendering its slide or card.
- Posting Agent relies on its existing duplicate check: the unique constraint
  on content/platform/account.

An existing output is a successful idempotent outcome, not a reason to repeat
generation, adaptation, rendering, or publication.

## Rendering and package integrity

Domain pipelines own canonical meaning; output adapters own adapted creative
and the versioned visual specification. The shared local
renderer renders that specification; it does not rewrite captions, tags,
hashtags, or creative meaning. The reusable renderer/provider, local input,
and quality contract is owned by [Visual Rendering](visual-rendering.md).

- Every package carries a versioned visual-spec contract and resolved
  renderer-owned profile/template ID/version/hash for each slide.
- Successful Adaptation Run finalization atomically creates the immutable
  package and its first pending Render Run, so a package cannot be stranded
  without a renderer work item.
- Render into a package/content-identity-specific temporary directory on the
  same filesystem as the canonical artifact root. `fsync` files/directories as
  supported, verify a complete manifest, atomically rename the directory to a
  run-specific immutable final path, and only then commit the succeeded run,
  assets, manifest, and Review Request in one SQLite transaction.
- Startup recovery deletes only verified abandoned temporary directories. A
  promoted final directory without a succeeded database row is quarantined and
  reconciled by run identity/hash; it is never silently adopted or overwritten.
- The manifest includes content identity/hash, renderer/template version,
  ordered asset roles/ordinals, local path, MIME type, dimensions, bytes,
  SHA-256, and conversion/encoder version. Canonical `delivery_jpeg` assets are
  reviewed; R2 transport copies are not.
- Path existence is never evidence of valid assets.
- Review approval revalidates the stored content and manifest hashes and all
  referenced asset hashes. Mismatch, destination/account change, or an
  incompatible frozen-asset requirement invalidates the review; temporary
  provider/token readiness does not. Approval cannot float to newer output.
- Output readiness validates its frozen Instagram/X grammar, native text,
  image count/dimensions/format, immutable metadata, and required disclosures
  before review/delivery. Posting rejects invalid input rather than repairing it.

## External publication safety

External publication is the final and most conservative boundary. The normal
Posting Agent and platform-adapter lifecycle is owned by [Posting Agent](posting.md);
the rules here constrain its safety behavior.

1. Validate configuration, package, asset manifest, cadence, and destination
   before the final provider-publication request.
2. Persist a `PostAttempt`, publication identity, and a durable
   `final_publication_request_sent_at` marker immediately before that request.
   If the process cannot prove the marker was committed, it must not send.
3. Classify pre-final-request failure as configuration, validation,
   authentication, permission, rate-limit, server-transient, or
   network-pre-request. Retry only categories explicitly safe to retry.
4. Once a final request may have reached the platform—including timeout, lost
   response, or local persistence failure after remote success—write terminal
   `publication_unknown`. Never retry it automatically.
5. Use a durable `ReconciliationRequest` and append-only read-only checks to
   investigate an uncertain outcome. It never publishes. Only an unambiguous
   provider match may resolve automatically; every human resolution is
   auditable and a second post needs new explicit approval.

Before the durable final-publication marker, dashboard cancellation and the
Posting Agent's final-marker transaction race through one fenced conditional
SQLite update. Cancellation that commits first marks the active attempt
`cancelled`, schedules cleanup for staged R2 bytes, and retains/audits provider
containers; the agent then has no authority to make the final call. A committed
final marker wins instead and retains the normal published/unknown safety rule.

R2 staging cleanup is an independent, idempotent audited task. A cleanup
failure is visible and retryable when safe, but never changes a confirmed post
to failed.

## Fan-out, reuse, and optional-thread safety

Generation success atomically persists canonical content and all frozen output
requests/adaptation runs. Adaptation retry never repeats canonical generation.
Every model call in either stage charges the same parent job cap and the shared
daily cap. Fingerprint checks, domain-angle guards, unique output identity, and
confirmed/uncertain publication history remain independent of cooldown.

Optional X threads require one durable pre-send marker per public post, not
one marker for a multi-call adapter. A confirmed prefix remains public audit;
a failed/unknown suffix cannot make the whole thread safely unpublished.
Do not retry a confirmed/possibly sent step or automatically restart the package.
Until exact per-step transitions and reconciliation fixtures exist, thread mode
is disabled under [Platform outputs](platform-outputs.md).

## Storage, backup, and retention — `storage_safety_v1`

SQLite is the operational source of truth. Once daily at 03:30 `Asia/Seoul`, a
maintenance process takes a consistent SQLite online-backup snapshot to the
configured local backup volume; it never copies a live database file and WAL
by filesystem copy. Keep 14 daily and 8 weekly snapshots. After a successful
snapshot, request a passive WAL checkpoint; request `TRUNCATE` only when no
worker has an active claim and the checkpoint reports no busy reader. Failed
backup or checkpoint is a visible operational warning, never a reason to delete
the current database, WAL, or previous backup.

At least once each calendar month, restore the newest backup into a new
temporary directory, open it with foreign keys enabled, run `PRAGMA
integrity_check`, verify migration checksum/version, and query a representative
source-to-publication trace. Record the result as an auditable maintenance run.
The dashboard warns if the latest successful backup is older than 26 hours or
the last restore verification is older than 35 days. A separately configured
Mac backup system/off-device copy is strongly recommended; without one the
dashboard continuously shows **local backups only** rather than claiming
hardware-loss recovery.

All SQLite audit records, model/delivery/reconciliation evidence, package
metadata, review decisions, and publication history are retained indefinitely.
The system stores bounded source metadata rather than fetched article/video
bodies. Canonical local renderer output follows this retention schedule:

| Material | Retention and removal rule |
| --- | --- |
| Pending, reviewable, approved, delivery-retry, or `publication_unknown` final assets | Keep local bytes until the record is terminally resolved; never delete under routine retention. |
| Published final assets and their local preview/HTML/PNG derivatives | Keep 180 days after confirmed publication, then delete only bytes after verifying the immutable manifest/hash remains in SQLite. |
| Rejected, cancelled, failed, or expired final assets with no publication identity | Keep 30 days after terminal state, then delete only bytes after manifest/hash verification. |
| Run-specific temporary directories | Delete after a verified owner/lease recovery, or 24 hours after abandonment. |
| Quarantined promoted directories | Keep until reconciled by run ID/hash; never apply age deletion while unreconciled. |
| R2 `instagram-transient/` staged objects | Cleanup Worker deletes after a safe terminal delivery outcome; bucket lifecycle deletion at 7 days is a backstop only. |

SQLite record retention is separate from byte retention. The Maintenance Worker
removes only the following high-volume details, in small committed batches,
and writes an append-only retention summary before each deletion:

| Record class | Detailed-row retention | Durable summary retained |
| --- | --- | --- |
| Observations and source-item events not linked to a selected candidate or retained candidate | 90 days after collection | source, window, count, payload-hash aggregate, retention-run ID |
| Unselected/deferred/rejected candidate score detail and topic snapshots | 180 days after evaluation | candidate identity, disposition, score/fingerprint/version, retention-run ID |
| Source-health and completed collection/evaluation operational detail not needed by retained evidence | 180 days | source/run identity, health disposition, counts, configuration fingerprint |
| `worker_runs` | 90 days | daily worker/status/count/duration aggregate |
| `storage_samples` | 90 days at five-minute resolution, then daily aggregate through 365 days | daily minimum free space and maximum component sizes |
| Cleanup-task and maintenance detail | 365 days after terminal outcome | terminal identity, disposition, timestamps, counts/checksum |

Rows tied to a selected candidate, a ContentThread, a revision, a package, a
review, a post, a reconciliation, a configuration release, or a migration are
never routine-retention candidates. Retention never removes the evidence needed
to explain a public or uncertain publication. A failed batch rolls back; a
retention run records zero deletions rather than partially deleting its scope.

Physical artifact deletion updates no historical asset/manifest/hash fields; it
adds a deletion timestamp/reason to the artifact record. Cleanup never removes
credentials, audit evidence, pending-review bytes, or a possibly published
delivery input merely to reclaim space.

The Storage Monitor samples available space and database/WAL/artifact/backup
sizes every five minutes. Normal operation requires both at least 15 percent
free space and 10 GiB free. Below either threshold it enters `storage_warning`
and blocks new Pipeline Runner, Adaptation Worker, and Visual Renderer claims while preserving
dashboard, review, posting, reconciliation, and cleanup. Below 8 percent or 5
GiB it also pauses new Trend Scout collections and performs only safe cleanup;
existing delivery audit remains readable. Below 3 percent or 1 GiB it enters
read-only emergency mode: it takes no new external/model/generation/delivery
claim and the dashboard disables commands that would create work, while still
showing the precise condition and recovery guidance. Recovery requires both
thresholds to be exceeded on two consecutive samples; no worker deletes audit
rows automatically to leave an emergency state.

## Configuration and Gemini accounting

### Operational-data minimization — `operational_data_v1`

Human messages, source titles/snippets, and frozen editorial snapshots are
operational data, not secrets by default. The dashboard warns the operator not
to paste credentials, access tokens, private URLs, or personal data into an
idea or change request. Idea Intake may send only the bounded current-thread
messages, frozen brief, and relevant selected evidence to Gemini; Determination
may send only the frozen revision/catalog and bounded relevant prior-angle
summaries; a domain pipeline may send only the immutable job and approved
source/reference inputs; an output adapter may send only its frozen canonical
content and output policy. No worker sends
raw source payloads, diagnostic logs, credentials, signed URLs, browser
sessions, or unrelated historical threads to Gemini.

Authoritative messages are retained under the Data Model policy, but are capped
at 8,000 UTF-8 characters per message and 32,000 characters of frozen input per
model invocation. Source excerpts are capped at 4,000 characters per item and
only their bounded normalized excerpts enter SQLite; fetched bodies are never
stored. Input over a limit is rejected with a typed `input_too_large` outcome,
not silently truncated after a human has submitted it.

Safe diagnostics redact values matching secret/header/token/signed-URL patterns
and retain only category, provider request ID when non-secret, hash, and a
bounded 2,000-character safe summary. Authoritative human messages are not
redacted or rewritten because that would break their audit meaning; the UI
marks them as operator-supplied and keeps them out of generic diagnostic views.
Backups contain the retained SQLite operational data and therefore inherit the
same local access boundary. Before any non-local dashboard or multi-operator
mode, an explicit privacy deletion/export process and data-access design are
required. Credentials, authorization headers, signed URLs, raw provider
payloads, and full model prompts/responses must never enter SQLite, backups,
packages, manifests, or logs.

`gemini_budget_v1` applies a local daily warning threshold of USD 5.00 and a
hard stop at USD 8.00 across all model invocations in one UTC day. The active
configuration release must supply a nonempty, versioned price snapshot for each
permitted model: model/provider ID, effective timestamp, input and output
prices in integer micro-USD per token, and maximum input/output tokens for each
named invocation phase. Initial operation is **priced-required**: an absent,
zero, malformed, or mismatched price snapshot blocks new Gemini-backed claims;
there is no token-only fallback mode.

Before a provider call, the worker validates the frozen model/schema phase and
atomically calculates `ceil(max_input_tokens * input_price + max_output_tokens
* output_price)` micro-USD. It creates one `reserved` ledger row only if that
amount plus existing `settled`, `reserved`, and `uncertain` reservations is at
or below both the UTC-day hard stop and the frozen job cap. Token caps are
checked independently in the same transaction. The reservation stores the
price snapshot hash, token maxima, daily limit, job limit, and computed
worst-case cost, so every admission result is reproducible. The dashboard
reports settled cost, outstanding reservations, and the specific admission
blocker. Reaching the warning does not stop already claimed work; the hard stop
prevents new Gemini claims until the next UTC day or a new active release.

A `ModelInvocation(outcome=started)` that outlives its lease is cost-uncertain:
its reservation remains counted until an explicit provider/accounting recovery
marks it settled or conclusively releases it. The same content
entity is blocked from an automatic repeat. This preserves a conservative daily
ceiling without assuming that a lost response incurred zero cost.

Load local `.env` secrets/composition settings once at each process composition
root. Domain modules receive validated settings and never read environment
variables. Non-secret source, capability, renderer, posting, teaching, and
runtime policy is an activated persisted release owned by the
[Configuration control plane](configuration.md), never an environment default.
Check all required/numeric values and secret references at startup. A missing
Gemini price snapshot blocks a new model call before admission; it never causes
a successful prior model operation to be repeated or reclassified.

Insert and commit an `outcome=started` model-invocation ledger row before each provider
call. Finalize it immediately after response or transport failure and before
parsing/validation. Preserve token usage for accepted, invalid, parse-failed,
schema-failed, and provider/transport-failed attempts. A stale `started` call is
an uncertain-cost event and is never silently repeated. Store safe metadata
only—never credentials or full provider prompts/responses.

All external text—trend titles, feed bodies, provider metadata, and human text
quoted from an external source—is untrusted data. Detection never interprets
instructions. Gemini prompts delimit source material from system policy, and
model output can only populate validated schemas; it cannot call tools, alter
capabilities/policy, read secrets, or authorize publication.

External-input and local-artifact adapters also enforce structural boundaries:

- source collection uses only enabled registry entries, HTTPS, bounded
  timeout/response/decompression size, safe redirect policy, and rejects local,
  loopback, link-local, and private-network destinations;
- XML/HTML parsing disables external entities and active content;
- visual specifications reference registered logical asset/font/template IDs,
  never arbitrary absolute paths or traversal segments from model/user input;
- template and dashboard rendering escapes untrusted text and never executes
  package-provided HTML/script; and
- logs, errors, raw-JSON views, and provider summaries apply a shared secret
  and signed-URL redaction policy.

The POC dashboard binds only to the Mac Mini loopback interfaces. Its single
operator is the durable `local_owner` actor; it has no remote-access or
multi-user authentication mode. A state-changing dashboard command requires a
same-origin anti-CSRF token, unique client command ID, and target-record
version. These protections make browser retries and duplicate clicks safe but
do not insert a confirmation step before an authorized **Post now** command.
Any non-loopback dashboard deployment requires a separately approved
authentication/authorization design before human commands are enabled.

## Operational acceptance

Before enabling continuous public delivery, implementation and boundary tests
must demonstrate:

- idempotent claims and safe recovery after every persistence boundary;
- fencing prevents an expired claimant from committing after reassignment;
- one job per selected domain route, one canonical result per job, and one
  package per output request, with atomic fan-out and no duplicate paid creative;
- independent review/authorization per destination and preservation of siblings;
- optional-thread per-step markers, partial-publication audit, and no duplicate
  confirmed prefix before thread mode can be enabled;
- actual asset dimensions/format/manifest match the package;
- one final publication request per publication identity;
- `publication_unknown` after ambiguous final outcomes;
- audit of every model attempt, delivery attempt, and cleanup outcome; and
- dashboard health/freshness reflects persisted worker state without mutating
  the database.
