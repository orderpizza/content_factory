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
detection, Gemini only in Idea Intake/Determination/pipeline generation, and
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
non-acceptance never stops later work. Accepted decision, unique job, and
request completion share one transaction; missing-job repair is legacy-only.

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

## Rendering and package integrity

Pipelines own the creative and versioned visual specification. The shared local
renderer renders that specification; it does not rewrite captions, tags,
hashtags, or creative meaning. The reusable renderer/provider, local input,
and quality contract is owned by [Visual Rendering](visual-rendering.md).

- Every package carries a versioned visual-spec contract and resolved
  renderer-owned profile/template ID/version/hash for each slide.
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
  referenced asset hashes. Mismatch or supersession invalidates the review;
  approval cannot float to newer output.
- O2 readiness validates its exact carousel grammar, slide count, image
  dimensions/format, immutable caption, and hashtag representation before
  review/delivery. Posting rejects invalid input rather than repairing it.

## External publication safety

External publication is the final and most conservative boundary. The normal
Posting Agent and platform-adapter lifecycle is owned by [Posting Agent](posting.md);
the rules here constrain its safety behavior.

1. Validate configuration, package, asset manifest, cadence, and destination
   before the final `media_publish` request.
2. Persist a `PostAttempt`, publication identity, and a durable
   `final_publication_request_sent_at` marker immediately before that request.
   If the process cannot prove the marker was committed, it must not send.
3. Classify pre-final-request failure as configuration, validation,
   authentication, permission, rate-limit, server-transient, or
   network-pre-request. Retry only categories explicitly safe to retry.
4. Once a final request may have reached Instagram—including timeout, lost
   response, or local persistence failure after remote success—write terminal
   `publication_unknown`. Never retry it automatically.
5. Use a durable `ReconciliationRequest` and append-only read-only checks to
   investigate an uncertain outcome. It never publishes. Only an unambiguous
   provider match may resolve automatically; every human resolution is
   auditable and a second post needs new explicit approval.

R2 staging cleanup is an independent, idempotent audited task. A cleanup
failure is visible and retryable when safe, but never changes a confirmed post
to failed.

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

Physical artifact deletion updates no historical asset/manifest/hash fields; it
adds a deletion timestamp/reason to the artifact record. Cleanup never removes
credentials, audit evidence, pending-review bytes, or a possibly published
delivery input merely to reclaim space.

The Storage Monitor samples available space and database/WAL/artifact/backup
sizes every five minutes. Normal operation requires both at least 15 percent
free space and 10 GiB free. Below either threshold it enters `storage_warning`
and blocks new Pipeline Runner and Visual Renderer claims while preserving
dashboard, review, posting, reconciliation, and cleanup. Below 8 percent or 5
GiB it also pauses new Trend Scout collections and performs only safe cleanup;
existing delivery audit remains readable. Below 3 percent or 1 GiB it enters
read-only emergency mode: it takes no new external/model/generation/delivery
claim and the dashboard disables commands that would create work, while still
showing the precise condition and recovery guidance. Recovery requires both
thresholds to be exceeded on two consecutive samples; no worker deletes audit
rows automatically to leave an emergency state.

## Configuration and Gemini accounting

`gemini_budget_v1` applies a local daily warning threshold of USD 5.00 and a
hard stop at USD 8.00 across all model invocations in one UTC day. Before
claiming Gemini-backed work, the worker reserves the configured worst-case
remaining cost for that work against the daily ceiling; the dashboard reports
both settled ledger cost and outstanding reservations. Reaching the warning
does not stop already claimed work. The hard stop prevents new Gemini claims
until the next UTC day or an explicit configuration change. Per-job caps remain
owned by the selected pipeline contract.

A `ModelInvocation(status=started)` that outlives its lease is cost-uncertain:
its reservation remains counted until an explicit provider/accounting recovery
marks it settled or a documented expiry policy releases it. The same content
entity is blocked from an automatic repeat. This preserves a conservative daily
ceiling without assuming that a lost response incurred zero cost.

Load local `.env` configuration once at each process composition root. Domain
modules receive validated settings and never read environment variables. Check
all required/numeric values at startup. A blank optional Gemini cost rate means
unknown cost, not a reason to fail/repeat a successful model operation.

Insert and commit a `started` model-invocation ledger row before each provider
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
- one job/package per accepted revision and no accidental duplicate coverage;
- actual asset dimensions/format/manifest match the package;
- one final publication request per publication identity;
- `publication_unknown` after ambiguous final outcomes;
- audit of every model attempt, delivery attempt, and cleanup outcome; and
- dashboard health/freshness reflects persisted worker state without mutating
  the database.
