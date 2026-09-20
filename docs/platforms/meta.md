# Instagram and R2 Integration

**Owner:** Implemented Meta/R2 adapter behavior and operator prerequisites.
**Code:** `src/workflow/delivery.py`, `src/workflow/readiness.py`.
These are local integration rules; live provider availability and account
permissions require explicit verification before delivery.

## Identity and credentials

The configured adapter uses `graph.facebook.com/<META_GRAPH_API_VERSION>`
for the Facebook-Login Instagram Professional account route. It does not publish
to a Facebook Page. Keep these identities separate:

| Setting | Meaning |
| --- | --- |
| `INSTAGRAM_ACCOUNT_KEY` | Internal destination label, not a Page ID or pipeline ID |
| `INSTAGRAM_USER_ID` | Numeric Instagram Professional account ID |
| `INSTAGRAM_ACCESS_TOKEN` | Credential authorized for that account |
| `META_GRAPH_API_VERSION` | Explicit version such as vNN.N; no unversioned fallback |

For this authorization route, verify the linked Page/account relationship and
required permissions during activation. Token acquisition/renewal is an operator
task; the application does not renew tokens or track actual token expiry.
Persisted readiness is time-limited, not proof a token cannot expire.

Delivery/readiness use a Bearer Authorization header. The explicit credential
diagnostic can compare header/query transport; a diagnostic SHA-256 fingerprint
is never prepended to the transmitted credential. Do not paste tokens in ideas,
logs or source configuration.

## Readiness

A real destination requires the exact configured account/profile and current
persisted readiness. Live checks are explicit operator actions; routine tests
use fakes. R2 probing uploads a temporary object, verifies it and deletes it.
It therefore requires explicit probe authorization, not just a read-only label.

Review and Post now concern exact final assets and copy. Readiness does not
authorize publication. [Posting](../specs/posting.md) owns that boundary.

## Carousel protocol

The adapter stages the reviewed JPEGs in ordinal order:

1. Persist each intended R2 key before upload; verify exact local bytes/hash.
2. Upload and verify public bytes, then create `/<ig-id>/media` children with
   `image_url` and `is_carousel_item=true`.
3. Persist returned child IDs and poll each for `FINISHED`.
4. Create a carousel parent with ordered child IDs and the immutable caption;
   persist its ID and poll for `FINISHED`.
5. The Posting Agent commits its fenced final-request marker, then the adapter
   calls `/<ig-id>/media_publish` with that parent ID.

`IN_PROGRESS` polls wait up to ten seconds. Error/expired or unknown statuses
fail pre-final. A 240-second deadline is shared by container staging/polling;
individual R2 operations have their own transport timeouts, and final publication
uses a separate 20-second timeout. This is not a strict whole-attempt deadline.

Possibly sent publication with no conclusive persisted result becomes
`publication_unknown`; it is never automatically repeated. Provider containers
remain audited. Cleanup of R2 staging is independent.

## Transient R2 relay

R2 stores temporary transport copies, never canonical assets. Configuration
accepts an HTTPS origin, including the selected `r2.dev` origin; a purchased
domain is not required for this PoC. Public retrieval must return exact bytes
without redirects. Reachability does not guarantee future provider retrieval.

Keys use:

```text
instagram-transient/<post-record-id>/<attempt-number>/<ordinal>-<64-hex-random-suffix>.jpg
```

The suffix comes from 32 OS-random bytes. Uploads use `image/jpeg`,
`Cache-Control: no-store, max-age=0`, asset SHA-256 and immutable attempt metadata.
Authenticated HEAD checks length/type/hash; anonymous GET checks exact bytes
before Meta receives the URL. R2 credentials and signed URLs are not publication
evidence.

Cleanup DELETE is idempotent and verified by authenticated HEAD
(`404`/`NoSuchKey`), not public cache behavior. The application does not inspect
bucket lifecycle rules or custom-domain cache configuration. Verify a lifecycle
backstop and public-endpoint reliability before unattended use; see
[future operations](../plans/target-implementation.md#delivery-acceptance).

## Reconciliation

The worker reads the first 25 account media results and compares exact caption
text. It records bounded matching IDs and a text hash, not the provider response.
It does not paginate, enforce a search time window or establish publication
identity from text alone. Every result requires human resolution under
[posting](../specs/posting.md#reconciliation).

## External references for activation

Recheck provider requirements and account permissions when enabling or changing
the integration; these links are not a live-readiness assertion.

- [Meta content publishing](https://developers.facebook.com/docs/instagram-platform/instagram-api-with-facebook-login/content-publishing/)
- [Meta Facebook-Login route](https://developers.facebook.com/docs/instagram-platform/instagram-api-with-facebook-login/)
- [R2 public buckets](https://developers.cloudflare.com/r2/buckets/public-buckets/)
- [R2 limits](https://developers.cloudflare.com/r2/platform/limits/)
