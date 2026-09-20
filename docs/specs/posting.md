# Posting and Reconciliation

**Owner:** Delivery authorization, attempts, remote-resource audit and uncertain outcomes.
**Implementation:** `src/workflow/store.py` and `src/workflow/delivery.py`.
Credentialed delivery is composed only with explicit production/delivery flags;
see [runtime](runtime.md#workflow-composition).

## Boundary

```text
exact reviewed package + Post now
  → immutable PostRequest + pending PostRecord
  → Posting Agent → PostAttempt → platform staging
  → durable final-request marker → provider publication
  → published or publication_unknown
  → independent cleanup / explicit read-only reconciliation
```

The dashboard persists commands, never invokes a worker/provider. PostRequest
is human authorization; PostRecord is the claimed delivery lifecycle. Each
destination requires its own exact authorization. Posting never generates or
modifies text, hashtags, alt text or images.

## Preconditions and cadence

Authorization and attempt preparation verify the package/render/asset hashes,
destination/profile binding, current persisted readiness and posting policy.
Synthetic packages cannot authorize delivery. Missing or changed reviewed assets
are rejected, not regenerated. A transient readiness failure does not mean the
human rejected the content.

`configure_production.py` freezes an account timezone, daily cap, minimum
interval and authorization lifetime. Its defaults are Asia/Seoul, one post per
account-day, 1,200 minutes between posts and 48 hours of authorization.
Dashboard timestamps are UTC. Cadence is per platform/account, not per domain.
Post now means the earliest policy-compliant delivery, not permission to bypass
cadence. Confirmed or uncertain sends reserve cadence; safe pre-final failures
do not represent a published slot.

Reviews expire 14 days after creation. Authorization expiry is checked before
claim and final send. Expiry cannot erase a possible public side effect.
The schema supports review-cycle numbers, but no fresh-review-cycle dashboard
command is implemented. Renewal/reuse belongs in [the roadmap](../plans/target-implementation.md).

## Attempt and cancellation

1. Claim due work with an owner, version and live lease.
2. Revalidate authorization, readiness, immutable assets and policy.
3. Persist an attempt before external staging; persist resource IDs as they are obtained.
4. Recheck claim, request, thread and expiry in a fenced transaction immediately
   before the public call. Commit `final_publication_request_sent_at` first.
5. Record confirmed publication or uncertainty and schedule staging cleanup.

Before the final marker, an exact row-versioned cancellation can cancel the
request, delivery record and active pre-final attempt. Staged R2 objects receive
cleanup tasks; provider containers remain audited. If cancellation wins, the
worker cannot send. If the final marker wins, cancellation is refused.

A safe pre-final failure may retry within its attempt limit. Once the final
request might have reached the provider, a timeout, lost response or failed local
commit means `publication_unknown`, never automatic retry. Lease recovery
preserves this distinction. A cleanup failure never changes a confirmed post
to failed.

## Adapters

| Adapter | Staging | Final public operation |
| --- | --- | --- |
| [Instagram](../platforms/meta.md) | Verified transient R2 JPEGs, child containers, carousel parent | `media_publish` |
| [X](../platforms/x.md) | Native media upload and metadata | `POST /2/tweets` |

Both use only reviewed input. Provider-specific limits, timeout behavior and
readiness checks live in those references, not in domain pipelines.
One adapter call publishes one carousel or one X post. X threads are unsupported.

## Reconciliation

A dashboard command creates a durable ReconciliationRequest for an uncertain
post. The worker performs bounded read-only lookups and appends checks; it never
publishes or creates media. Current adapters compare exact caption/post text
against one page of recent account results. Text equality and absence of a match
are not publication-identity proof.

All current lookups require human resolution: `published`,
`not_published_cancel`, or `leave_unknown`. Even a stored check classification
of `confirmed_not_published` does not authorize retry or automatically resolve
the post. A confirmed-not-published decision cancels that authorization, not
requeues it. There is no generic dashboard command to renew the same package's
review; broader recovery is future work.

## Ownership and limits

[Data model](data-model.md) owns persisted identities and transaction boundaries.
[Reliability](reliability.md) owns model accounting, storage admission and
cross-cutting safety. [Dashboard](dashboard.md) owns visible controls.

No scheduling UI, automatic token renewal, unattended approval, cross-revision
canonical reuse or multi-post publication is implemented. Offline adapter tests
do not verify live credentials, permissions, provider entitlements or public
delivery. Those require separate authorized acceptance.
