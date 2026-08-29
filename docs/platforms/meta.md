# Meta: Facebook and Instagram

**Content Factory status:** Active only for the o2 English Instagram carousel
POC. Facebook publishing, Threads, messaging, advertising, token renewal, and
multi-account management are not implemented.

**Last verified:** 2026-08-27. The local read-only credential check previously
resolved the configured `@o2_english` Professional account. Recheck the
official sources below before changing the adapter or Meta configuration.

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

## Current Authorization Contract

The implemented adapter uses the **Instagram API with Facebook Login** and
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

`INSTAGRAM_ACCESS_TOKEN` is a bearer secret and remains local only. The app ID
and app secret are not needed by the current delivery worker because it already
has a token; they will be needed when token renewal is implemented.

For an owner-operated development app, the app administrator/developer/tester
can authorize their own connected assets without supporting unrelated accounts.
Opening the app to other people requires the appropriate Meta access and review
work; do not treat the POC token as a multi-account solution.

## Current Publishing Path

1. The Posting Agent accepts a ready o2 Instagram package with 5–8 rendered
   slides (the API accepts a carousel of 2–10 items).
2. It converts the local PNG slides to JPEG and stages each at a temporary,
   public HTTPS R2 URL.
3. Meta creates child media containers, then a parent carousel container.
4. The agent polls the parent status and calls `media_publish` only after it is
   ready.
5. SQLite records attempts, container IDs, and the final external media ID.
6. The agent deletes the transient R2 objects after the attempt.

Meta must be able to fetch each media URL anonymously while publishing. The
canonical content package and rendered assets remain local; R2 is only a
short-lived delivery relay.

## Approved Human-Reviewed Target

The current adapter converts PNG files to JPEG during delivery. That is a
current implementation fact, not the approved review boundary. In the target
Content Factory flow, the deterministic renderer creates and manifests the
final delivery-ready JPEGs before human review. The reviewer sees those exact
files, caption, hashtags, account, package hash, and manifest hash.

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

## Safety and Verification

- `media_publish` creates a real Instagram post. There is no private/draft
  publication outcome for this carousel route. Use a separate test account if
  a real post is unacceptable.
- Verify R2 first with `scripts/test_r2_public_asset_store.py`. It uploads,
  reads publicly, then deletes one probe image without calling Meta.
- Verify Meta credentials next with
  `scripts/test_instagram_credentials.py`. It only calls
  `GET /{INSTAGRAM_USER_ID}?fields=id,username` and never creates media.
- Do not place tokens in Git, documentation, dashboards, logs, or chat.

## Operational Gaps to Revisit

- Token expiry, renewal, secure rotation, and expiry monitoring.
- Production public-media setup and retention policy. `r2.dev` is appropriate
  only for development and is rate-limited by Cloudflare.
- A deliberate test-account policy before the first live publication.
- Implementation of final-JPEG review binding, the human approval gate, and
  read-only uncertain-publication reconciliation.
- Additional Meta products only when a concrete pipeline needs them.

## Official Sources

- [Instagram Platform overview](https://developers.facebook.com/docs/instagram-platform/overview/)
- [Instagram content publishing](https://developers.facebook.com/docs/instagram-platform/content-publishing/)
- [Instagram API with Facebook Login](https://developers.facebook.com/docs/instagram-platform/instagram-api-with-facebook-login/)
- [Meta Graph API Explorer](https://developers.facebook.com/tools/explorer/)
- [Cloudflare R2 public buckets](https://developers.cloudflare.com/r2/buckets/public-buckets/)
