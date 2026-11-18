# Offline measurement and operating costs

**Owner:** Phase 4A observation contract, provenance, attribution and operator report.

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
Synthetic evidence stays synthetic in any database and environment. Phase 4B must
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
