# Posting and delivery boundary

**Owner:** Exact-asset authorization, offline delivery rehearsal, preserved delivery
state machine, and the future Instagram adapter contract.

## Current contract and architecture map

The generation workflow ends at review PNGs. Phase 3B1 adds explicit offline
preparation, separate JPEG approval and Post now authorization in an operator DB.
No delivery runner or real adapter is composed. The dashboard reads evidence and
persists commands; it never constructs a provider, converts assets or sends posts.
Its CSRF, path containment and exact hash checks are preserved. JPEG reviews use
the [offline owner CLI and report](../operations.md#exact-jpeg-delivery-review).

| Boundary | Existing infrastructure and invariant |
| --- | --- |
| Editorial acceptance | `decide_review` / `approve_review` records a human decision, with row version and command receipt. It creates no PostRequest. PNG approval covers only those PNG bytes. |
| Deliverable review | Package and manifest hashes bind caption, alt text and ordered `delivery_jpeg` assets. Post now reopens and validates actual JPEGs against persisted size/hash/MIME/geometry, package count and destination. English supports 4–6 slides; other domains retain the 4–14 local content bound. These are local contracts, not claims of provider eligibility. |
| Explicit Post now | `authorize_post_now` requires a separately approved delivery-revision review, then atomically creates a unique publication identity, PostRequest and PostRecord. Legacy direct-JPEG fixture reviews retain their original combined authorization behavior. It checks current configuration, visual approval, readiness, expiry and cadence. Replayed command IDs return the same record; changed input is rejected. |
| Preparation/staging | `CredentialedPostingAgent` claims work, rechecks artifacts/authorization and records PostAttempt. `R2TransientRelay` uploads exact JPEG bytes, checks authenticated HEAD and anonymous exact-byte fetch. Staging never changes creative. |
| Final send | A fenced transaction rechecks live lease, thread, cancellation, expiry and readiness, then commits the final-send marker before calling `publish`. Success stores a receipt ID; any potentially accepted final call becomes `publication_unknown`, never automatic retry. |
| Recovery | Expired claims before the final marker can retry within limits. Recovery after it is conservative, including a crash between marker and actual send. Pre-final cancellation wins. |
| Reconciliation | `PublicationReconciliationWorker` records unavailable lookup evidence and hands uncertainty to a human. Explicit decisions can confirm publication, cancel as not published, or leave unknown. None reposts automatically. |
| Cleanup | Attempt resources and cleanup tasks remain separately durable. Cleanup can remove staged objects after success, failure, cancellation or uncertainty; it never reverses a publication or resolves its outcome. |

The production catalog remains closed `production_configuration_v2` with
`adapter_version=unimplemented`. No OAuth, live adapter, send command
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

## Append-only delivery revision and human commands (Phase 3B1)

Schema 18's unique constraints permit only one package per output/adaptation, one
storyboard per package/output and one render per storyboard/visual recipe. Two
concrete alternatives were considered:

1. Add a delivery revision containing only derivative package/manifest evidence,
   referencing the original review, with a new ReviewRequest. Existing PostRequest
   and PostRecord keep their original package/render foreign keys as **source
   lineage**, resolving delivery bytes through the review's revision pointer.
2. Add a new output/adaptation/package/storyboard/render branch for conversion.
   This would require new output-identity rules and broaden generation/render
   semantics, or fabricate successful work to satisfy existing constraints.

Option 1 is implemented. No original content, source, recipe, render, manifest,
asset or approval is rewritten. `delivery_revisions` is SQL-immutable; its package
copies the exact original caption, aggregate alt text and all existing content,
adding only technical preparation and explicit ordered `image_alt_text`. Each
manifest asset also freezes its individual alt text. No automatic splitting,
rewriting or inference from the aggregate description occurs. Human-supplied
per-image descriptions must preserve its complete meaning; the report shows both.
Technical validation cannot prove semantic completeness or that a human looked.

`prepare` takes an original, unexpired, awaiting or editorially approved English
PNG ReviewRequest on an open thread, its current account/destination, a contained
artifact root and a new output directory. It reuses `prepare_review_bundle` and
verifies stored hashes, ordered assets and source bytes. The command records the
source review/package/render IDs and hashes, source snapshot/brief hashes,
canonical identity/hash, visual recipe/hash, output identity/binding, destination
and provider account ID. It creates one immutable revision and a new
`awaiting_review` ReviewRequest atomically with its command receipt. It never
inherits the PNG decision. Arbitrary `candidate.json` import is unsupported;
conversion always starts from trusted DB evidence. A failed transaction can leave
an unregistered directory; no worker discovers it, and retry needs a new directory.
A successful command replay returns its original review without reconversion.

`report` validates exact evidence and writes a new self-contained local HTML file
with every JPEG embedded in order, caption, aggregate/per-image alt text, hashes,
lineage, account/provider ID, destination, status, expiry and command fingerprint.
It uses a read-only DB connection and never refreshes readiness. HTML is escaped,
scripts/network are forbidden by CSP, and existing report paths are never replaced.
The dashboard labels these as JPEG delivery reviews and offers no PNG approval
form for them. Direct legacy `approve_review` calls also reject JPEG revisions.
The existing rejection command may reject an awaiting revision; corrections need
a new revision and fresh review. Cancellation after Post now remains the existing
`cancel_delivery` state-machine operation, not deletion of approval evidence.

`approve` requires the displayed review ID, row version, fingerprint, account,
destination and every JPEG hash in order, plus the CLI's explicit inspection
acknowledgment. The fingerprint binds the immutable package, manifest, lineage,
artifact root, review status, version and expiry. Approval revalidates source and
JPEG bytes, current binding, readiness and configuration under a write transaction.
It records `local_owner`, decision/time and a receipt, increments the review
version and creates **no PostRequest**. This trusts the local OS owner, like the
loopback dashboard; a fingerprint is not a remote authentication mechanism.

A fresh report supplies a new fingerprint/version for the separate `post-now`.
The existing `WorkflowStore.authorize_post_now` rechecks approval, current exact
artifacts, destination, readiness, visual configuration, storage admission,
expiry and cadence. It preserves the JPEG approval actor/note/time, appends a
command receipt, creates approved PostRequest plus pending PostRecord, and fences
stale commands. The canonical identity plus destination is the publication
identity for revisions. Any previous authorization for that canonical/destination
(including a different revision or cancelled/failed authorization) blocks another;
there is no automatic reauthorization/repost recovery. Exact command replay
returns the same result after restart and does not create work.

The original claim, attempt, expiry, final-send marker, cadence, cancellation,
unknown-outcome and reconciliation machinery remains authoritative. Revision
artifacts and approval are rechecked before attempt creation and the final marker.
A default `CredentialedPostingAgent` has an empty adapter registry and fails before
staging/final send. Revision delivery also refuses the `unimplemented` configuration
marker even if a caller injects an adapter, preventing fake transports from marking
operator revisions published. The production CLI never constructs that agent, fake adapters,
R2, Gemini clients or provider transports; it has no run/send option and denies
socket connections/DNS. Rehearsal fake publication remains confined to its separate
synthetic workspace. No real provider is configured or called in this phase.

Readiness is never invented by these commands. Preparation may precede readiness;
approval/Post now require the existing current ready observation and enabled
binding. A default development fixture binding with no destination cannot be
promoted. Account registration/readiness validation and rebinding old unbound
reviews are not silently added; those are explicit future integration concerns.

## Isolated simulation

`simulate_delivery.py init` creates a fresh workspace, current-schema DB, synthetic
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
| Carousel | Current guide advertises up to 20 children, while older references commonly used 10. Pin tested capabilities to the chosen version; start with only 4–6 English images. Freeze ordered child mapping, exact parent caption and reviewed per-image alt text. Phase 3B1 preserves aggregate alt text and adds separately reviewed ordered per-image descriptions; the adapter must transmit those exact strings and validate version-specific limits. |
| Lifetime and polling | Media reference says containers expire after 24 hours and describes a 400-container rolling-day creation bound. Version/preflight must validate those limits. Poll with bounded attempts/deadline; `FINISHED` is ready, `PUBLISHED` means published, `IN_PROGRESS` is pending, `ERROR`/`EXPIRED` stop. Reads may retry under bounded backoff; final publish cannot blindly retry. |
| Quota | The publishing guide contains both 100 and 50 posts/day; the limit reference describes 50 and differs in request-field examples. Never hardcode one as truth. Confirm the selected version's fields, read account usage/config and quota window with a validity period, reserve locally for concurrent work, and honor provider rejection/backoff. Local cadence is an additional limit, not provider quota evidence. |

### Exact input to the future adapter

`WorkflowStore.prepare_post_attempt` returns the validated context to the existing
agent. For a revision it includes:

| Field | Meaning |
| --- | --- |
| `delivery_revision_id`, `lineage`, `revision_fingerprint` | Immutable derivative identity and source review/package/render, canonical, recipe and output binding evidence. Original package/render IDs are provenance, not a second render. |
| `package.caption`, `package.alt_text`, `package.image_alt_text` | Exact parent caption, retained aggregate accessibility description and ordered human-reviewed child descriptions. |
| `assets[]` | Contiguous ordinal, contained local JPEG path, MIME, dimensions, byte count, SHA256 and `alt_text`. `render_asset_id` is null for revision derivatives; identify them by revision plus ordinal/hash. Read bytes from the path and recheck immediately before staging. |
| `platform`, `account`, `destination_key`, `provider_account_id`, `output_binding_id` | Exact current authorized account and destination; domain `english` remains editorial policy. |
| `package_hash`, `manifest_hash`, `publication_identity`, `post_request_id`, `post_record_id` | Approval binding, canonical/destination duplicate guard and durable authorization/delivery identities. |
| `post_attempt_id`, `claim_owner`, `claim_version`, `attempt_number` | Fenced attempt identity; the agent adds attempt number. SQL retains status, expiry, readiness, policy snapshot and final-send marker. |

No public URL exists in Phase 3B1. The future relay must produce verified exact-byte
URLs per asset and durable publication resources scoped to the attempt; the
adapter consumes that ordered URL/hash/alt mapping without transforming images or
copy. It must preserve existing final-marker and unknown-outcome semantics.

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
