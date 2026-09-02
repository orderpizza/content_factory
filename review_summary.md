# Documentation Architecture Review Task List

**Review date:** 2026-08-29
**Reorganized:** 2026-09-02
**Scope:** Current documentation architecture only. The codebase was not
reviewed and must not be treated as evidence of current behavior.

This is a temporary working task list, not a canonical system contract.
Confirmed decisions belong in the Tier 2 document routed by
[`docs/system.md`](docs/system.md). Implementation must not depend on this file
directly.

## Decision-order principle

The list is ordered to minimize rework, not by the original P0/P1 label alone.
First settle the inputs, identities, lifecycle policies, and provider
constraints that create persisted records. Then define the complete data
catalog. Only then design the dashboard that exposes that stable state.

The dashboard is the sole visibility tool and will eventually cover many
pipelines, but that is precisely why its operational UX comes late in this
sequence. It must present the settled behavior of Detection, Determination,
generation, rendering, delivery, reliability, and the final data model; it
must not become the place that invents their states.

- **P0** — required before the affected public/production component can be
  implemented safely.
- **P1** — resolve before finalizing the baseline schema if it changes commands,
  states, or audit records.
- **P2** — follow-up design/tooling work after policy contracts stabilize.

## Settled task

### T01 — Dashboard local-access and command-trust boundary [complete]

The continuously running POC dashboard is accessible only on the Mac Mini
loopback interfaces. It has one durable `local_owner` actor and no login or
multi-user account system. State-changing commands require same-origin
anti-CSRF protection, a unique command ID, and the displayed record version.
One click on **Post now** immediately writes durable authorization; duplicate
clicks/retries are idempotent. The dashboard exposes complete non-secret
operational state and redacted diagnostics only.

**Canonical contracts:** [Dashboard and HAI](docs/specs/dashboard.md),
[Reliability and safety](docs/specs/reliability.md), and
[Data model](docs/specs/data-model.md).

## Recommended remaining order

| Order | Task | Priority | Why it is before later work |
| --- | --- | --- | --- |
| T02 | Detection canonicalization, clustering, and recurrence | P0 | Defines the source evidence, candidate identity, scoring, selection, and trend lineage that the rest of the system consumes. |
| T03 | Thread lifecycle, cancellation, and blocked-route re-evaluation | P1 | Defines how opportunity lineage may be closed, changed, or safely revisited before downstream records and transitions are finalized. |
| T04 | Meta delivery facts and reconciliation matching | P0 | Provider media/caption/delivery rules constrain O2 output, renderer encoding, and delivery behavior. |
| T05 | O2 creative, teaching, and metadata contract | P0 | Defines the structured package and teaching claims consumed by the shared renderer. |
| T06 | Shared visual profiles, templates, and O2 visual bindings | P0 | Depends on the O2 package fields and provider media constraints. |
| T07 | Post now, cadence, and account time-zone policy | P0 | Defines how one-click authorization becomes policy-eligible delivery. |
| T08 | Review freshness and intentional republishing | P1 | Depends on final assets, delivery/reconciliation policy, and renderer/provider versions. |
| T09 | Worker retry, lease, and Gemini-cost limits | P1 | Requires the full set of worker stages, model calls, and external boundaries above. |
| T10 | Complete data field and transition catalog | P2 | Consolidates all settled identities, commands, lifecycle states, and constraints into one reviewed baseline. |
| T11 | Backup, retention, artifact cleanup, and disk pressure | P2 | Depends on the finalized records, render assets, R2 lifecycle, and worker behavior. |
| T12 | Dashboard visibility and operational UX | P1 | Uses stable component outputs and the final catalog rather than inventing dashboard-only states. |
| T13 | Documentation conformance checks | P2 | Tooling should validate stable canonical names, links, and routing only after the docs settle. |
| T14 | Implementation plan and acceptance matrix | P2 | Derives from all settled contracts; it cannot safely substitute for them. |

## T02 — Detection canonicalization, clustering, and recurrence [P0]

**Decide:**

- Unicode/case/punctuation/whitespace normalization for a candidate and its
  route-neutral coverage identity.
- How RSS titles and Wikimedia article identities become the same cluster,
  including aliases, redirects, ambiguity, and language variants. Detection
  remains LLM-free.
- Exact prominence (`P_s`) calculation, tie handling, minimum population, RSS
  feed-independence rule, and degraded/unavailable source-health formula used
  by `R_s`.
- Exact materiality comparator for a candidate returning after the three-day
  cooldown; a changed fingerprint alone is insufficient.
- Rolling-budget half-open UTC windows, selection-time accounting, concurrency
  behavior, and deferred-candidate staleness.

**Recommended starting position:** Conservative versioned alias table plus
Unicode-normalized exact keys rather than fuzzy/semantic clustering;
deterministic percentile rank with an explicit tie rule; cooldown expiry plus a
new independent source kind or meaningful score/component increase. Do not use
“fingerprint differs” as the recurrence rule.

**Owners:** `docs/specs/detection.md` and `docs/specs/data-model.md`.

**Done when:** The same observations always create the same candidate, cluster,
selection, cooldown, and recurrence outcome without LLM involvement.

## T03 — Thread lifecycle, cancellation, and blocked-route re-evaluation [P1]

**Decide:**

- Whether `closed` prevents new intake, what can reopen it, and whether it
  changes existing work.
- What `cancelled` may safely stop at each boundary: intake, determination,
  generation, rendering, review, delivery, and post-publication audit.
- Whether cancellation invalidates outstanding review/delivery authorization.
- How a `blocked` determination becomes eligible for a capability recheck
  without silently re-running the same revision.
- Whether the capability recheck is a system-authored revision with unchanged
  editorial content or requires a human message.

**Recommended starting position:** `closed` prevents new messages but leaves
existing work unchanged and may be explicitly reopened. `cancelled` prevents
new intake and conditionally cancels only work that has not crossed an
external-side-effect boundary. Never re-evaluate a blocked decision
automatically; a human **Re-evaluate route** command creates an auditable
capability-recheck revision/request and preserves the original decision.

**Owners:** `docs/specs/idea-intake-and-determination.md`,
`docs/specs/dashboard.md`, `docs/specs/data-model.md`, and
`docs/specs/reliability.md`.

**Done when:** Each command's permitted targets, transaction preconditions, and
immutable historical records are stated. Published and `publication_unknown`
records are never erased or rolled back.

## T04 — Meta delivery facts and reconciliation matching [P0]

**Decide/verify from current official Meta and Cloudflare sources:**

- Selected Graph API version, permissions, token lifecycle, rate limits, and
  error taxonomy.
- Carousel limits, media URL requirements, container readiness/status behavior,
  and delivery constraints.
- Development test-account policy.
- Production public-media domain and retention policy, replacing development
  `r2.dev` before live delivery.
- Read-only reconciliation endpoints, bounded account/time scope, match fields,
  automatic `confirmed_published` threshold, and outcomes that remain
  `ambiguous` for a human.

**Owners:** `docs/platforms/meta.md`; generic safety remains in
`docs/specs/posting.md` and `docs/specs/reliability.md`.

**Done when:** Time-sensitive provider facts have a verification date and
sources, and reconciliation has a versioned, non-publishing match rule.

## T05 — O2 creative, teaching, and metadata contract [P0]

**Depends on:** T04 for final platform caption/media constraints.

**Decide:**

- Exact JSON schemas for teaching target, ordered slides, dialogue speakers and
  messages, metadata, provenance, citations, and the O2-owned content bindings
  within `visual_spec_json`.
- Unicode word-count rules for contractions, hyphens, emoji, numerals,
  punctuation, speaker labels, and the idiom itself.
- English locale/variant, tone, reading level, CTA policy, forbidden claims,
  and sensitive-topic rules.
- Caption serialization order, maximum final caption length, hashtag
  normalization/case/de-duplication, and tag/hashtag overlap policy.
- Teaching-accuracy validation and required evidence for meaning, nuance, and
  generated examples.
- Prompt/schema versions, maximum creative/metadata attempts, repair-prompt
  policy, per-job token/cost ceiling, and the frozen outline/angle boundary.

**Recommended starting position:** JSON-schema-first output; `en-US` unless
the O2 brand specifies otherwise; deterministic Unicode word counting; no
silent metadata fallback; conservative factual/teaching validation before
package creation; and repair attempts that preserve a frozen job intent rather
than vary freely.

**Owners:** `docs/pipelines/o2-english-instagram.md`; the generic visual
envelope is owned by `docs/specs/visual-rendering.md`.

**Done when:** A package can be validated deterministically before rendering,
and every learner-facing claim has an explicit evidence/validation rule.

## T06 — Shared visual profiles, templates, and O2 visual bindings [P0]

**Depends on:** T04 for delivery-media constraints and T05 for structured slide
fields.

**Decide:**

- Exact generic `visual_spec_json` envelope and per-role O2 bindings.
- The distinction between reusable pipeline-neutral **profiles**, concrete
  **templates**, and versioned O2 **themes**; profile IDs must not become
  pipeline-private styling.
- Profile tokens, palette, typography, local font files/licenses, safe areas,
  spacing, local assets, and profile/template/theme naming.
- Per-template copy capacity and deterministic overflow/clipping/missing-content
  detection.
- Playwright/Chromium/runtime pinning and reproducibility tolerance.
- PNG/JPEG encoder settings, color profile, quality/subsampling, and file-size
  bounds consistent with T04.
- Golden fixtures, pixel/perceptual regression thresholds, manual visual
  acceptance cases, and failure behavior for unavailable fonts/assets.

**Required policy:** Missing fonts or assets fail the `RenderRun`; the renderer
never silently substitutes them. The pipeline supplies structured content, not
raw HTML, CSS, fonts, colors, or remote asset URLs.

**Owners:** `docs/specs/visual-rendering.md`; O2 role mapping, copy capacity,
and compatible selection rules in `docs/pipelines/o2-english-instagram.md`;
manifest fields in `docs/specs/data-model.md`.

**Done when:** The first renderer can be implemented and regression-tested
without design choices being invented in code, and human review is bound to the
exact final JPEGs it will publish.

## T07 — Post now, cadence, and account time-zone policy [P0]

**Decide:**

1. Whether **Post now** bypasses the minimum interval and/or daily cap, or
   means the earliest policy-compliant delivery time.
2. The IANA time zone for account caps and dashboard display.
3. Daylight-saving-time behavior.
4. Whether a failed pre-publication attempt reserves a cadence slot and when
   it is released.

**Resolved scope:** The initial POC has no human scheduling command. A future
scheduling feature must be introduced as a separately versioned contract.

**Recommended starting position:** Post now means the earliest
policy-compliant delivery time; it never bypasses the minimum interval or daily
cap. Compute caps in the account time zone.

**Owners:** `docs/specs/posting.md`, `docs/specs/runtime.md`,
`docs/specs/dashboard.md`, and `docs/specs/data-model.md`.

**Done when:** Dashboard wording, immediate-request/eligibility fields,
due-work calculation, and delivery authorization behavior use one policy.

## T08 — Review freshness, renewed review, and intentional republishing [P1]

**Depends on:** T04, T06, and T07.

**Decide:**

- Maximum age of an awaiting review.
- Whether configuration, posting policy, template, renderer, capability, or
  provider-contract changes invalidate an existing review.
- Maximum time an approved immediate request may remain policy-deferred before
  it expires or needs renewed approval.
- When an expired/rejected exact package can enter a fresh review cycle.
- Whether an exact package may return for review after an auditable
  `not_published_cancel` resolution of `publication_unknown`.

**Recommended starting position:** Never intentionally repost the same
published package. Permit a fresh review of unchanged bytes only after
expiration or an auditable `not_published_cancel` reconciliation decision; all
other republication requires a new Brief Revision and content identity.

**Owners:** `docs/specs/dashboard.md`, `docs/specs/data-model.md`, and
`docs/specs/posting.md`.

**Done when:** Review validity, invalidation, fresh cycles, and publication
identity use one auditable policy.

## T09 — Worker retry, lease, and Gemini-cost limits [P1]

**Depends on:** T02–T08, because worker stages, model calls, rendering runtime,
and external-side-effect boundaries must be known first.

**Decide per worker/stage:**

- Batch size, lease duration, renewal point, maximum runtime, and graceful-stop
  behavior.
- Maximum attempts, exponential backoff/jitter, retryable error categories,
  and terminal escalation.
- Treatment of a stale `ModelInvocation(status=started)`, which may represent
  incurred cost without a response.
- System/job daily Gemini token and cost warning/stop limits.

**Recommended starting position:** Lease comfortably above normal stage p99,
renew at one-third remaining, use small POC batches, allow at most three
retry-safe technical attempts, and do not automatically retry a cost-uncertain
model call until a deliberate recovery policy exists.

**Owners:** `docs/specs/runtime.md`, `docs/specs/reliability.md`, and the
relevant stage contract.

**Done when:** Every claimable worker has one bounded, observable recovery and
cost policy; no worker invents retries independently.

## T10 — Complete the data field and transition catalog [P2]

**Depends on:** T02–T09. Do not finalize DDL before the remaining identities,
commands, lifecycle states, renderer manifest, and delivery policies are known.

**Define:**

- Full table/column catalog or reviewed baseline migration DDL.
- Field type, nullability, default, foreign key, and retention behavior for
  every retained record.
- A transition matrix for every claimable record, including allowed actor and
  transaction preconditions.
- Partial unique indexes for one active claim/run/review/reconciliation item.
- Foreign-key deletion behavior. Permanent audit lineage should use `RESTRICT`;
  published history must never cascade-delete.

**Owner:** `docs/specs/data-model.md`, with linked transition ownership in each
component specification.

**Done when:** The baseline migration, typed boundary models, and boundary
tests can be reviewed together without silently inventing any contract field or
status.

## T11 — Backup, retention, artifact cleanup, and disk pressure [P2]

**Depends on:** T06, T09, and T10.

**Decide:**

- SQLite backup cadence and restoration verification.
- Artifact, temporary-directory, quarantine, R2-cleanup, model-ledger, and
  audit retention by terminal state.
- WAL checkpoint policy and minimum disk headroom.
- Safe low-disk response.

**Recommended starting position:** Stop new generation/render claims before
disk exhaustion while preserving review, delivery audit, and published records.

**Owners:** `docs/specs/reliability.md`, `docs/specs/runtime.md`, and
`docs/specs/data-model.md`.

**Done when:** Unattended operation has a recoverable storage policy that
cannot destroy pending review or publication audit evidence under pressure.

## T12 — Dashboard visibility and operational UX [P1]

**Depends on:** T02–T11. The dashboard reads and traces the settled system; it
does not define its own lifecycle states or worker behavior.

**Decide:**

- The information architecture, default landing view, navigation, drill-down,
  filters, sorting, and trace links for all currently enabled pipelines.
- A pipeline/account-aware design that scales without redesign from O2 to many
  pipelines, while showing only actually enabled pipelines and never hiding a
  failing one in a global aggregate.
- A Trend Opportunities page as the primary view: every normalized candidate,
  its evidence, score/rank, shortlist result, determination outcome, selected
  pipeline/account, and linked content/delivery outcome.
- A complete trace detail from source observations through candidate, thread,
  brief, determination, ContentJob, package, render/review, and publication.
- Simple human interaction only: free-text idea/revision conversation, **Post
  now**, request changes, and remove from queue. No human scheduling control in
  the initial POC.
- Secondary views for ideas/threads, review queue, pipeline portfolio, worker
  operations, costs, audit, cleanup, and reconciliation.
- Exact refresh/freshness presentation and safe non-secret diagnostics using
  the final runtime/reliability policies.

**Owners:** `docs/specs/dashboard.md`, with references to every affected Tier 2
contract. Update `docs/system.md` only if dashboard ownership/routing changes.

**Done when:** The dashboard presents full source-to-publication traceability
and operational visibility without duplicating component contracts or requiring
operator inference from raw database records.

## T13 — Documentation conformance checks [P2]

**Depends on:** T10–T12; checking unstable names/statuses earlier would encode
premature assumptions in tooling.

**Add checks for:**

- Internal links and required Tier 2 metadata.
- Tier 1 router coverage and reachable pipeline/platform references.
- Forbidden duplicate status definitions and canonical record names.

**Owner:** `scripts/check_docs.py` and its tests. This is tooling work, not a
new architecture contract.

**Done when:** The checker protects finalized document-routing and naming rules
without treating this temporary task list as canonical input.

## T14 — Noncanonical implementation plan and acceptance matrix [P2]

**Depends on:** T02–T13. It must derive from settled contracts, not replace
them.

**Plan:**

1. Baseline schema, constraints, command receipts, claim helpers, and
   migrations.
2. Intake + Determination lineage and model ledger.
3. Deterministic Detection + recurrence.
4. O2 GenerationRun/checkpoint/package contract.
5. Renderer profiles, manifests, filesystem recovery, and review binding.
6. Dashboard read model and human commands.
7. Posting/Meta adapter, cleanup, reconciliation, and live-safety gates.
8. `launchd`, health, backup/retention, and end-to-end failure injection.

For each stage, derive boundary tests directly from the owning specification.
Do not use this task list as the implementation source of truth.

## Completion rule

When a task is decided:

1. Update the named Tier 2 owner(s), plus `docs/system.md` only if routing or
   top-level ownership changed.
2. Verify related documents do not duplicate or contradict the new policy.
3. Mark the task complete here with links to the canonical contracts, or remove
   it once no follow-up question remains.
4. Delete this file when every task is resolved; it is intentionally not a
   permanent documentation tier.
