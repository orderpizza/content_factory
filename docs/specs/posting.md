# Posting Agent Specification

**Document role:** Tier 2 target design contract. It defines the generic
Posting Agent and platform-adapter boundary; verify implementation conformance
from code and tests.
**Owner:** `PostRecord` pickup, `PostRequest` authorization,
`PostRecord`/attempt lifecycle, adapter
invocation, publication resources, delivery staging, and reconciliation input.
**Read this for:** Post now, cancellation, delivery attempts,
adapter behavior, R2 staging, publication records, or reconciliation. Read
[the system guide](../system.md) first, then [the data model](data-model.md)
and [reliability](reliability.md).

## Purpose and boundary

The Posting Agent is the shared, platform-neutral delivery worker. It claims a
due `PostRecord` backed by an explicit human-approved `PostRequest`, delivers
one exact reviewed package through a platform adapter, and records the external
outcome. It does not
generate or modify creative content, captions, tags, hashtags, assets, or
editorial routing.

```text
approved ReviewRequest
  → PostRequest + initial PostRecord (one transaction)
  → Posting Agent claims PostRecord
  → PostAttempt
  → platform adapter
  → PublicationResource + delivery result
  → cleanup / reconciliation records
```

**Implementation status:** [Current implementation and operations](../current-state.md)
owns available delivery modes, operational gates, and unverified provider
behavior. This target contract does not assert that a credentialed adapter is
composed or a public destination is enabled.

The dashboard creates authorization and its initial delivery record, or
cancels an eligible pre-publication record, but never calls the agent or a
platform API. The agent polls and claims its eligible Post Record through SQLite;
`PostRequest` is immutable authorization and is never a worker claim.
The exact eligibility/claim process is in [Worker runtime](runtime.md); the
records and constraints are in [Data model](data-model.md).

## Preconditions and immutable input

Before creating a delivery attempt, the agent verifies that the claimed record
is due, owns a live fenced claim, is backed by approved authorization, and is
still bound to:

- one approved review request;
- the exact package, destination, content hash, final render-manifest hash, and
  asset hashes reviewed by the human; and
- complete delivery assets whose checksums, MIME types, dimensions, and order
  satisfy the selected platform-output contract.

The agent gives the adapter only those immutable assets and metadata. It may
create transient delivery derivatives only when the platform contract permits
them and they were already represented in the reviewed final manifest. It never
repairs, converts, re-renders, reorders, or rewrites the package during
delivery.

## Generic delivery lifecycle

1. Claim one eligible `PostRecord` using its monotonic fencing version.
2. Revalidate the immutable approval binding, destination configuration release,
   current persisted destination readiness, eligibility/cadence policy, and
   final asset manifest. A stale/non-ready record blocks delivery before any
   provider side effect; it does not rewrite the historical human approval.
3. Create a `PostAttempt` before any external side effect.
4. Ask the selected platform adapter to stage assets, create platform resources,
   and perform its final publication operation.
5. Persist every safe remote ID/object as a `PublicationResource` and persist
   terminal outcome or `retry_wait` with bounded retry metadata when failure is
   provably pre-publication and retry-safe.
6. Create independent `DeliveryCleanupTask` records for transient staging
   objects. Cleanup does not alter confirmed publication state.

### Cancellation during staging — `pre_final_cancel_v1`

The dashboard may cancel a claimed or `publishing` Post Record only while its
linked Post Request remains approved and no `final_publication_request_sent_at`
marker exists. It matches the displayed row version and, in one transaction,
cancels the request and record, marks the active pre-final Post Attempt
`cancelled`, and creates one cleanup task for every staged R2 resource. It
marks any already-created provider child/parent container `retained` with the
safe reason `cancelled_before_final_publish`; those remote resources are never
silently deleted or reused.

Immediately before the provider's public-post operation (Meta: `media_publish`), the Posting Agent performs a final fenced
SQLite transaction. It rechecks its live claim, Post Record status
`publishing`, Post Request status `approved`, thread not cancelled, and absence
of a cancellation/final marker. Only that transaction writes
`final_publication_request_sent_at` and changes the attempt to
`final_request_sent`; the external call happens after it commits. If dashboard
cancellation won first, the transaction affects zero rows and the agent must
not call the public-post operation. If the marker won first, cancellation is rejected and
the eventual result is `published` or `publication_unknown`; no path turns a
possibly sent final request into a retry.

The initial POC accepts only **Post now** authorization. It records immediate
human intent; the versioned posting policy derives the record's earliest
eligible time. It never implicitly bypasses cadence, review, persistence,
validation, or adapter safety. An incomplete policy blocks the record before an
attempt rather than guessing. A future human scheduling feature requires a new
versioned command and data-model contract; it is not an implicit mode of Post
now.

## Initial cadence policy — `posting_policy_v1`

Post now means the earliest policy-compliant delivery; it never bypasses the
minimum interval or daily cap. O2's Instagram destination uses `Asia/Seoul` for account-day boundaries
and dashboard display; UTC timestamps remain canonical. The policy records a
daily cap of one post and a minimum interval of 20 hours. A pre-publication
failure reserves no slot: it releases immediately when its attempt becomes
retryable/failed. A final request that may have reached a platform reserves a slot
until human reconciliation because a post may exist. Daylight-saving changes do
not affect the initial account time zone; another account must supply its IANA
zone explicitly. Cadence is per actual platform/account destination, not per
domain; two pipelines sharing an account cannot multiply its quota. Other
Instagram/X destinations require their own explicit finite cap/interval policy
before activation. Optional threads need a verified per-step accounting policy
before their format is enabled.

## Review freshness and republishing — `review_freshness_v1`

An awaiting Review Request expires exactly 14 days after that request's own
`created_at`, not after its Render Run. An approved immediate Post Request
expires 48 hours after authorization if the final-publication marker has not
committed, even when staging or an earlier pre-final attempt has begun. The
claim and final-marker transactions both require `now < expires_at`; expiration
atomically marks its authorization and delivery record `expired`, without
changing the immutable package or assets. Expiry during staging stops the final
send and schedules safe cleanup. Once a final marker has committed before
expiry, preserve the eventual published/unknown outcome; expiry never permits
a retry or erases possible publication. A destination/account configuration
change, missing/mismatched reviewed asset hash, or a provider requirement that
makes the frozen reviewed asset invalidates the review binding. Template,
renderer, or font upgrades do not invalidate an already reviewed exact asset
manifest.

Temporary readiness is not editorial invalidation. An expired token, transient
provider outage, quota state, or stale readiness record blocks the Post Record
before a side effect and remains visible with its typed reason; it does not
change the prior approval or claim the human rejected the package. If that
temporary condition clears before the 48-hour authorization expiry, the same
Post Record may proceed. If authorization expires first, renewed delivery needs
a distinct fresh Review Request and a new explicit Post now command.

The system never intentionally republishes a confirmed published package. An
unchanged package may enter a fresh review cycle only after an expired review or
an auditable `not_published_cancel` reconciliation outcome; it receives a new
review-cycle number, new `created_at`, and a new expiry exactly 14 days later.
Before that transaction the dashboard revalidates the exact package/render/
destination, physical delivery asset bytes/hashes, and current compatible
destination policy. It rejects a new cycle when those assets are missing, a
confirmed publication exists, or a changed destination/provider requirement
would alter the reviewed binding. The fresh cycle is created by an explicit
human dashboard command, never by a worker. Any creative, metadata,
destination, or asset change requires explicit scoped rework and a new output
and publication identity followed by fresh review. A distribution-only change
reuses unchanged canonical content under an audited reuse link; only changed
domain-angle/creative input requires a new canonical content identity.

## Platform-adapter contract

An adapter is a small platform-specific service. It may use only its provided,
validated delivery input and its local configuration. It returns a structured
attempt result containing safe resource identifiers, a typed outcome, and the
point reached in the external workflow.

The adapter owns provider calls, provider-specific staging, container/resource
semantics, readiness polling, and provider error mapping. It must not make an
editorial decision or create a second publication. Provider account,
permission, token, API, and media requirements belong in the relevant
`platforms/` reference; format-specific composition requirements belong in the
shared [Platform outputs](platform-outputs.md) contract.

Phase 1 has Instagram and X delivery adapters, separate from their creative
output adapters. Instagram uses [Platform outputs](platform-outputs.md) and
[Meta](../platforms/meta.md); X uses the same output contract and the draft
[X reference](../platforms/x.md). Domain pipelines share these adapters.
The normal lifecycle here covers one public operation (an Instagram carousel
or an X single post). Optional X threads require the versioned per-step
extension below; they cannot be implemented by looping the single-post adapter.

## Independent destinations and optional threads

Each PostRequest authorizes one exact platform/account package. A sibling
package derived from the same canonical content has no authority until separately
reviewed and approved. A failed/rejected Instagram branch does not cancel X,
and successful Instagram delivery does not imply X succeeded.

X thread mode is disabled until its per-step schema/provider fixtures and
cadence policy are approved. Persist ordered PublicationSteps with immutable
reviewed text/asset references, one final-send marker per step, and remote reply
IDs. Send a step only after the previous step is conclusively recorded as
published. A lost response never authorizes a resend or later reply.

If a confirmed prefix exists and the next step fails conclusively before send,
record a partial-publication outcome; if any step may have been sent without a
confirmed result, record publication uncertainty. Never label the entire
package unpublished, retry its prefix, or fulfill the authorization as completely
published. The exact additional terminal states and reconciliation mappings must
be added to the forward schema before thread mode is enabled. There is no
automatic deletion/restart/continuation of partially published threads.

## Safety, retries, and reconciliation

External delivery is irreversible or externally stateful. The generic safety
rules—fenced claims, idempotency, safe retry classification, final-publication
marker, `publication_unknown`, and read-only reconciliation—are owned by
[Reliability and safety](reliability.md). This document does not redefine them.

In particular, once a final provider publication request may have reached the
provider, the attempt is never automatically repeated. The agent records
`publication_unknown`. An explicit dashboard command creates a durable
`ReconciliationRequest`; the worker appends read-only `ReconciliationCheck`
records and never publishes. A platform contract may prohibit automatic
resolution altogether; the initial Meta adapter does so. Otherwise, only an
unambiguous external match may resolve automatically. An ambiguous/not-found
case requires an auditable human decision, and another publication requires a
new explicit review approval and publication identity.

## Dashboard contract

The dashboard must distinguish human authorization from external activity:

- `PostRequest` is the human's immediate delivery authorization.
- `PostRecord` is the agent's delivery lifecycle.
- `PostAttempt` records a concrete adapter attempt.
- `PublicationResource` records remote/staged provider objects.
- `DeliveryCleanupTask` records transient-media cleanup.
- `ReconciliationRequest`, checks, and human decision record the uncertain
  publication investigation.

The only allowed human delivery actions are Post now, reject before
authorization, cancel before the final external request, and reconcile an
unknown result. The detailed UI is owned by [Dashboard and HAI](dashboard.md).

## Acceptance direction

Boundary tests must demonstrate that the agent claims only approved/due work,
delivers the exact reviewed manifest once, records every attempt/resource,
never mutates creative, handles a safe pre-final retry separately from an
uncertain final request, and makes cleanup/reconciliation independently
auditable.

## Related contracts

- [System guide](../system.md)
- [Data model](data-model.md)
- [Dashboard and HAI](dashboard.md)
- [Worker runtime](runtime.md)
- [Reliability and safety](reliability.md)
