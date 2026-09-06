# Meta: Facebook and Instagram

**Document role:** Tier 2 platform reference. It records provider account/API
facts and required configuration; it is not a Content Factory implementation
status report.

**Provider facts verified:** Facebook-Login authorization route and carousel
constraints, 2026-09-05; Cloudflare R2 public-media facts, 2026-09-05. The
configured Graph API version is a pinned local policy, not a claim that it is
Meta's newest version; recheck provider support before implementation or an
adapter change.

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
INSTAGRAM_GRAPH_API_VERSION=v24.0
```

The initial authorization needs these permissions:

```text
instagram_basic
instagram_content_publish
pages_show_list
pages_read_engagement
```

`INSTAGRAM_ACCESS_TOKEN` is a bearer secret and remains local only. Publication
requests do not need the app ID/secret when a validated token is already
provided; renewal will require the appropriate app credentials. The POC does
not automatically renew tokens. On onboarding/renewal, store a non-secret
`token_expires_at` value in validated local configuration or the safe account
health record. The dashboard warns 14 days before expiry, shows a high-visibility
failure state at 72 hours, and blocks a delivery attempt once the token is
expired.

For an owner-operated development app, the app administrator/developer/tester
can authorize their own connected assets without supporting unrelated accounts.
Opening the app to other people requires the appropriate Meta access and review
work; do not treat the POC token as a multi-account solution.

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

### Public-media environments

The current Cloudflare-managed `r2.dev` URL is permitted only for an explicit
development smoke test. It is not a production origin. Before unattended live
delivery, attach a dedicated custom domain controlled in the same Cloudflare
account (for example, `media.example.com`) to the R2 bucket, configure
`R2_PUBLIC_DOMAIN` to that HTTPS domain, validate retrieval of a temporary
probe object, and then disable `r2.dev` public access. Each staging key is
unique to its delivery attempt and asset; public reachability is required for
Meta retrieval but does not make the object canonical content.

Cloudflare documents `r2.dev` as a non-production, rate-limited development
endpoint. A custom domain is the required production path and enables
production access-management/caching controls. See [Cloudflare R2 public
buckets](https://developers.cloudflare.com/r2/buckets/public-buckets/) and
[R2 limits](https://developers.cloudflare.com/r2/platform/limits/).

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
- O2 uses a carousel with at most ten child images. Meta's current content
  publishing documentation limits a carousel to ten images/videos and requires
  media to be publicly accessible while it is fetched for publishing.
- Verify R2 first with `scripts/test_r2_public_asset_store.py`. It uploads,
  reads publicly, then deletes one probe image without calling Meta.
- Verify Meta credentials next with
  `scripts/test_instagram_credentials.py`. It only calls
  `GET /{INSTAGRAM_USER_ID}?fields=id,username` and never creates media.
- Do not place tokens in Git, documentation, dashboards, logs, or chat.

## Provider and operating decisions still required

- Additional Meta products only when a concrete pipeline needs them.

## Official Sources

- [Instagram Platform overview](https://developers.facebook.com/docs/instagram-platform/overview/)
- [Instagram content publishing](https://developers.facebook.com/docs/instagram-platform/content-publishing/)
- [Instagram API with Facebook Login](https://developers.facebook.com/docs/instagram-platform/instagram-api-with-facebook-login/)
- [Meta Graph API Explorer](https://developers.facebook.com/tools/explorer/)
- [Meta Instagram content publishing collection](https://www.postman.com/meta/instagram/documentation/6yqw8pt/instagram-api?entity=request-23987686-8365d531-b49f-4e07-8e76-19f8608947a3)
- [Cloudflare R2 public buckets](https://developers.cloudflare.com/r2/buckets/public-buckets/)
