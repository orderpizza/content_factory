# Offline measurement and operating costs

This specification owns schema v20 observation history, the Phase 4B0 Instagram Login collection contract and the one-destination report.

## Inventory and decisions

Publication state lives in `post_records`; authorization and exact JPEG review
live in `post_requests`, `review_requests` and `delivery_revisions`. Provider
acceptance, offline identity verification and reconciliation are separate evidence
in `publication_resources` and reconciliation tables. None is currently a live
Instagram receipt. Model invocations contain usage and diagnostic estimates;
`gemini_budget_reservations` is the accounting ledger. Settled values are internal
usage-priced estimates, not invoices or a guaranteed provider billing cap.

These records do not represent insight snapshots or manual cost observations.
Schema 20 adds only `measurement_observations`, an immutable append-only table in
the existing database. It does not rewrite publication, content or approval rows.

## Observation contract

Every observation identifies an immutable destination configuration row, canonical
account/provider account, optional PostRecord and media ID, a versioned definition,
metric, unit, post/account scope, explicit UTC half-open measurement window,
observation time, fetched time, source response SHA256, evidence reference and
provider/API/login/capability provenance. Local insertion time is separate.
Values are nonnegative integers; missing values are null with `unknown`,
`unavailable`, `not_authorized` or `not_collected`, never implicit zero.

Provenance is `synthetic`, `authenticated_platform`, `human_estimate` or
`not_collected`. The offline writer cannot accept authenticated observations.
Synthetic evidence stays synthetic in any database and environment. Phase 4B1 must
supply a separately reviewed authenticated issuer and metric registry; a label,
media ID, expired token, human decision or offline receipt is insufficient.

`synthetic_insights_v1` defines reach, saves, shares and follows for posts, and
reach and follows for accounts, as counts over the explicitly supplied window.
These are fixture semantics, not claims about v26/v27 support. The provider,
API version, login and capability are explicitly fixture-only. No implicit 24h,
7d, 30d or lifetime snapshots, cumulative addition or derived engagement ratios
are provided. `manual_operations_v1` defines operator minutes, storage micro-USD
and delivery micro-USD per post or account/window. Manual values are estimates;
no hourly rate or invoice accuracy is inferred. Account overhead is not allocated
to every post. Unknown definitions, units and scopes fail closed.

A source key identifies one observation across retries. Changed payloads under
that key are rejected. Corrections name the superseded observation, keep its
metric/scope/window/provenance stream and advance observation/fetch time; forks
are refused. Late arrivals in older windows are retained. Current values are
computed from immutable history by observation time then fetched time, never
insertion order. History and supersession remain inspectable after restart.

## Reporting and retention

The report selects one exact destination configuration and a UTC period. It
separates post/account observations and each window/provenance stream, exposes
fetched timestamps and missing coverage, and never adds snapshot values together.
Publication evidence remains distinct from metric provenance. No engagement is
revenue and no profitability claim is calculated.

Retain observation history and response hashes with the database and its verified
backups; no automatic pruning is introduced. Raw responses, credentials and tokens
are not persisted. Evidence references are bounded nonsecret operator identifiers,
not fetched URLs. The local OS owner remains the trust boundary. Corrections append
records; deletion or retention-policy changes require a separate reviewed change.

## Instagram Login pilot contract

Reviewed Meta documentation on 2026-11-18. The versioning guide and current
Instagram endpoint references identify `v27.0`. The collector pins this version
in the request and requires a matching response version header. Schema v20 is the
local database version. Phase 3B2's candidate publishing profile has its own
version and approval lifecycle. [Platform versioning](https://developers.facebook.com/docs/graph-api/guides/versioning)

Business Login for Instagram serves professional accounts with an Instagram User
access token on `graph.instagram.com`. Reading Insights requires
`instagram_business_basic` and `instagram_business_manage_insights`. Standard
Access covers accounts owned or managed and added to the app. Serving other
accounts requires Advanced Access. [Instagram Platform Insights](https://developers.facebook.com/documentation/instagram-platform/insights)

| Local metric | Documented GET and response | Schema v20 interpretation |
| --- | --- | --- |
| Account `reach` | `/{account}/insights` with `metric=reach`, `period=day`, `metric_type=total_value`. Read `total_value.value` and verify the account, metric and period in the response ID. | Estimated unique accounts reached, including ads, over one completed UTC day. Unit `unique_accounts`. [Account Insights](https://developers.facebook.com/documentation/instagram-platform/api-reference/instagram-user/insights) |
| Post `saves` | `/{parent-media}/insights?metric=saved`. Read one `values[].value` from the matching `saved/lifetime` result for a FEED carousel parent. | Count of saves as of capture. Window begins at the synthetic publication time and ends at capture. Children have no album Insights. [Media Insights](https://developers.facebook.com/documentation/instagram-platform/reference/instagram-media/insights) |

Meta's account endpoint describes inclusive Unix-second bounds. The pilot sends
`since=start` and `until=end-1 second` for its half-open daily window. A
`time_series` would return per-period results. A `breakdown` partitions a total,
and demographic `timeframe` overrides date bounds. The pilot requests neither
dimension and does not traverse time links to adjacent days. Keep evidence from
one requested range together. Confirm actual day boundaries on the pilot account.
[Account Insights parameters](https://developers.facebook.com/documentation/instagram-platform/api-reference/instagram-user/insights)

Account history extends up to 90 days. Media history extends up to two years.
Values may arrive up to 48 hours late. Empty data can indicate unavailable
metrics. Some account metrics have audience thresholds and Stories have shorter
availability and suppression rules. The pilot covers only the two definitions
above. [Account availability](https://developers.facebook.com/documentation/instagram-platform/insights) · [Media availability](https://developers.facebook.com/documentation/instagram-platform/reference/instagram-media/insights)

### Collection and identity

`workflow.instagram_insights.collect_offline` takes one destination, a UTC date,
capture and fetch times, up to five local PostRecord IDs and an in-memory HTTP
fixture. Within `offline_only()` it reads the configured IG User ID, then looks
up selected media on that account's media edge. Each selected parent must match
the returned `owner.id`, `CAROUSEL_ALBUM`, `FEED` and the exact media ID in a
unique local `synthetic_verified` receipt. A username cannot establish owner
identity. The old receipt's configuration and attempt remain historical evidence.
A human publication decision alone has no verified media binding.
[IG User](https://developers.facebook.com/documentation/instagram-platform/instagram-graph-api/reference/ig-user) · [User media edge](https://developers.facebook.com/documentation/instagram-platform/instagram-graph-api/reference/ig-user/media) · [Media owner](https://developers.facebook.com/documentation/instagram-platform/reference/instagram-media)

The injected transport looks up exact versioned GET URLs in memory. It has no
credential input, socket implementation or posting client. Media enumeration
stops when all selected IDs match. It can examine at most three pages, ten items
per page and twenty items total. A next-page indicator permits a bounded opaque
`after` cursor on the original media query. Returned URLs are never executed.
The collector rejects repeated cursors, duplicate IDs and incomplete searches.
[Graph pagination](https://developers.facebook.com/docs/graph-api/results/)

Each collection has at most ten GETs, three seconds per reply, twelve seconds
for the reads and 64 KiB per body. Meta applies Business Use Case limits to
Instagram requests, with usage and recovery information when available. The
Instagram throttle code is 80002. The rehearsal stops on throttling (including
HTTP 429), expired credentials (401 or code 190), provider failure, timeouts or
version drift. It makes one attempt. A future operator must check the account's
available budget and respect recovery headers before a new authorized read.
[Rate limits](https://developers.facebook.com/docs/graph-api/overview/rate-limiting/)

Only `ingest_offline` writes the complete validated batch. The definition
`synthetic_instagram_insights_v1` stores synthetic provenance, the period, wire
metric, response-body SHA256 and a bounded hash reference binding identity
responses and the selection. Explicit zero is known. Empty data is
`unavailable`, an explicit null is `unknown`, and a metric-level permission
denial after identity validation is `not_authorized`. Each carries a null value.
An aborted collection leaves prior history intact. Absent coverage remains
`not_collected`. Replaying the same capture returns its IDs. To correct a
capture, pass `supersedes={None: account_observation_id}` or map each post ID to
its previous observation. Late captures retain their own observation and fetch
times. The report shows each whole window and never adds lifetime snapshots.

### Separately authorized Phase 4B1

1. The owner selects one professional account and app, grants the two Insights
   scopes at the applicable access level and approves a short-lived read-only
   call plan with a request ceiling, expiry and stop conditions. Verify token
   kind, app, scopes, account binding, expiry, rotation and revocation in a
   credential-isolated reader.
2. Validate the version header, exact ID namespace and owner field against an
   existing, owner-approved carousel. Inspect only bounded aggregate responses.
   Check metric IDs, response shape, UTC boundaries, suppression, delay,
   pagination and the app/account usage headers. A missing or inconsistent field
   stops verification.
3. Obtain independently authenticated historical publication evidence before
   attributing audience data to a local post. Existing 3B2 receipts attest only
   offline fixtures. The authenticated definition registry remains empty and the
   reserved issuer rejects every proof. A future reviewed issuer must bind live
   identity, version, metric, window and receipt and prevent copied fixture proof
   from entering that path.
4. Agree comparable destination windows. The proposed manual pilot reads the
   previous UTC day's reach, then revisits it after the reporting delay. Capture
   media lifetime totals around 24 hours and seven days after publication and
   retain the actual capture times. The local rehearsal accepts media ages up to
   30 days. These intervals are sampling choices. Each lifetime value describes
   the entire period since publication. Scheduling and audience KPI baselines
   require a later decision.
