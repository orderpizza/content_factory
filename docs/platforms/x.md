# X Platform Reference

**Document role:** Tier 2 draft provider-integration reference.
**Owner:** X account authorization, media upload, posting, safe resource audit,
and read-only reconciliation. **Provider facts verified:** not yet verified for
the configured application/account/API access. No endpoint, entitlement, price,
quota, or limit in this document is asserted as currently available.

## Approved architecture

X is a Phase 1 output/distribution target. The output adapter creates native
image + post text, optionally an image + thread, under
[Platform outputs](../specs/platform-outputs.md). A separate delivery adapter
sends the exact human-approved package through [Posting](../specs/posting.md).
It does not depend on Instagram containers or assume R2 public-URL staging.

Credentials stay local behind named secret references. Configure the actual
X account separately from the domain pipeline and any Instagram destination.
Do not invent handles or reuse the Instagram identity as an X account ID.

## Provider verification required before implementation/enablement

Record dated official documentation links, the chosen authorization route,
configured access/entitlements, request/response fixtures, and typed failure
mapping for:

- account identity and write permissions, token lifecycle, scopes, and safe
  read-only readiness checks;
- supported static-image upload, media readiness/expiry, MIME/dimension/byte
  limits, alt text, and attachment semantics;
- exact native text-length counting, URL handling, post creation responses,
  rate limits, cost/quota policy, and any provider idempotency guarantees;
- a durable marker before public post creation, confirmation IDs, ambiguous
  timeout/lost-response handling, and read-only reconciliation queries;
- safe cleanup of unneeded upload resources, if the provider supports it; and
- for optional threads, ordered reply creation and per-step publication audit,
  partial-prefix failure, cadence accounting, and reconciliation evidence.

Do not assume provider exactly-once delivery or automatically retry a possibly
sent post. Apply the shared conservative `publication_unknown` boundary even if
no matching post can immediately be found. Public account checks and temporary
uploads must not be disguised live-publication tests.

## Activation

A destination is blocked until its reviewed provider profile and secret refs
resolve, schema/adapter tests pass, and current readiness is valid. Thread mode
has an additional disabled-by-default safety gate. Live testing requires explicit
human authorization for the exact package/account and may publish real content.
Provider verification is an implementation task; it does not reopen the user's
decision to include X in Phase 1.
