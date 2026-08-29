# Documentation Architecture Review Summary

**Review date:** 2026-08-29  
**Scope:** Current documentation architecture only. The codebase was not
reviewed and must not be treated as evidence of current behavior.

This is a review artifact, not a canonical system contract. Confirmed decisions
must be incorporated into the owning Tier 2 document routed by
[`docs/system.md`](docs/system.md); implementation should not depend on this
file directly.

## Settled during this review

The obvious cross-document gaps have been repaired in the canonical docs:

- Evidence, coverage, content, and publication are four separate identities.
- Selected trends and human messages create durable `IntakeRequest` handoffs;
  workers do not infer work from unread conversation.
- The three-day rejected-candidate cooldown is retained, but expiry alone does
  not regenerate content. A materially changed candidate continues its existing
  thread through a `ThreadEvidenceEvent` and `evidence_refresh` revision.
- Claims use leases plus monotonic fencing versions, bounded attempts,
  `retry_wait`, and conditional finalization.
- Accepted Determination decision + unique Content Job + request completion are
  one transaction.
- Model-call audit starts before the provider call, so a crash cannot hide a
  potentially billable invocation.
- The renderer produces the canonical final JPEGs before review. Review binds
  exact package, manifest, and asset hashes; the posting adapter cannot convert
  or repair them.
- `PostRequest` is immutable human authorization; workers claim `PostRecord`.
- Publication reconciliation is durable, read-only work with append-only checks
  and an auditable human resolution.
- Heartbeats use one current row per worker instance; append-only worker runs
  are reserved for substantive work.
- The current pre-production database may be deliberately rebuilt, but never
  automatically by dashboard/worker startup. Once the new baseline exists,
  migrations are forward-only.

## Decisions required before implementation

### P0. Detection canonicalization, clustering, and recurrence materiality

`attention_v1` has weights and broad formulas, but the following deterministic
details still need an exact versioned contract:

- Unicode/case/punctuation/whitespace normalization for a candidate and its
  route-neutral coverage identity.
- How RSS titles and Wikimedia article identities become the same cluster,
  including aliases, redirects, ambiguity, and language variants. Detection
  must remain LLM-free.
- The exact prominence (`P_s`) calculation, tie handling, minimum population,
  RSS feed-independence rule, and degraded/unavailable source-health formula
  used by `R_s`.
- The exact materiality comparator for a candidate returning after the
  three-day cooldown. A changed fingerprint by itself is too weak: timestamps,
  rank movement, or one new feed item could otherwise regenerate effectively
  identical content.
- Rolling-budget boundary semantics: half-open UTC windows, selection time used
  for counting, concurrency behavior, and when a deferred candidate becomes too
  stale to reconsider.

Recommended starting position: use a conservative versioned alias table and
Unicode-normalized exact keys rather than fuzzy/semantic clustering; use
deterministic percentile rank with an explicit tie rule; and require cooldown
expiry plus a substantive event such as a new independent source kind or a
meaningful score/component increase. Do not use “fingerprint differs” as the
materiality rule. The exact score delta/source condition needs confirmation.

Owning documents: `docs/specs/detection.md` and `docs/specs/data-model.md`.

### P0. Visual profile and template deep dive

The renderer boundary is now coherent, but the visual specification explicitly
defers the material needed to build it:

- exact `visual_spec_json` schema and per-role bindings;
- profile tokens, palette, typography, font files/licensing, safe areas,
  spacing, local assets, and template/version naming;
- per-template copy capacity and deterministic overflow/clipping detection;
- Playwright/Chromium/runtime pinning and reproducibility tolerance;
- PNG and JPEG encoder settings, color profile, quality/subsampling, and file
  size bounds;
- golden fixtures, pixel/perceptual regression thresholds, and manual visual
  acceptance cases; and
- fallback behavior when fonts/assets are missing (recommended: fail the run,
  never silently substitute).

This is a blocker for renderer implementation and visual-regression tests.

Owning document: `docs/specs/visual-rendering.md`, with O2-specific limits in
`docs/pipelines/o2-english-instagram.md`.

### P0. O2 creative and metadata contract completion

The slide counts and word limits exist, but robust generation still needs:

- exact structured schemas for slides, dialogue speakers/messages, metadata,
  provenance, citations, and `visual_spec_json` output;
- word-count/tokenization rules for contractions, hyphens, emoji, numerals,
  punctuation, and speaker labels;
- English locale/variant, tone, reading level, CTA policy, forbidden claims,
  sensitive-topic rules, and whether the idiom itself counts toward limits;
- caption serialization order, maximum final caption length, hashtag
  normalization/case/de-duplication, and whether tags may overlap hashtags;
- teaching-accuracy validation and what evidence is required for meaning,
  nuance, and generated examples;
- prompt/schema versions, maximum creative and metadata attempts, repair-prompt
  policy, and per-job token/cost ceiling; and
- whether a failed creative attempt may vary freely or must preserve a frozen
  outline/angle checkpoint.

Recommended starting position: JSON-schema-first output, `en-US` unless the O2
brand specifies otherwise, deterministic Unicode word counting, no silent
metadata fallback, and conservative factual/teaching validation before package
creation.

Owning document: `docs/pipelines/o2-english-instagram.md`.

### P0. Post now, cadence, time zone, and overdue policy

The docs now refuse to guess whether `delivery_mode=immediate` bypasses cadence.
Choose and document:

1. Does **Post now** bypass minimum interval and/or daily cap, or mean “the
   earliest policy-compliant slot”?
2. Which IANA time zone owns the daily cap and displayed scheduled times?
3. How are daylight-saving changes handled?
4. If a scheduled time is already past after downtime, publish at the next
   compliant slot, require fresh confirmation, or expire the authorization?
5. Does a failed pre-publication attempt reserve a cadence slot, and when is
   the slot released?

Recommended starting position: Post now means earliest policy-compliant slot;
it never bypasses the minimum interval or daily cap. Store the requested local
time/zone and normalized UTC time, compute caps in the account time zone, and
require renewed confirmation for materially overdue authorizations.

Owning documents: `docs/specs/posting.md`, `docs/specs/runtime.md`,
`docs/specs/dashboard.md`, and `docs/specs/data-model.md`.

### P0. Meta delivery facts and reconciliation match rule

Before adapter implementation, reverify official Meta and Cloudflare material
for the selected Graph API version, permissions, carousel limits, media URL
requirements, container status behavior, rate limits, error taxonomy, and token
lifecycle. Then define a read-only reconciliation algorithm:

- which provider endpoint(s) it queries;
- the bounded time window and account scope;
- which fields form a match (media type, creation time, caption/hash surrogate,
  permalink, child count/order, or another stable identifier);
- what is unambiguous enough for automatic `confirmed_published`; and
- which results must remain `ambiguous` for a human.

Also confirm development test-account policy and replace `r2.dev` with the
intended production public-media domain/retention policy before live delivery.

Owning document: `docs/platforms/meta.md`; generic safety remains in
`docs/specs/posting.md` and `docs/specs/reliability.md`.

## Important policy decisions

### P1. Blocked Determination re-evaluation

A `blocked` decision currently creates no job and the dashboard offers thread
continuation, but the docs do not decide what happens after configuration or a
capability becomes available. One Determination request is currently unique per
revision, so silently running the same revision again would violate the audit
model.

Recommended starting position: never re-evaluate automatically. Add an explicit
human **Re-evaluate route** command that creates an auditable capability-recheck
revision/request with the new capability snapshot; preserve the old blocked
decision. Confirm whether this may be a system-authored revision with unchanged
editorial content or must require a human message.

Owning documents: `docs/specs/idea-intake-and-determination.md`,
`docs/specs/data-model.md`, and `docs/specs/dashboard.md`.

### P1. Review freshness, renewed review, and intentional republishing

The schema now supports review invalidation/expiration and review cycles, but
the policy still needs exact answers:

- maximum age of an awaiting review;
- whether configuration, posting-policy, template, renderer, capability, or
  provider-contract changes invalidate an existing review;
- how far in the future an approved scheduled delivery may remain valid;
- when an expired/rejected exact package may enter a fresh review cycle; and
- after a human resolves `publication_unknown` as not published, whether the
  exact package may return for a new approval or must receive a new creative
  revision.

Recommended starting position: never allow an intentional repost of the same
published package. Permit a fresh review cycle for unchanged bytes only after
expiration or an auditable `not_published_cancel` reconciliation decision; all
other republishing requires a new Brief Revision and content identity.

Owning documents: `docs/specs/dashboard.md`, `docs/specs/data-model.md`, and
`docs/specs/posting.md`.

### P1. Retry, lease, and model-cost limits

The architecture defines fenced claims and bounded retries, but not the actual
values for each worker. Specify per worker/stage:

- batch size, lease duration, renewal point, maximum runtime, and graceful-stop
  behavior;
- maximum attempts, exponential backoff/jitter, retryable error categories,
  and terminal escalation;
- special handling for a stale `ModelInvocation(status=started)`, which may
  represent incurred cost without a response; and
- system/job daily Gemini token and cost warning/stop limits.

Recommended starting position: lease comfortably above the normal stage p99,
renew at one-third remaining, small batches for the POC, at most three
retry-safe technical attempts, and no automatic model retry when the prior call
is cost-uncertain until a deliberate recovery policy is documented.

Owning documents: `docs/specs/runtime.md`, `docs/specs/reliability.md`, and the
relevant stage contract.

### P1. Thread closure and cancellation propagation

`ContentThread.status` is described as administrative, but exact semantics are
missing. Decide whether closing/cancelling a thread prevents new Intake,
cancels safely pending Determination/Generation/Render work, invalidates review,
or leaves all downstream work unchanged. Published and
`publication_unknown` records must never be erased or rolled back.

Recommended starting position: `closed` prevents new messages but leaves
existing work unchanged and can be explicitly reopened; `cancelled` prevents
new Intake and conditionally cancels only work that has not crossed an external
side-effect boundary. Make propagation one audited transaction/service.

Owning documents: `docs/specs/data-model.md`, `docs/specs/dashboard.md`, and
`docs/specs/reliability.md`.

### P1. Dashboard trust and operator identity

The HAI persists consequential approval, cancellation, and reconciliation
decisions, but its deployment trust boundary is not defined. Confirm:

- localhost-only, trusted LAN, or remotely reachable;
- authentication/session mechanism and durable actor identity;
- CSRF/replay protection and command-id generation;
- whether a second confirmation is required for public **Post now**; and
- which safe raw JSON/error fields are visible and how redaction is tested.

Recommended POC position: bind to loopback only, one explicit local operator
identity, anti-CSRF/idempotency tokens, and a final confirmation showing account,
exact assets, caption, hashes, and irreversible-publication warning. Any LAN or
remote access should require real authentication before delivery controls are
enabled.

Owning documents: `docs/specs/dashboard.md` and
`docs/specs/reliability.md`.

## Follow-up specification work

### P2. Backup, retention, and disk-pressure policy

Define SQLite backup cadence/verification, artifact retention by terminal
state, temp/quarantine cleanup, R2 cleanup escalation, model/audit retention,
WAL checkpoint policy, minimum disk headroom, and the safe response to low disk.
Recommended behavior is to stop new generation/render claims before disk
exhaustion while preserving review, delivery audit, and published records.

### P2. Complete field/transition catalog

`docs/specs/data-model.md` now defines the important records and invariants, but
some retained detection tables and newer records remain prose rather than a
complete field/type/nullability/default/foreign-key catalog. Before writing the
baseline migration, add:

- a full table/column catalog or reviewed migration DDL;
- one transition matrix per claimable record, including allowed actor and
  transaction preconditions;
- partial unique indexes for one active claim/run/review/reconciliation item;
  and
- foreign-key deletion behavior (recommended: restrict permanent audit lineage,
  never cascading deletion across published history).

The migration DDL and typed boundary models/tests should be reviewed together;
do not let either silently invent contract details.

### P2. Documentation conformance checks

Extend the documentation checker later to verify internal links, required Tier
2 metadata, router coverage, forbidden duplicate status definitions, canonical
record names, and that every pipeline/platform reference is reachable from
`docs/system.md`. This is code/tooling work and was intentionally not changed
during this documentation-only review.

### P2. Implementation sequence and acceptance matrix

Create a noncanonical development plan after the P0/P1 decisions are resolved.
A practical dependency order is:

1. baseline schema, constraints, command receipts, claim helpers, and migrations;
2. Intake + Determination lineage and model ledger;
3. deterministic Detection + recurrence;
4. O2 Generation Run/checkpoint/package contract;
5. renderer profiles, manifests, filesystem recovery, and review binding;
6. dashboard read model and human commands;
7. Posting/Meta adapter, cleanup, reconciliation, and live-safety gates; and
8. `launchd`, health, backup/retention, and end-to-end failure injection.

For each stage, derive boundary tests directly from the owning specification.
Do not use this review file as the implementation source of truth.
