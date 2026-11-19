# Posting and delivery boundary

**Owner:** Exact-asset authorization, offline delivery rehearsal, preserved delivery
state machine, and the future Instagram adapter contract.

## Current contract and architecture map

The generation workflow ends at review PNGs. Phase 3B1 adds explicit offline
preparation, separate JPEG approval and Post now authorization in an operator DB.
A disabled-by-default adapter factory is implemented; no live contract is verified or delivery runner enabled. The dashboard reads evidence and
persists commands; it never constructs a provider, converts assets or sends posts.
Its CSRF, path containment and exact hash checks are preserved. JPEG reviews use
the [offline owner CLI and report](../operations.md#exact-jpeg-delivery-review).

| Boundary | Existing infrastructure and invariant |
| --- | --- |
| Editorial acceptance | `decide_review` / `approve_review` records a human decision, with row version and command receipt. It creates no PostRequest. PNG approval covers only those PNG bytes. |
| Deliverable review | Package and manifest hashes bind caption, alt text and ordered `delivery_jpeg` assets. Post now reopens and validates actual JPEGs against persisted size/hash/MIME/geometry, package count and destination. English supports 4–6 slides; other domains retain the 4–14 local content bound. These are local contracts, not claims of provider eligibility. |
| Explicit Post now | `authorize_post_now` requires a separately approved delivery-revision review, then atomically creates a unique publication identity, PostRequest and PostRecord. Legacy direct-JPEG fixture reviews retain their original combined authorization behavior. It checks current configuration, visual approval, readiness, expiry and cadence. Replayed command IDs return the same record; changed input is rejected. |
| Preparation/staging | `CredentialedPostingAgent` claims work, rechecks artifacts/authorization and records PostAttempt. `R2TransientRelay` uploads exact JPEG bytes, checks authenticated HEAD and anonymous exact-byte fetch. Staging never changes creative. |
| Final send | A fenced transaction rechecks live lease, thread, cancellation, expiry and readiness, then commits the final-send marker before calling `publish`. The registered Instagram adapter retains acceptance separately and requires issued media/account verification before automatic `published`. Failed or uncertain readback remains `publication_unknown`, never automatic retry. |
| Recovery | Expired claims before the final marker can retry within limits. Recovery after it is conservative, including a crash between marker and actual send. Pre-final cancellation wins. |
| Reconciliation | The registered factory supplies bounded read-only investigation of known media/container IDs. Only positive, identity-bound receipt evidence can confirm automatically; generic/unavailable lookup still hands uncertainty to a human. Human decisions remain distinct from API verification. None reposts automatically. |
| Cleanup | Attempt resources and cleanup tasks remain separately durable. Cleanup requires independent safe-release evidence for registered Instagram objects; it never reverses a publication or resolves its outcome. |

The production catalog remains closed `production_configuration_v2`. It accepts
`adapter_version=unimplemented` or the versioned, disabled-by-default Instagram
registration below. No OAuth, live send command or real capability probe is enabled. Configuration visual acceptance is separate
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
adding delivery preparation, ordered `image_alt_text` and the required
`is_ai_generated=true` disclosure for generated images. Each
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

Target contract; **no real Meta API request or public upload was made**. Checkpoint 1
implements the transport and composition boundaries described below, with live use blocked.
Official documentation was checked again on 2026-11-18. Documentation examples use
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
| Quota | The publishing guide describes 100 posts/day and the limit reference describes 50 with differing request-field examples. Never hardcode one as truth. Confirm the selected version's fields, read account usage/config and quota window with a validity period, reserve locally for concurrent work, and honor provider rejection/backoff. Local cadence is an additional limit, not provider quota evidence. |

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
   tokens/signed URLs/raw responses, and schedule R2 cleanup independently under
   the Checkpoint 3 release policy below. Its offline source-independence contract
   does not establish real ingestion safety or permit live deletion.

Phase 3B2 is complete offline only. Phase 4B0 consumes historical
`instagram_verified_receipt` records through the [measurement contract](measurement.md#instagram-login-pilot-contract).
Collection checks the recorded destination, receipt media ID and returned owner.
Neither a human decision nor a simulated receipt establishes platform performance.
The collector has no posting registration, readiness refresh, approval, Post now
or resource-management entry point.

Official references (documentation reads only):

- [Content publishing and login modes](https://developers.facebook.com/documentation/instagram-platform/content-publishing)
- [Media creation and image limits](https://developers.facebook.com/documentation/instagram-platform/instagram-graph-api/reference/ig-user/media)
- [Container status and lookup limitations](https://developers.facebook.com/documentation/instagram-platform/instagram-graph-api/reference/ig-container)
- [Account publishing usage/config](https://developers.facebook.com/documentation/instagram-platform/instagram-graph-api/reference/ig-user/content_publishing_limit)
- [Final publish reference](https://developers.facebook.com/documentation/instagram-platform/instagram-graph-api/reference/ig-user/media_publish) (direct retrieval was rate-limited; revalidate before implementation).

[Data model](data-model.md) owns persisted identity and
[reliability](reliability.md) owns uncertainty and storage admission.

## Offline Instagram Login protocol experiment (Phase 3B2, incomplete)

### Checkpoint 1: registered composition and trusted boundaries

`workflow.instagram_composition.InstagramComposition` now consumes the actual
immutable `production_configuration_v2` catalog through a closed
`instagram_login_v1` registration. The registration defaults to `enabled=false`;
credentials and registration alone cannot start work. The factory is not installed
in the polling worker, dashboard or LaunchAgents. No live command is exposed.

The explicit sequence is configuration approval → read-only `preflight()` → exact
JPEG review/approval → separate Post now → `activate(..., confirm=True)` →
`agent(...).run_once()`. Construction, preflight, activation and agent construction
never publish or stage objects. Activation is restricted to one pending PostRecord,
its destination/provider account, configuration, credential, evidence, package and
manifest. Its **authorization-to-start** expires within two minutes (or earlier
evidence expiry), checked with both wall and monotonic clocks before claiming and
again before consumption. The agent claims only that record. Consumption and an
`instagram_run` execution grant are committed atomically before staging. The grant
binds that attempt's claim owner/version and exact reviewed identity. It cannot be
reused, transferred to another worker or automatically reissued after failure.

An already running attempt has a separate fixed execution deadline: at most 45
minutes from consumption, capped by the original token, Post now and JPEG review
expiries. The two-minute start deadline no longer stops this authorized work.
Both elapsed monotonic time and the durable wall deadline are enforced; backward
clock movement fails closed. Neither heartbeats nor fresh evidence extend the
grant. The same live claim renews its five-minute lease before every external
request and in at-most-30-second polling wait segments, bounded by that deadline.
An expired/lost claim cannot renew or start another request.

| Lifecycle boundary | Result |
| --- | --- |
| Configuration, preflight, JPEG approval, Post now, activation | Separate approvals; no provider side effects from configuration or activation. |
| Unused start authorization expires | No new claim, consumption or external request; the queued post stays held. |
| Unexpired activation is consumed by its claim | `publishing` / `staging`, with one durable execution grant for one attempt. |
| Current claim continues within its execution deadline | Guarded staging and minute-spaced polling; renewable lease and fresh readiness, then `ready_to_publish`. |
| Execution/polling deadline, cancellation or lost ownership before the final marker | Stop requests; failure/cancellation or fenced stale recovery, with investigation required for a consumed run. No automatic replay. |
| Durable final marker commits | `final_request_sent`; at most one final POST, still guarded immediately before dispatch. |
| Final response or uncertain outcome | Existing `published` receipt handling or `publication_unknown`; never an automatic final-send retry. |

Continuation means the **same living invocation, attempt, claim and grant**. It is
not a restart or retry. Restart cannot reconstruct in-memory run authority, even
after a crash before the first upload/create intent. Stale recovery makes consumed
pre-final attempts terminal; a committed final marker instead preserves publication
uncertainty. This checkpoint has no human rearm command, even for an unused expired
activation or a consumed run proven to have zero external effects. Such a command
would need separate review of quota, approval and side-effect evidence.

Container polling allows at most five reads, at least 60 seconds between request
starts and a five-minute elapsed limit including waits and requests. These are
local conservative bounds, not a verified provider SLA. Slow responses count
toward both container and overall execution limits. No POST is automatically
retried. SQL admission checks do not hold a transaction across network I/O: an
already admitted in-flight request cannot be recalled by later cancellation or
claim loss. Its reply cannot revive an expired lease or authorize a next request.

Preflight reads identity, permission grants and quota via the authenticated HTTP
interface and consumes a separate `TokenValidityReader` for token/app/login/expiry
verification. Only the issuing preflight can persist its result through the registered
readiness API; arbitrary `CapabilityObservation`, dicts and copied results are
rejected. Evidence is allowlisted, bound to the immutable destination/configuration
and current in-memory credential, and expires within five minutes or token expiry.
A failed refresh revokes prior readiness. Replaying an issued proof or supplying
caller-written offline readiness cannot reinstate it. Evidence is rechecked before each R2
put/head/anonymous read and each Instagram request, as well as the final marker.
The current invocation refreshes evidence when it has at most 90 seconds left,
checking its claim, cancellation, exact assets, original token and fixed execution
deadline before every read-only refresh request and before persisting the result.
Only this guarded refresh can replace its active proof; the original configuration
and credential binding must match. Expired evidence permits only that guarded
read-only refresh, never a publish/upload. Credential changes, revocation or an
unrelated replacement evidence ID stop the run. Fresh evidence cannot revive an
expired start authorization, lost claim or consumed activation after restart.

**Live verification remains blocked.** `VERIFIED_LIVE_CONTRACTS` is empty. The
candidate profile is `instagram_login_candidate_v1`, explicitly pinned to `v26.0`
for fixtures only. It uses GET `/me` (`user_id,account_type`), GET `/me/permissions`
and GET `/{account}/content_publishing_limit` (`quota_usage,config`). These response
shapes, the `facebook-api-version` response header, and the selected-login token
introspection flow have **not been externally verified in this checkpoint**.
There is no registered live `TokenValidityReader`. No JSON flag, token, fake
observation or run confirmation can substitute for that verification. A reviewed
implementation of the verified token reader and live contract is required before
real read-only preflight can run. This is an explicit external-contract blocker,
not a claim that fixture account observations are authenticated.

Injected HTTP, token and storage implementations require the explicit
`offline_only()` network-refusal boundary, with every external dependency supplied.
Their evidence has `provenance=offline` and remains **degraded** in SQLite; only
inside that boundary is it eligible for offline authorization checks. Outside it,
the production catalog, review/Post now, attempt and final-marker checks refuse
that evidence. Injected adapters cannot bypass the registered factory. The old
observation/exchange helpers are offline-only and cannot establish readiness.
Trust assumes the local OS/database owner; this is not a sandbox against arbitrary
Python execution or an owner directly rewriting SQLite.

Activation reserves one publication and one container per slide plus one parent.
The same SQLite write transaction checks both limits before recording the one-post
activation. The account ID and number of slides come from each immutable delivery
revision. All aliases and configuration releases for the same provider ID share a
budget. Reservations survive failures, uncertain outcomes and restarts. They cover
the rolling day plus the maximum delay between activation and dispatch (two minutes
to start and 45 minutes to execute). Fresh observations plus existing reservations
can conservatively count some usage twice. A guarded refresh rechecks both budgets.

### Authenticated HTTP and credentials

`workflow.instagram_http` pins TLS with certificate/hostname verification to
`graph.instagram.com`, the configured explicit version, allowed methods and account
paths. Bearer credentials go only in the Authorization header. Requests are limited
to 32 KiB encoded parameters; responses to 64 KiB, JSON, no compression and the
matching API-version header. Redirects are refused, including Location headers.
There is no retry loop, even for 429, 5xx, timeouts or potentially accepted POSTs.
Safe categories replace provider messages/exception text; tokens, raw replies and
request headers are never persisted or logged.

A single HTTPS attempt runs in a bounded child process. The parent enforces a
20-second maximum wall-clock deadline across DNS, connection, TLS, headers and
body reads, terminating the child on timeout. Socket inactivity timeout alone
would not bound slow responses. Credentials cross only in-memory IPC, never
command arguments or files. Offline tests supply a wire below the same request,
response, authentication and validation logic; separate tests cover TLS host
pinning and termination of a stalled child without network access.

`EnvironmentCredentials` resolves only the configured `DELIVERY_TOKEN` reference
from an OS-injected process environment. It rejects missing/invalid values and
hides the secret in representations. No token enters production configuration,
SQLite, Git, model traces or logs. There is no dotenv loading or command-line token
argument in this composition. A process-local keyed fingerprint detects rotation
without persisting any token-derived value. See the [operator handoff](../operations.md#instagram-integration-status).

### Checkpoint 2: publication receipts and conservative reconciliation

The existing schema is unchanged. Publication status and receipt classification
are separate: `published` can also represent a legacy simulation or an explicit
human decision, so it alone never establishes verified Instagram identity.

| Evidence classification | Meaning and transition |
| --- | --- |
| `accepted_unverified` | A successful final response supplied a numeric media ID. `instagram_publish_acceptance` retains that ID and exact local attempt/review/destination binding in its own transaction before readback. The attempt remains in progress during verification; any failure becomes `publication_unknown`. Acceptance alone is not identity verification. |
| `identity_verified` | An issued receipt matches the accepted media ID, owning account, carousel type, exact caption hash and complete unique child-media count. Safe receipt facts are persisted atomically with automatic `published`, the external media ID and succeeded attempt. In this checkpoint all such proofs have **offline provenance**, not real Instagram evidence. |
| `outcome_uncertain` | No accepted media ID is durably available, or the evidence conflicts/is unavailable. Preserve `publication_unknown`, known parent/child container IDs and final marker. Never infer non-publication or replay a final POST. |

`workflow.instagram_receipts` binds safe evidence to the PostRecord, PostAttempt,
delivery revision, package/manifest hashes, destination ID/key, provider account,
configuration/version and known parent/child container IDs. The local hashes prove
which reviewed content was sent; they do **not** prove Meta's returned pixels.
Verification explicitly lists JPEG bytes, child order relative to reviewed assets
and alt text as unverified. Child media IDs are not container IDs. No conversion
between those namespaces or parent-to-published-media mapping is invented.

The candidate readback is one GET `/{accepted-media-id}` with fields
`id,owner,media_type,caption,children{id}` through the same pinned, authenticated,
single-attempt transport. It rejects absent/mismatched owner or media ID, different
caption/type, incomplete/paginated children and inconsistent counts/IDs. Only
allowlisted numeric IDs, hashes, timestamps, classification/provenance and explicit
verification limits are persisted. Raw private responses, URLs, captions returned
by the provider, tokens and diagnostics are not copied into receipt storage.
Caller-created or copied receipt objects cannot authorize automatic confirmation.

Acceptance retention does not grant execution authority: an already dispatched
publish reply may be recorded after lease loss, but that worker cannot verify,
confirm or send again. Final persistence still fences ownership, live lease,
approval/readiness and the original execution deadline. If the first acceptance
write itself cannot commit, the media ID cannot be durably retained; the existing
final marker and container IDs preserve uncertainty. A later verification/status
transaction failure cannot roll back the independently committed acceptance.

`InstagramComposition.reconciliation_worker(fresh_proof)` supplies only read-only
capabilities to `PublicationReconciliationWorker`. It consumes an existing explicit
reconciliation request, not a run activation, and cannot stage or publish. It checks
its own request owner/version/live lease, unresolved post and current account/token/
configuration evidence before and after each GET. It has a 180-second monotonic
budget checked around requests, at most eight GETs, and the existing per-request
20-second bound. There is no pagination, list search or automatic request retry.
Posting approval expiry does not prohibit investigation of historical evidence;
fresh trusted account evidence is still required. The current preflight's quota
gate may conservatively block investigation when quota evidence is exhausted.

With a durably accepted media ID, positive readback can atomically append a receipt
and reconciliation check, resolve the request, mark the original attempt succeeded
and confirm the post. Without that ID, read only the known parent/child container
statuses. Even `PUBLISHED` does not establish a published-media/account mapping.
Missing media, 404/permission errors, inaccessible fields, conflicts and negative
observations remain ambiguous/unavailable and move the request to `needs_human`.
They never mean `confirmed_not_published`; the registered store rejects that
automatic outcome. Lost claims cannot persist even a negative check. Restart may
perform a newly claimed read-only investigation, never resume a consumed run.

Existing human decisions remain `published`, `not_published_cancel` or
`leave_unknown`, with the selected check, actor, note and command receipt. They do
not manufacture provider verification or authorize retry. The existing JPEG review
HTML report includes accepted IDs, verification scope/provenance, reconciliation
checks and human decisions. Reading it never refreshes readiness or calls a provider.
After an inconclusive check there is no automatic polling loop: the owner may leave
the outcome unknown and explicitly request another investigation later.

**Live receipt capability is blocked, not assumed.** The receipt contract
`instagram_receipt_candidate_v1` and its empty live registry are offline-only.
Alongside the Checkpoint 1 contract/token-reader verification, the owner must
establish for the exact Instagram Login API version and approved account/app:

- Whether media readback reliably exposes owning account identity (`owner.id` is
  only the fixture hypothesis), which permissions/access level it needs, and that
  its ID namespace matches the configured professional account.
- Whether returned `id`, carousel type, caption and complete child-media listing
  have the selected field/expansion semantics, including pagination and delayed
  availability, and that this readback identifies published media rather than an
  unpublished container. Exact caption comparison fails closed on normalization.
- Whether any supported **positive** evidence links a known publishing container
  to a published media ID after response loss. Until reviewed and implemented,
  that case remains human-only; a negative list lookup is never sufficient.
- Any reliable asset/order/alt correspondence the API actually provides. No such
  claim is made by the current proof. Registration requires reviewed code and
  separately authorized account verification, not a configuration flag or fake.

### Checkpoint 3: orphan investigation and staging lifecycle

`resource_lifecycle.py` is composed through `InstagramComposition.investigate_orphans()`
and `cleanup_worker()`, using existing resource, command and cleanup records.
The read-only JPEG report and staging report distinguish committed creates with
unknown responses, known child/parent IDs, pending ingestion, verified receipts
and unresolved final outcomes. Unknown IDs are never guessed from lists or caption
matches. Investigation cannot create containers, publish, resolve publication by
absence, or rearm a consumed activation.

Investigation requires a terminal/recovered attempt, trusted preflight for its
exact destination and an exclusive durable 180-second investigation lease. Each
of at most seven known container IDs receives one bounded authenticated status
GET, fenced before and after against claim, account/readiness and attempt snapshot.
A competing live investigation or cleanup claim blocks admission. A crashed reader
can be replaced after its lease expires; its late response cannot commit evidence.
Only allowlisted statuses, IDs, timestamps, immutable binding hashes and offline
provenance persist. Missing/failed reads become `UNAVAILABLE`, never safe absence.
Evidence must be less than five minutes old when a new release is authorized.

Every newly staged registered object records the exact R2 account/bucket/public
origin/key, destination/provider account, post/attempt, package/manifest hashes,
asset ordinal, SHA-256 and byte length. Conditional create uses `IfNoneMatch=*`.
A separate `r2_staged` record proves upload, HEAD and exact public-byte probe
completed. A crash before that record leaves write completion uncertain, even if
an object is visible. Child intents bind the corresponding object resource/key.

The following policy is implemented and tested **only with offline evidence**.
All rows require terminal/recovered execution, complete immutable identity and a
completed staging record. Neither elapsed TTL nor a human publication decision is
source-independence evidence.

| Object evidence | Release disposition |
| --- | --- |
| Completed staging never exposed to a create request, with no final-send marker | Eligible for explicit safe-policy scheduling. |
| Verified publication plus positive source-independence statuses for every known child/parent | Eligible for safe-policy scheduling under the candidate offline contract. A receipt alone is insufficient. |
| Every known container positively `EXPIRED`, with no final-send marker | Eligible for safe-policy scheduling under the candidate offline contract. Wall-clock age is insufficient. |
| All known containers positively independent/expired, but cancelled or uncertain publication disposition | Separate exact-object operator release required. Publication remains unchanged. |
| Unknown create IDs, incomplete graph/source binding, uncertain upload, pending/error/unavailable ingestion, active attempt, stale evidence or legacy identity | Retain. A confirmation flag cannot override this hold. |

The fixture hypothesis treats `FINISHED`/`PUBLISHED` as source-independent and
`EXPIRED` as no longer requiring source bytes. These meanings are **not verified
live API capabilities**. Outside the offline boundary even unused fixture objects
are ineligible. There is no live source-independence reader or enabled scheduler.

Release is independent from JPEG approval, Post now, activation and human receipt
reconciliation. Commands require exact object identity, destination, attempt,
immutable hashes, current resource state, current report fingerprint and a unique
command ID. A SQLite transaction checks all evidence, appends an actor/time/reason
release record and queues one cleanup task. Identical command replay returns its
existing result; altered/stale commands fail. No provider request occurs in a
release command. Changed attempt/investigation evidence invalidates pending work.
The durable release captures positive source independence; its original five-minute
admission freshness need not remain live during queue delays, but any new or
contradictory investigation invalidates it.

Cleanup claims retain the existing ten-minute lease and five-attempt limit with
five-minute retry delay. Before every request and completion, the worker checks
live claim ownership, exact identity and release evidence. It HEADs the exact key,
checks immutable metadata, JPEG length/type and ETag, then DELETEs with `IfMatch`
and confirms absence. A replacement fails closed. Retry after a timeout/crash
rechecks identity; already absent objects complete idempotently. Only bounded
transient/uncertain deletion failures retry; exhausted or rejected tasks require a
fresh independently authorized command. No upload/create/publish retry is added.
Intent, returned deletion, confirmed absence and failures are durably auditable;
stale workers cannot finalize another claim. Investigation and deletion leases
exclude each other. An already admitted network request cannot be recalled after
claim loss; no subsequent request or completion is permitted by that stale worker.

The default R2 client pins TLS to the configured account host, uses SDK connect/read
timeouts of 5/10 seconds, one total SDK attempt and a one-send hook that rejects
redirect/replay. PUT, HEAD, DELETE and public-byte probes run in supervised child
processes with at most a 20-second whole-exchange deadline, shortened by remaining
publication execution time. Stalled blocking I/O is terminated; credentials remain
in memory/IPC and raw SDK errors/logs do not escape. Terminating the local process
cannot undo an accepted remote operation, so uncertain writes remain retained.
Conditional cleanup may retry only under its original exact-object authorization.

**Owner-dependent gates:** verify status fields and source-dependency semantics for
the selected Instagram Login version/account, including expired/published children
and parent behavior; establish reliable positive mapping for lost IDs or keep them
held. Separately verify R2 conditional PUT/DELETE support, ETag/metadata identity,
HEAD absence/consistency and pinned-endpoint behavior. `VERIFIED_R2_CONTRACTS` is
empty; configuring credentials cannot enable it. Existing token/version/readback
gates remain closed. No live request or deletion is authorized by this checkpoint.
The [operations guide](../operations.md#staging-investigation-and-release) owns the
local offline report/release commands.

### Checkpoint 4 Instagram Login evidence

Official references reviewed 2026-11-18. The simulator uses the explicit v26.0
candidate. The following distinctions govern any future live implementation.

| Boundary | Public documentation | Evidence still required for this account |
| --- | --- | --- |
| Login and identity | Business Login for Instagram exchanges an authorization code for a short-lived Instagram User token, scoped user ID and grants. A long-lived token has a documented 60-day lifetime. The publishing guide specifies professional Business and Creator accounts, `graph.instagram.com`, `instagram_business_basic` and `instagram_business_content_publish`. [Business Login](https://developers.facebook.com/documentation/instagram-platform/instagram-api-with-instagram-login/business-login) · [Publishing guide](https://developers.facebook.com/documentation/instagram-platform/content-publishing) | Verify app access, account type and ID, exact grants, revocation, data-access expiry and same-app token inspection. The generic Graph debug-token reference requires an associated app or developer credential. The selected Instagram Login introspection flow and response fields need their own verification. [Debug token](https://developers.facebook.com/docs/graph-api/reference/debug_token/) |
| Version | Meta labels v27.0 latest. Its lifecycle table lists v21.0–v25.0 with future expiry dates and v26.0 with expiry TBD as of the review. [Versioning](https://developers.facebook.com/docs/graph-api/guides/versioning) · [Version table](https://developers.facebook.com/docs/graph-api/changelog/versions/) | Verify the pinned v26.0 endpoint shapes, returned version, app access and feature availability. Record any upgrade through a reviewed contract change. |
| Images and order | The image profile and bounds appear above. Meta documents up to 20 children and crop based on the first image. The local contract uses 4–6 ordered 1080×1350 JPEGs. Each image gets its own public URL, carousel-item flag and exact alt text (up to 1,000 characters). The parent takes ordered child IDs and the caption (2,200 characters, 30 hashtags, 20 mentions). [Media creation](https://developers.facebook.com/documentation/instagram-platform/instagram-graph-api/reference/ig-user/media) | Verify anonymous retrieval, observed crop, displayed order, child accessibility and caption on the selected account. The aggregate accessibility description stays in review. |
| AI disclosure | Meta describes an optional post-level boolean and excludes carousel children. The generated English package requires true. New revisions display and hash that declaration before approval. Pre-disclosure revisions remain inspectable and require fresh preparation and review before delivery. The candidate sends the field only on the parent and requires true on the parent media readback. [Media creation](https://developers.facebook.com/documentation/instagram-platform/instagram-graph-api/reference/ig-user/media) · [Media fields](https://developers.facebook.com/documentation/instagram-platform/reference/instagram-media) | Verify both fields on the pinned version, and the visible AI label. An absent or contradictory readback after the final request retains the returned media ID for investigation and leaves publication uncertain. |
| Status and errors | POST `/{ig-user}/media` for each child and parent, GET `/{container}?fields=id,status_code`, then POST `/{ig-user}/media_publish` with the parent creation ID. Only a matching ID and `FINISHED` advance staging. `IN_PROGRESS` permits bounded polling. `PUBLISHED`, `ERROR`, `EXPIRED`, and unknown or mismatched results stop staging. Containers expire after 24 hours. [Publishing guide](https://developers.facebook.com/documentation/instagram-platform/content-publishing) · [Container reference](https://developers.facebook.com/documentation/instagram-platform/instagram-graph-api/reference/ig-container) | Verify status responses, errors and the point at which Meta stops fetching bytes. A status or elapsed time alone cannot release a real object. A lost create response leaves a durable intent. A lost final response never authorizes another publish. |
| Publication quota | The guide describes 100 posts per rolling day and counts a carousel once. The limit reference describes 50 and documents `quota_usage` and `config`; its example requests `rate_limit_settings`. The candidate requires one complete observation with a positive available dynamic limit and an 86,400-second window. [Publishing guide](https://developers.facebook.com/documentation/instagram-platform/content-publishing) · [Publishing limit](https://developers.facebook.com/documentation/instagram-platform/instagram-graph-api/reference/ig-user/content_publishing_limit) | Establish the selected account's fields, limit and usage. A missing, paginated, ambiguous or exhausted response blocks preflight. |
| Container quota | Meta documents 400 container creations per account per rolling day. A 4/5/6-slide attempt budgets 5/6/7 creates even if some replies are lost. Publication usage measures published posts. [Media limitations](https://developers.facebook.com/documentation/instagram-platform/instagram-graph-api/reference/ig-user/media) | No authoritative account-wide creation-usage reader was established. Only an isolated fixture supplies independent same-account/version/window usage and parent/child field capabilities. Live capacity remains unknown. |

The fixture receipt verifies the accepted parent media ID, owner, carousel type,
caption, child count and the declared AI field for new revisions. JPEG bytes,
ordinal-to-published-child mapping, alt text, displayed labels and object-source
independence need separate evidence. Orphan investigation requires an ID-bound
status response. Previously recorded status-only investigations require a fresh
check before release. Conditional R2 operations and consistency remain unverified.
All live registries stay empty.
