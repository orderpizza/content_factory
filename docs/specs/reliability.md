# Reliability and Safety Specification

**Status:** Approved target design; several policies are not yet implemented.
**Owner:** Worker recovery, duplicate prevention, artifact integrity, posting
safety, configuration boundary, and operational acceptance.
**Read this for:** Detection/recovery/worker work, Gemini/R2/render/posting
changes, 24/7 operations, or any external side effect. Read
[the system guide](../system.md) first and [the data model](data-model.md) for
the exact records and constraints.

## Scope

Content Factory remains local-first: Mac Mini, SQLite handoffs, deterministic
detection, Gemini only in Idea Intake/Determination/pipeline generation, and
small platform adapters. These policies do not justify distributed queues,
direct module calls, or new cloud runtime infrastructure.

The current implementation can public-post ready packages automatically. The
target design requires human review before every public post and implements the
policies below before unattended posting is enabled.

## Trend quality and recurrence

### Deterministic, explainable detection

- Normalize each source within its own unit before combining activity. RSS
  presence, votes, page views, and video views are not directly comparable.
- Score momentum, corroboration breadth, freshness, and source reliability
  separately. Persist scoring and canonicalization versions.
- Define first-observation scoring and deterministic tie-breakers:
  corroboration, normalized activity, freshness, then stable candidate ID.
- Persist every scored candidate before applying top-N/minimum-score selection.
  Retention is not a presentation limit.
- Persist exact clustered observation membership and provenance. Determination
  receives frozen cluster evidence, never a later topic-string lookup.
- Record source-instance identity, measurement windows, fallback/degradation,
  latency, and structured errors. Stale/degraded evidence is visible and may be
  deterministically penalized or rejected.

### Recurrence policy

- An accepted trend candidate is consumed for automatic routing permanently;
  time passing alone does not reconsider it.
- A rejected candidate can re-enter only after three days **and** material
  deterministic evidence change.
- Worker failure resumes the same persisted request. It does not make a fresh
  request from unchanged evidence.
- A human can continue any thread and create an intentional revision. This is
  allowed because it is explicit, auditable rework—not automatic duplication.
- Future recurring coverage needs its own editorial freshness/version policy.

The data model enforces separate evidence, coverage/content, and publication
identities. A single hash must not be used as a shortcut for all duplication
problems.

## Worker claims, recovery, and concurrency

Each work item has explicit state, conditional claim, claim owner, timestamp,
lease expiry, safe error, and terminal outcome. State machines are:

| Record | State model |
| --- | --- |
| `DeterminationRequest` | `pending → claimed → accepted/rejected/failed/cancelled` |
| `ContentJob` | `pending → claimed → running → completed/failed/cancelled` |
| `RenderRun` | `pending → claimed → running → succeeded/failed/cancelled` |
| `PostRecord` | `scheduled → publishing → published/retryable_failure/failed/publication_unknown/cancelled` |

Safe expired leases resume the same record. Determination must distinguish
`no_work`, `accepted`, `rejected`, `failed`, and `cancelled`; a rejection never
stops later work. If a decision was saved before a crash but its accepted job
was not, create the unique missing job instead of evaluating again.

Use short SQLite transactions, configured busy timeout, and WAL only after Mac
Mini multi-process verification. Never hold a transaction during Gemini, R2,
or social API work. Database uniqueness conflicts are successful idempotent
outcomes when they represent work already created.

The exact cadence, freshness, and stale thresholds live in the
[dashboard specification](dashboard.md). A stale `publishing` post is never
safe to retry; it becomes `publication_unknown`.

## Rendering and package integrity

Pipelines own the creative and versioned visual specification. The renderer
renders that specification; it does not rewrite captions, tags, hashtags, or
creative meaning.

- Every package carries a versioned visual-spec contract and resolved template
  ID/version/hash for each slide.
- Render into a package/content-identity-specific temporary directory, verify a
  complete manifest, then atomically promote the render run.
- The manifest includes content identity/hash, renderer/template version,
  ordered slide count, local path, MIME type, dimensions, bytes, and SHA-256.
- Path existence is never evidence of valid assets.
- O2 readiness validates its exact carousel grammar, slide count, image
  dimensions/format, immutable caption, and hashtag representation before
  review/delivery. Posting rejects invalid input rather than repairing it.

## External publication safety

External publication is the final and most conservative boundary.

1. Validate configuration, package, asset manifest, cadence, and destination
   before the final `media_publish` request.
2. Persist a `PostAttempt` and publication identity before that request.
3. Classify pre-final-request failure as configuration, validation,
   authentication, permission, rate-limit, server-transient, or
   network-pre-request. Retry only categories explicitly safe to retry.
4. Once a final request may have reached Instagram—including timeout, lost
   response, or local persistence failure after remote success—write terminal
   `publication_unknown`. Never retry it automatically.
5. Use a read-only reconciliation lookup to investigate an uncertain outcome.
   It never publishes. Human resolution is auditable; a second post needs new
   explicit approval.

R2 staging cleanup is an independent, idempotent audited task. A cleanup
failure is visible and retryable when safe, but never changes a confirmed post
to failed.

## Configuration and Gemini accounting

Load local `.env` configuration once at each process composition root. Domain
modules receive validated settings and never read environment variables. Check
all required/numeric values at startup. A blank optional Gemini cost rate means
unknown cost, not a reason to fail/repeat a successful model operation.

Write a model-invocation ledger immediately after every completed provider
response, before parsing/validation. Preserve token usage for accepted, invalid,
parse-failed, schema-failed, and provider/transport-failed attempts. Store safe
metadata only—never credentials or full provider prompts/responses.

## Operational acceptance

Before enabling continuous public delivery, implementation and boundary tests
must demonstrate:

- correct source normalization, provenance, tie behavior, and recurrence;
- idempotent claims and safe recovery after every persistence boundary;
- one job/package per accepted revision and no accidental duplicate coverage;
- actual asset dimensions/format/manifest match the package;
- one final publication request per publication identity;
- `publication_unknown` after ambiguous final outcomes;
- audit of every model attempt, delivery attempt, and cleanup outcome; and
- dashboard health/freshness reflects persisted worker state without mutating
  the database.
