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
  satisfy the selected platform/pipeline contract.

The agent gives the adapter only those immutable assets and metadata. It may
create transient delivery derivatives only when the platform contract permits
them and they were already represented in the reviewed final manifest. It never
repairs, converts, re-renders, reorders, or rewrites the package during
delivery.

## Generic delivery lifecycle

1. Claim one eligible `PostRecord` using its monotonic fencing version.
2. Revalidate the immutable approval binding, destination configuration,
   eligibility/cadence policy, and final asset manifest.
3. Create a `PostAttempt` before any external side effect.
4. Ask the selected platform adapter to stage assets, create platform resources,
   and perform its final publication operation.
5. Persist every safe remote ID/object as a `PublicationResource` and persist
   terminal outcome or `retry_wait` with bounded retry metadata when failure is
   provably pre-publication and retry-safe.
6. Create independent `DeliveryCleanupTask` records for transient staging
   objects. Cleanup does not alter confirmed publication state.

The initial POC accepts only **Post now** authorization. It records immediate
human intent; the versioned posting policy derives the record's earliest
eligible time. It never implicitly bypasses cadence, review, persistence,
validation, or adapter safety. An incomplete policy blocks the record before an
attempt rather than guessing. A future human scheduling feature requires a new
versioned command and data-model contract; it is not an implicit mode of Post
now.

## Platform-adapter contract

An adapter is a small platform-specific service. It may use only its provided,
validated delivery input and its local configuration. It returns a structured
attempt result containing safe resource identifiers, a typed outcome, and the
point reached in the external workflow.

The adapter owns provider calls, provider-specific staging, container/resource
semantics, readiness polling, and provider error mapping. It must not make an
editorial decision or create a second publication. Provider account,
permission, token, API, and media requirements belong in the relevant
`platforms/` reference; pipeline-specific format requirements belong in the
relevant `pipelines/` contract.

The first adapter is Instagram carousel delivery. It is specified jointly by
the [O2 English Instagram pipeline](../pipelines/o2-english-instagram.md) and
the [Meta platform reference](../platforms/meta.md). Future adapters (for
example, another social platform) implement this same boundary without changing
the review, request, record, or Posting Agent contract.

## Safety, retries, and reconciliation

External delivery is irreversible or externally stateful. The generic safety
rules—fenced claims, idempotency, safe retry classification, final-publication
marker, `publication_unknown`, and read-only reconciliation—are owned by
[Reliability and safety](reliability.md). This document does not redefine them.

In particular, once a final provider publication request may have reached the
provider, the attempt is never automatically repeated. The agent records
`publication_unknown`. An explicit dashboard command creates a durable
`ReconciliationRequest`; the worker appends read-only `ReconciliationCheck`
records and never publishes. Only an unambiguous external match may resolve
automatically. An ambiguous/not-found case requires an auditable human
decision, and another publication requires a new explicit review approval and
publication identity.

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
