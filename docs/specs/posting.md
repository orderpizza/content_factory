# Posting and delivery boundary

**Owner:** Exact-asset authorization, offline delivery rehearsal, preserved delivery
state machine, and the future Instagram adapter contract.

## Current contract and architecture map

The live workflow still ends at review PNGs. The dashboard reads evidence and
persists commands; it never constructs a provider, converts assets or sends posts.
Its CSRF, path containment and exact hash checks are unchanged. Phase 3A adds only
explicit offline entrypoints, documented in [operations](../operations.md#offline-delivery-rehearsal).

| Boundary | Existing infrastructure and invariant |
| --- | --- |
| Editorial acceptance | `decide_review` / `approve_review` records a human decision, with row version and command receipt. It creates no PostRequest. PNG approval covers only those PNG bytes. |
| Deliverable review | Package and manifest hashes bind caption, alt text and ordered `delivery_jpeg` assets. Post now reopens and validates actual JPEGs against persisted size/hash/MIME/geometry, package count and destination. English supports 4–6 slides; other domains retain the 4–14 local content bound. These are local contracts, not claims of provider eligibility. |
| Explicit Post now | `authorize_post_now` atomically approves one awaiting review and creates a unique publication identity, PostRequest and PostRecord. It checks current configuration, visual approval, readiness, expiry and cadence. Replayed command IDs return the same record; changed input is rejected. |
| Preparation/staging | `CredentialedPostingAgent` claims work, rechecks artifacts/authorization and records PostAttempt. `R2TransientRelay` uploads exact JPEG bytes, checks authenticated HEAD and anonymous exact-byte fetch. Staging never changes creative. |
| Final send | A fenced transaction rechecks live lease, thread, cancellation, expiry and readiness, then commits the final-send marker before calling `publish`. Success stores a receipt ID; any potentially accepted final call becomes `publication_unknown`, never automatic retry. |
| Recovery | Expired claims before the final marker can retry within limits. Recovery after it is conservative, including a crash between marker and actual send. Pre-final cancellation wins. |
| Reconciliation | `PublicationReconciliationWorker` records unavailable lookup evidence and hands uncertainty to a human. Explicit decisions can confirm publication, cancel as not published, or leave unknown. None reposts automatically. |
| Cleanup | Attempt resources and cleanup tasks remain separately durable. Cleanup can remove staged objects after success, failure, cancellation or uncertainty; it never reverses a publication or resolves its outcome. |

The production catalog remains closed `production_configuration_v2` with
`adapter_version=unimplemented`. No OAuth, live adapter, production delivery CLI
or real capability probe is enabled. Configuration visual acceptance is separate
from exact post authorization; see [configuration](configuration.md#preserved-production-configuration).

## Offline artifact preparation and approval boundary

`workflow.delivery_artifacts` exports a **new, unapproved** JPEG candidate from a
frozen English PNG review using a read-only database connection. It verifies the
source review/package/manifest and stored asset list, contained paths, contiguous
ordinals, MIME, SHA256, bounded size and 1080×1350 geometry. Only single RGB PNGs
without ICC/EXIF metadata are currently accepted; unsupported modes/metadata fail
rather than silently changing appearance. It performs no resizing, overlays or
rendering. The existing PNGs and database are untouched.

Profile `instagram_english_jpeg_v1` writes ordered `slide-01.jpg` etc. using JPEG
quality 92, 4:4:4, no optimization/progressive encoding or copied metadata. Byte
determinism is scoped to the recorded Pillow/libjpeg build. A new directory is
required; an interrupted directory has no completed `candidate.json` and must not
be treated as a complete candidate. No existing directory is overwritten.

`candidate.json` contains a new candidate package and exact asset manifest with
source database/review/render/package identity, source PNG hashes, encoder version,
JPEG sizes/hashes, caption and alt text. Its `delivery_ready=true` describes the
**candidate's technical format**, not approval. `requires_new_review=true` and
`authorization=null` are explicit. Neither this flag nor deterministic conversion
can authorize sending. A reviewer must inspect every JPEG in order plus copy and
alt text, then authorize that exact immutable package for the exact destination.

**Production promotion remains blocked deliberately:** current schema 18 enforces
one immutable package per output, one storyboard per package/output and one render
per storyboard. The active package is non-deliverable. Mutating it, replacing its
manifest, or attaching JPEGs to its approved PNG review would break authorization.
Phase 3A introduces no schema migration and no candidate import into operator DBs.
Before real integration, add a narrowly modeled append-only delivery revision
referencing the original package/render and candidate hashes, with its own review
identity and PostRequest binding. Design an explicit, reversible migration and
backup procedure; do not reset operator data or fabricate new editorial generation
lineage to evade the unique constraints. Alternatively, prove an explicit new
output/package path preserves all lineage. Either choice requires fresh JPEG
review; old PNG approval is never copied.

## Isolated simulation

`simulate_delivery.py init` creates a fresh workspace, schema-18 DB, synthetic
PNGs, prepared JPEGs and an **awaiting** JPEG review using the shared existing
fixture lineage. No automatic review or Post now occurs. This synthetic fixture
bypasses generation deliberately and is not a production package importer.

Only the literal destination `instagram:simulation`, provider ID `0`, and packages
marked `execution_mode=simulation` are accepted by the rehearsal. Workspace marker
and DB identity are checked before writes. There is no arbitrary database argument,
current-DB discovery, environment loading, credential lookup or real-provider mode.
The single-threaded CLI blocks socket connections/DNS as defense in depth.

An explicit `post-now` requires the displayed review identity, destination, version
and command ID; it persists authorization without sending. `run` composes the
existing posting agent and relay with a local object client, fake public-byte fetch,
ordered child/parent resources and a simulated provider receipt. A generic agent
also rejects mismatched simulated package/adapter modes. IDs begin `simulated:`;
reports always state `real_publication=false`. No real adapter is registered.

Outcomes are `success`, `outage` before the final marker, or `unknown` after it.
Local send evidence is written exclusively per post, surviving restart. Commands
for cancellation, unavailable reconciliation, explicit manual resolution and due
cleanup reuse the store/workers. The read-only report includes approval actor and
identity, caption/alt text, asset hashes, attempts, resources, simulated sends,
cleanup, uncertainty and human decisions. A report never refreshes readiness or
creates work. The fake object's HTTP-looking `.invalid` URL is never requested.

## Future Meta adapter contract: instagram_adapter_spec_v1

Specification only; **no Meta API request or public upload was made or implemented**.
Official documentation was inspected on 2026-11-16/17. Documentation examples use
`v27.0`; that is evidence to validate in Phase 3B, not a configured working version.
The future immutable capability snapshot must record explicit Graph API version,
login mode, host, account ID, allowed scopes, media bounds, quota evidence and
expiry. No implicit `latest` version or guessed readiness is allowed.

| Area | Documented requirement and Phase 3B gate |
| --- | --- |
| Account | Professional Business/Creator account; verify selected account and app access level. Facebook Login requires the linked Page, task access and any required Page publishing authorization / 2FA. Consumer accounts are ineligible. |
| Instagram Login | `graph.instagram.com`, Instagram User token, `instagram_business_basic` and `instagram_business_content_publish`. Validate granted scopes, app/account association and expiry without logging tokens. |
| Facebook Login | `graph.facebook.com`, linked Page and `instagram_basic`, `instagram_content_publish`, `pages_read_engagement`; Business Manager grants may require ads permissions. Guide and references differ in token wording: select and validate the documented endpoint-specific User/Page token flow, never substitute an Instagram Login token. Unified Login is outside this first connection. |
| Images | Publicly retrievable JPEG only, standard JPEG rather than MPO/JPS; media reference specifies 8 MB, width 320–1440, aspect 4:5–1.91:1, sRGB. Local profile stays at 1080×1350 and ≤8,000,000 bytes. Test resulting carousel crop; metadata geometry alone cannot prove its appearance on Instagram. |
| Carousel | Current guide advertises up to 20 children, while older references commonly used 10. Pin tested capabilities to the chosen version; start with only 4–6 English images. Freeze ordered child mapping, exact parent caption and reviewed per-image alt text. The current package has aggregate alt text: its mapping to individual children still needs an explicit reviewed contract. |
| Lifetime and polling | Media reference says containers expire after 24 hours and describes a 400-container rolling-day creation bound. Version/preflight must validate those limits. Poll with bounded attempts/deadline; `FINISHED` is ready, `PUBLISHED` means published, `IN_PROGRESS` is pending, `ERROR`/`EXPIRED` stop. Reads may retry under bounded backoff; final publish cannot blindly retry. |
| Quota | The publishing guide contains both 100 and 50 posts/day; the limit reference describes 50 and differs in request-field examples. Never hardcode one as truth. Confirm the selected version's fields, read account usage/config and quota window with a validity period, reserve locally for concurrent work, and honor provider rejection/backoff. Local cadence is an additional limit, not provider quota evidence. |

Future adapter sequence:

1. Validate the versioned capability snapshot, professional account/token/scopes,
   current quota and explicit exact-JPEG review/Post now. Refuse stale/missing
   evidence before staging; recheck near the final marker.
2. Persist R2 staging intent before side effects, upload immutable reviewed bytes
   with attempt-scoped unguessable keys, then verify authenticated metadata and
   anonymous HTTPS byte hash. Reject redirects, content changes and unsafe URLs.
   No CDN conversion. Ensure lifetime covers Meta ingestion and bounded polling.
3. Create individual image containers with exact URLs and reviewed alt text;
   durably bind IDs to ordinals/hashes. Create the carousel parent from the ordered
   children and exact caption. Persist parent identity before final publish. A lost
   create response is unresolved staging work, never evidence of publication;
   bound orphan creation/cleanup and quotas rather than unlimited replay.
4. Poll child/parent eligibility, maintain fenced leases and cancellation checks.
   Commit the existing final marker once, make one `media_publish` request, and
   durably retain returned media ID and redacted response provenance. Read back the
   receipt/account/children before claiming verified delivery; if persistence or
   final response is uncertain, retain `publication_unknown` and reconcile.
5. Use known container `PUBLISHED` evidence where reliable. Container lookup does
   not expose a guaranteed media-ID correlation or application idempotency key.
   Do not infer an exact match from caption/time or absence in a recent-media list.
   A failed/expired lookup, lost IDs or ambiguous negative evidence requires human
   intervention. Never turn it into permission to resend. Preserve unresolved
   receipt attribution even when publication itself is confirmed.
6. Retain minimal diagnostic IDs, statuses, timestamps and hashes, redact bearer
   tokens/signed URLs/raw responses, and schedule R2 cleanup independently. Before
   live use, define ingestion-safe cleanup timing; the current generic queue can
   clean immediately and the simulation does not establish real retention timing.

Later insights must link the confirmed account/media ID to measurement name,
API version, period/window, fetched-at timestamp and raw-response provenance/hash.
Missing/unavailable metrics remain unknown. Costs distinguish generation, relay,
operator effort and reconciliation; no insight collector is implemented here.

Official references (documentation reads only):

- [Content publishing and login modes](https://developers.facebook.com/documentation/instagram-platform/content-publishing)
- [Media creation and image limits](https://developers.facebook.com/documentation/instagram-platform/instagram-graph-api/reference/ig-user/media)
- [Container status and lookup limitations](https://developers.facebook.com/documentation/instagram-platform/instagram-graph-api/reference/ig-container)
- [Account publishing usage/config](https://developers.facebook.com/documentation/instagram-platform/instagram-graph-api/reference/ig-user/content_publishing_limit)
- [Final publish reference](https://developers.facebook.com/documentation/instagram-platform/instagram-graph-api/reference/ig-user/media_publish) (direct retrieval was rate-limited; revalidate before implementation).

[Data model](data-model.md) owns persisted identity and
[reliability](reliability.md) owns uncertainty and storage admission.
