# X Platform Reference

**Document role:** Tier 2 provider-integration reference.
**Owner:** X account authorization, media upload, posting, safe resource audit,
and read-only reconciliation. **Documentation reviewed:** official v2 media,
post, access, and character-counting references on 2026-09-13. The configured
application/account entitlements, live quota, token, and write behavior remain
unverified.

[Current implementation and operations](../current-state.md) owns as-built
adapter status and operational evidence. This reference defines provider facts
and target integration requirements; it does not assert live enablement.

## Approved architecture

X is a Phase 1 output/distribution target. The output adapter creates native
image + post text, optionally an image + thread, under
[Platform outputs](../specs/platform-outputs.md). A separate delivery adapter
sends the exact human-approved package through [Posting](../specs/posting.md).
It does not depend on Instagram containers or assume R2 public-URL staging.

Credentials stay local behind named secret references. Configure the actual
X account separately from the domain pipeline and any Instagram destination.
Do not invent handles or reuse the Instagram identity as an X account ID.

## Target adapter contract

The target contract freezes one numeric user ID, `X_USER_ACCESS_TOKEN`, the
`https://api.x.com` origin, v2 media/post paths, a 5 MB image ceiling, and a
finite posting policy. Readiness calls `GET /2/users/me` and requires the exact
configured user ID. The delivery adapter must:

1. revalidates the one reviewed 1200×675 JPEG and its hash/byte manifest;
2. rejects locally weighted text above 280;
3. sends base64 media to `POST /2/media/upload` and requires numeric `data.id`;
4. sends reviewed alt text to `POST /2/media/metadata`;
5. commits the durable final-publication marker; and
6. sends the immutable text/media ID to `POST /2/tweets`.

Any possibly sent final request becomes `publication_unknown` and is not
retried. On explicit human request, reconciliation reads up to ten recent user
posts and compares exact text, but every result still requires human resolution.
X threads are not implemented. The local weighted counter covers URL weighting,
combining marks, and wide characters but is not a complete vendored
`twitter-text` implementation; live provider acceptance must include boundary
strings before the first public post.

## Provider verification required before live enablement

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
Provider verification is an activation task; it does not reopen the user's
decision to include X in Phase 1.

## Official sources

- [Upload media](https://docs.x.com/x-api/media/upload-media)
- [Create a post](https://docs.x.com/x-api/posts/create-or-edit-post)
- [Media overview and metadata](https://docs.x.com/x-api/media/introduction)
- [API access and authentication](https://docs.x.com/x-api/getting-started/getting-access)
- [Character counting](https://docs.x.com/fundamentals/counting-characters)
- [`twitter-text` v3 configuration](https://github.com/twitter/twitter-text/blob/master/config/v3.json)
