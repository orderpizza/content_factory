# Meta: Facebook and Instagram

**Document role:** Tier 2 platform reference. It records provider account/API
facts and required configuration. Current conformance is stated explicitly
below; unqualified protocol detail remains the target contract.

**Provider facts verified:** Facebook-Login authorization route and carousel
constraints, 2026-09-05; Cloudflare R2 public-media facts, 2026-09-13. The
configured Graph API version is a pinned local policy, not a claim that it is
Meta's newest version; recheck provider support before live activation or an
adapter change.

**Current adapter subset:** schema v4 freezes the numeric Instagram account,
Graph version, token reference, dedicated R2 HTTPS origin, and posting policy.
The fake-tested adapter stages exact reviewed JPEGs, creates/polls ordered child
and parent containers, commits the final-send marker, calls `media_publish`, and
audits results/resources/cleanup. Readiness makes one account-identity GET and an
explicit transient R2 put/head/public-get/delete probe. The September 2026 Mac
check passed that complete relay probe through the owner's `r2.dev` origin;
the read-only Meta identity check returned OAuth 190 (token could not be
decrypted) with both Bearer and query-token authentication. See
[current operational evidence](../current-state.md#genuine-human-review-and-external-gates).
Current readiness does not inspect token
expiry/scopes, app-review state, quota, optional custom-domain cache rules, or
the bucket lifecycle setting; those remain operator gates. No live public
publication has been verified.

## Account Model

```text
Facebook personal identity -- administers --> Facebook Page -- linked to --> Instagram Professional account
Meta developer app -- authorized Page access token --> Meta Graph API -- publishes to --> Instagram account
```

- A **Facebook personal identity** is the human administrator who signs in and
  grants the app permission. It is not a posting destination.
- A **Facebook Page** is the brand asset that establishes the current
  Facebook-Login authorization relationship to the Instagram account. It does
  not receive a duplicate post from Content Factory.
- An **Instagram Professional account** (Business or Creator) is the actual
  delivery target. A personal Instagram account cannot use this API path.
- A **Meta developer app** is Content Factory's technical identity. It
  requests permissions and issues tokens; it is not a social channel.
- A **Meta Business Portfolio** is an optional organizational layer for
  assigning people and managing Pages, Instagram accounts, apps, and ad
  accounts. It is useful once brands, staff, or clients multiply, but it is
  not a current POC dependency.

## Authorization Contract

The approved adapter uses the **Instagram API with Facebook Login** and
calls `graph.facebook.com`. It requires a Professional Instagram account linked
to a Page administered by the authorizing Facebook identity.

```dotenv
INSTAGRAM_USER_ID=<numeric Instagram Professional Account ID; not @handle>
INSTAGRAM_ACCESS_TOKEN=<Page access token for the linked Facebook Page>
```

The initial authorization needs these permissions:

```text
instagram_basic
instagram_content_publish
pages_show_list
pages_read_engagement
```

`INSTAGRAM_ACCESS_TOKEN` is a bearer secret and remains local only.
`INSTAGRAM_USER_ID` and Graph API version are non-secret destination settings
in the activated configuration release. Publication requests do not need the
app ID/secret when a validated token is already provided; renewal will require
the appropriate app credentials. The POC does
not automatically renew tokens. The target readiness design stores a non-secret
`token_expires_at` and provides advance expiry warnings; the current monitor
records account identity and a six-hour readiness expiry only. The Posting Agent
does block stale/non-ready destinations, but token-expiry warning/renewal remains
an operator responsibility.

For an owner-operated development app, the app administrator/developer/tester
can authorize their own connected assets without supporting unrelated accounts.
Opening the app to other people requires the appropriate Meta access and review
work; do not treat the POC token as a multi-account solution.

## Phase 1 ownership

This provider adapter serves any configured domain's Instagram output. The
domain pipeline ID is not an Instagram account or format; native carousel/caption
composition belongs to [Platform outputs](../specs/platform-outputs.md).
Its new static profile must match the reviewed 1080×1350 delivery contract
before activation. The old 1080×1920 profile is a legacy reference, not an
implicit conversion path. No provider facts are newly verified by this
architecture-only update; retain the verification gate above.

## Human-Reviewed Publishing Contract

This is Meta-specific adapter behavior. The generic request, attempt, staging,
cleanup, and reconciliation lifecycle is owned by the
[Posting Agent specification](../specs/posting.md). The deterministic renderer
creates and manifests the final delivery-ready JPEGs before human review. The
reviewer sees those exact files, caption, hashtags, account, package hash, and
manifest hash.

After approval, the Meta adapter may only reverify and stage those JPEG bytes;
it cannot convert, regenerate, repair, or otherwise alter them. The human
approval transaction creates one publication identity. Immediately before
`media_publish`, the Posting Agent persists a final-request marker. Any timeout,
lost response, or local persistence failure after that marker becomes terminal
`publication_unknown` and is never automatically retried.

A human may request a separate read-only reconciliation lookup. Its worker can
inspect the configured account and persist evidence, but it cannot create a
container, call `media_publish`, or authorize another attempt. An unresolved
lookup remains blocked. Only a human-confirmed not-found result may proceed to
another explicit review approval and new publication identity.

Meta must be able to fetch each staged media URL anonymously while publishing.
The adapter uploads each already-reviewed JPEG to a temporary public HTTPS R2
object, creates and audits ordered child and carousel-parent resources, waits
for provider readiness, then calls `media_publish` under the safety boundary
above. The canonical package/assets remain local; R2 is only a short-lived
delivery relay and cleanup is an independent audited task.

### Carousel adapter protocol — `meta_instagram_carousel_v1`

`META_GRAPH_API_VERSION` is a required non-secret activated-release value in
the form `vNN.N`; every request below uses
`https://graph.facebook.com/<META_GRAPH_API_VERSION>`. The Readiness Monitor
does a read-only version/account check after activation. The adapter rejects an
unverified, expired, or changed version rather than falling back to an
unversioned endpoint.

For every reviewed delivery JPEG in ordinal order, send:

```text
POST /<INSTAGRAM_USER_ID>/media
access_token=<secret, never persisted>
image_url=<verified anonymous R2 HTTPS URL>
is_carousel_item=true
```

The response must contain a non-empty string `id`; persist it immediately as a
`PublicationResource(role=meta_child_container, asset_ordinal=n)`. Any
transport failure before a confirmed response is retryable only while the
adapter can prove no child ID was returned; otherwise retain the observed
resource and fail pre-final safely. After all children are ready, send:

```text
POST /<INSTAGRAM_USER_ID>/media
access_token=<secret, never persisted>
media_type=CAROUSEL
children=<child IDs in reviewed ordinal order, comma-separated>
caption=<immutable package caption>
```

Persist its returned `id` as `meta_parent_container`. The adapter polls each
child and then the parent with `GET /<container-id>?fields=id,status_code,status`
every 10 seconds, subject to both a 10-minute per-resource ceiling and the
Posting execution's **4-minute overall deadline**, whichever is earlier.
The 4-minute budget includes staging, all child/parent polling and final-call
admission; it is not restarted per image. Clip each request timeout/wait to
the remaining budget. Persist a safe pre-final failure with retained resource
IDs when the budget runs out; do not start a final call without remaining
time and live unexpired authorization. Lease renewal does not extend this
execution deadline. A possibly sent final request remains published/unknown,
not retryable, even if its response arrives after the deadline. These are local
execution limits, not newly verified provider timing guarantees.
`FINISHED` is ready; `IN_PROGRESS`
continues; `ERROR` or `EXPIRED` is a terminal pre-final failure; any unknown
status, malformed response, or timeout is retryable only before the final
marker and retains all resources. Poll response bodies are reduced to safe
status, ID, and bounded error summary/hash.

Only after parent `FINISHED` and the Posting Agent final-marker transaction,
send:

```text
POST /<INSTAGRAM_USER_ID>/media_publish
access_token=<secret, never persisted>
creation_id=<meta_parent_container ID>
```

A response `id` creates the published external-ID result. Timeout, connection
loss, malformed response, or persistence failure after the final marker is
`publication_unknown`; it is never retried. Authentication/permission and
unsupported-input errors are terminal; rate-limit/server and explicitly
pre-request transport errors are retryable only before the final marker. Every
provider error records HTTP status, safe provider code/subcode when returned,
stage, retry classification, and redacted bounded message.

The target reconciliation search uses `GET /<INSTAGRAM_USER_ID>/media` with fields
`id,media_type,timestamp,caption,permalink,children{id}` and an explicit
`limit=25`, following `paging.next` no more than four pages within the bounded
attempt time window. The current worker fetches only the first 25 results and
compares exact caption text; it does not implement pagination or the bounded
time filter. It hashes returned captions locally, stores no raw token
or response body, and follows the human-only reconciliation rule above.

### Public-media environments

On 2026-09-13 the owner selected the existing Cloudflare-managed `r2.dev` URL
for this small local PoC. Both the CLI and persisted configuration validator
accept that origin in real-account mode. Purchasing a domain is not required.
Origin-only HTTPS, successful public-byte verification, safe cleanup, and exact
Post now authorization remain mandatory. Each staging key is unique to its
delivery attempt and asset; public reachability is required for Meta retrieval
but does not make the object canonical content.

Cloudflare documents `r2.dev` as a non-production, rate-limited development
endpoint. Accepting it here is a local PoC tradeoff, not a production-service
guarantee from Cloudflare. If rate limiting interferes with Meta retrieval or
volume grows, move to a custom domain through a reviewed configuration release.
A custom domain enables additional access-management/caching controls.
See [Cloudflare R2 public
buckets](https://developers.cloudflare.com/r2/buckets/public-buckets/) and
[R2 limits](https://developers.cloudflare.com/r2/platform/limits/).

### Transient R2 relay — `r2_transient_delivery_v1`

For every asset, the adapter creates one object key exactly in this shape:

```text
instagram-transient/<post-record-id>/<attempt-number>/<asset-ordinal>-<32-lowercase-hex-random-bytes>.jpg
```

The random suffix comes from the operating-system CSPRNG and is never reused,
even on a retry. The key contains no caption, account handle, content title,
token, or signed URL. Before upload, the adapter verifies that the canonical
reviewed asset is `image/jpeg`, 1080×1350, has the manifest byte length, and
has the manifest SHA-256. It uploads exactly those bytes with
`Content-Type: image/jpeg`, `Cache-Control: no-store, max-age=0`, and no
metadata other than the SHA-256 and immutable attempt/resource identifiers.

After upload, it performs an authenticated R2 HEAD and compares byte length,
content type, and metadata hash. It then performs
one anonymous HTTPS GET through `R2_PUBLIC_DOMAIN`, follows no redirect, caps
the response at the expected byte length, hashes the returned bytes, and
requires an exact match before it gives the URL to Meta. This probe is an
attempt resource and is never logged as a reusable signed/public URL.

The current PoC uses the selected `r2.dev` HTTPS origin. If a custom domain is
used later, its Cloudflare cache rule should bypass cache for
`instagram-transient/*`; the response header above is the second guard.
Current configuration validates origin-only HTTPS; current readiness proves an
anonymous temporary probe has exact bytes and no redirect. Domain ownership
and cache-rule inspection are not automated.

Cleanup DELETE is idempotent. The Cleanup Worker records deletion time and
performs an authenticated HEAD that must return `404`/`NoSuchKey`; it does not
rely on a public GET because intermediate caches may outlive deletion. The
custom-domain cache-bypass rule, when applicable, is verified at activation and after any cache
configuration change. The bucket lifecycle rule for this prefix must be
enabled with a seven-day expiration backstop. Current readiness does not
retrieve that rule, so the owner must verify it in Cloudflare before unattended
use.

### Reconciliation — `meta_reconciliation_v1`

For the initial Meta adapter, reconciliation is **human-only**. The worker may
make read-only provider queries scoped to the configured Instagram account and
to the bounded time interval from ten minutes before the attempt began through
24 hours after the final-request marker. It records candidate media IDs,
timestamps, media type, caption hash/length where returned, child count where
returned, permalink, query version, and safe response summary.

It never automatically changes `publication_unknown` to `published` or
`not_published`. Even a plausible matching carousel is not proof that it is
the exact local attempt. The dashboard presents the evidence and a human records
`published`, `not_published_cancel`, or `leave_unknown`. A later publication
always requires a fresh human review approval and publication identity.

## Safety and Verification

- `media_publish` creates a real Instagram post. There is no private/draft
  publication outcome for this carousel route. A live owner-operated smoke
  test on the actual account is public and requires explicit **Post now**
  approval for that exact package. Use a separate test account if a public test
  post is unacceptable.
- The Instagram output adapter uses a carousel with at most ten child images. Meta's current content
  publishing documentation limits a carousel to ten images/videos and requires
  media to be publicly accessible while it is fetched for publishing.
- Verify R2 first with `scripts/test_r2_public_asset_store.py`. It uploads,
  reads publicly, then deletes one probe image without calling Meta.
- Verify Meta credentials next with
  `scripts/test_instagram_credentials.py`. It only calls
  `GET /{INSTAGRAM_USER_ID}?fields=id,username` and never creates media.
- Do not place tokens in Git, documentation, dashboards, logs, or chat.

## Provider and operating decisions still required

- Additional Meta products only when a concrete output/delivery contract needs them.

## Official Sources

- [Instagram Platform overview](https://developers.facebook.com/docs/instagram-platform/overview/)
- [Instagram content publishing](https://developers.facebook.com/docs/instagram-platform/content-publishing/)
- [Instagram API with Facebook Login](https://developers.facebook.com/docs/instagram-platform/instagram-api-with-facebook-login/)
- [Meta Graph API Explorer](https://developers.facebook.com/tools/explorer/)
- [Meta Instagram content publishing collection](https://www.postman.com/meta/instagram/documentation/6yqw8pt/instagram-api?entity=request-23987686-8365d531-b49f-4e07-8e76-19f8608947a3)
- [Cloudflare R2 public buckets](https://developers.cloudflare.com/r2/buckets/public-buckets/)
