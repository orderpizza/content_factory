# Documentation Architecture Review 2 — Ordered Remediation Plan

**Review date:** 2026-09-05
**Scope:** Documentation architecture and spec-driven-development readiness.
Application code was not reviewed.
**Document role:** Noncanonical review artifact. Confirmed resolutions must be
written into the owning canonical contracts routed by `docs/system.md`.

## How to use this review

Address the findings in the order below. Later sections depend on decisions in
earlier sections. Do not begin broad implementation until Phases 1–5 are
resolved; otherwise the schema, worker queues, detection algorithm, and typed
contracts may be implemented incompatibly.

For every completed item:

1. Update the owning Tier 2 contract rather than this file.
2. Remove contradictory or obsolete wording from all summary documents.
3. Add the corresponding rule to `scripts/check_docs.py` when it can be checked
   mechanically.
4. Update `docs/implementation-plan.md` if the resolution changes dependencies
   or acceptance evidence.
5. Run `py scripts/check_docs.py`.

## Current assessment

The overall architecture remains sound and does not need replacement. The
Tier 1 system guide, focused system specifications, pipeline contract, and
platform reference form a workable foundation. The prior review's major safety
gaps have largely been addressed: durable Intake handoffs, candidate
recurrence, thread lifecycle, fenced claims, immutable review assets, Post now
policy, reconciliation, local dashboard trust, storage monitoring, and an
implementation plan now exist.

The remaining risk is ambiguity. Several concepts currently have two plausible
owners, two state machines, or two incompatible definitions. Spec-driven
development should begin only after each persisted handoff has one creator, one
consumer, one state machine, and one canonical definition.

# Phase 1 — Resolve identity and lineage

## 1. Separate detection opportunity identity from editorial coverage identity

**Priority:** P0 — architecture blocker

### Problem

Detection defines a selected candidate's route-neutral coverage identity as:

```text
trend:<canonicalization_version>:<cluster_key>
```

The data model makes that identity immutable when a trend thread is created.
The O2 pipeline instead defines coverage identity as the normalized English
teaching target. These can differ for the same opportunity. For example, a
trend title such as “Why ‘piece of cake’ is trending” is not the same canonical
editorial target as the idiom “piece of cake.”

The same unresolved problem exists when a human submits an idea whose final
coverage identity already belongs to another thread.

### Recommended resolution

- Keep the detection cluster key in the evidence/opportunity domain. Do not
  call it editorial coverage identity.
- Permit a trend-originated `ContentThread` to exist with its seed candidate
  and cluster identity while `coverage_identity` remains null.
- Have Idea Intake assign the final route-neutral coverage identity atomically
  when it freezes Revision 1.
- Define a versioned deterministic normalization contract for coverage identity.
- Define the collision transaction when another thread already owns that
  coverage identity. Recommended behavior:
  - automatic trend evidence attaches to the existing thread;
  - a human is directed to continue the existing thread; and
  - a new thread is permitted only when an explicit qualifier proves that the
    intended editorial coverage is materially distinct.
- Preserve the candidate/evidence event even when no new thread is created.

### Documents to update

- `docs/specs/data-model.md`
- `docs/specs/detection.md`
- `docs/specs/idea-intake-and-determination.md`
- `docs/pipelines/o2-english-instagram.md`
- `docs/system.md` if the top-level flow changes

### Done when

- One term is used for detection clustering and another for editorial coverage.
- Trend and human collision behavior is transactional and testable.
- O2, Detection, Intake, and Data Model all derive the same final coverage
  identity at the same lifecycle point.

# Phase 2 — Establish one work item per worker

## 2. Resolve `ContentJob` versus `GenerationRun` claim ownership

**Priority:** P0 — implementation blocker

### Problem

Both `ContentJob` and `GenerationRun` currently have claim/retry state machines.
Runtime says the Pipeline Runner consumes a pending Content Job “and its
GenerationRun,” while the transition matrix requires the GenerationRun's
parent job claim to remain live. The contracts do not define which record is
polled first, who creates the GenerationRun, whether two leases must be
renewed, or which attempt limit is authoritative.

### Recommended resolution

Use this simpler model:

1. Determination atomically creates an immutable `ContentJob` and one pending
   `GenerationRun` when it accepts a route.
2. Only `GenerationRun` is worker-claimable.
3. `ContentJob` remains the immutable recipe. Any displayed job state is a
   derived projection or a narrowly defined aggregate, not a second lease.
4. Creative/metadata provider attempts are `ModelInvocation` children of the
   GenerationRun.
5. Retry-safe failures return the same GenerationRun to `retry_wait` and create
   a new ModelInvocation attempt; they do not create an unrelated content job.

If a different model is chosen, it must still provide one polling record, one
lease, and one retry counter.

### Documents to update

- `docs/specs/data-model.md`
- `docs/specs/runtime.md`
- `docs/specs/reliability.md`
- `docs/specs/idea-intake-and-determination.md`
- `docs/pipelines/o2-english-instagram.md`
- `docs/system.md`

### Done when

- The Pipeline Runner has exactly one claimable input.
- GenerationRun creation is part of a named atomic transaction.
- No two nested worker leases are required.
- Dashboard backlog and retry state have one authoritative source.

## 3. Define `RenderRun` creation and retry semantics

**Priority:** P0 — pipeline dead-end blocker

### Problem

The Visual Renderer requires a pending RenderRun, but no contract clearly owns
its creation. Generation success creates a Content Package and runtime assumes
a RenderRun already exists. The data model also says a safe retry creates a new
run while its state machine provides `retry_wait` on the existing run.

### Recommended resolution

- Generation success atomically creates:
  - the immutable `ContentPackage`; and
  - one pending `RenderRun` with its complete frozen renderer input.
- The Visual Renderer claims only that RenderRun.
- A retry-safe execution reuses the same RenderRun and increments its attempt
  envelope.
- A separate RenderRun for the same package is permitted only through an
  explicit, audited rerender/recovery operation after the prior run is terminal.
- A successful run remains immutable and cannot be superseded silently.

### Documents to update

- `docs/specs/data-model.md`
- `docs/specs/runtime.md`
- `docs/specs/visual-rendering.md`
- `docs/specs/reliability.md`
- `docs/pipelines/o2-english-instagram.md`
- `docs/system.md`

### Done when

- Package creation cannot leave the pipeline without a RenderRun.
- “Retry this run” and “create another run” have separate, explicit meanings.
- Only one active RenderRun can exist per package.

## 4. Define all other downstream handoff-creation transactions

**Priority:** P0

### Required transaction inventory

Confirm and document the creator, complete outputs, uniqueness guard, and
failure behavior for each boundary:

| Trigger | Atomic persisted result |
| --- | --- |
| Human idea/rework command | Thread/message + `IntakeRequest` + command receipt |
| Selected trend | Candidate selection + thread/evidence lineage + `IntakeRequest` |
| Completed Intake | `BriefRevision` + `DeterminationRequest` |
| Accepted Determination | Decision + `ContentJob` + `GenerationRun` + completed request |
| Successful generation | `ContentPackage` + `RenderRun` + successful generation state |
| Successful rendering | Manifest + assets + `ReviewRequest` + successful render state |
| Post now | Approved review + `PostRequest` + `PostRecord` + command receipt |
| Delivery attempt | `PostAttempt` before the first external side effect |
| Staged public object | `PublicationResource` + eventual cleanup responsibility |
| Publication uncertainty | `publication_unknown` + reconciliation availability |

### Done when

No downstream worker depends on a record whose creator is implied rather than
named.

# Phase 3 — Make the persistence contract executable

## 5. Fix primary-key contradictions

**Priority:** P0

### Problem

The data-model convention requires `INTEGER PRIMARY KEY AUTOINCREMENT`, while
the baseline and canonical catalog say `INTEGER PRIMARY KEY`. These are
different SQLite contracts when deletion or the highest historical ID is
involved.

### Recommended resolution

If audit IDs must never be reused, use `INTEGER PRIMARY KEY AUTOINCREMENT`
consistently for permanent audit entities. Explicitly list any internal or
replaceable table that may use a different key strategy.

### Document to update

- `docs/specs/data-model.md`

### Done when

The convention, catalog, migration requirements, and eventual DDL use exactly
the same primary-key rule.

## 6. Replace the pseudo-DDL catalog with an exact schema contract

**Priority:** P0 — spec-driven-development blocker

### Problem

The section named “Baseline DDL” is prose rather than DDL. It uses ambiguous
phrases such as “common id,” “as its name/value requires,” and “claim envelope.”
It does not fully specify column names, types, nullability, checks, defaults,
partial-index predicates, or every non-claimable transition.

The wording that every `*_id` is a foreign key also conflicts with named primary
keys such as `thread_id`.

### Recommended resolution

Choose one of these equivalent approaches:

1. Add reviewed target SQL for the baseline schema; or
2. Add a complete schema contract from which SQL can be implemented without
   inventing details.

The contract must include:

- exact table and column names;
- exact SQLite types and nullability;
- defaults and `CHECK` expressions;
- primary and foreign keys with deletion actions;
- full unique and partial-index predicates;
- every status set;
- common claim fields by exact name;
- attempt and eligibility fields;
- command version fields;
- JSON validation/version fields; and
- transaction-level invariants that SQLite cannot enforce alone.

Recommended structure if the document becomes too large:

```text
docs/specs/data-model.md          # identities, invariants, ER map, routing
docs/specs/data/records.md        # exact records, columns, FKs, indexes
docs/specs/data/transitions.md    # exact state and atomic transaction matrix
```

### Documents to update

- `docs/specs/data-model.md`
- `docs/system.md` if the data contract is split
- `scripts/check_docs.py`

### Done when

A developer can write the baseline migration without choosing an undocumented
column, state, default, or constraint.

## 7. Add optimistic row versions for dashboard command targets

**Priority:** P0

### Problem

Dashboard commands must validate the displayed target-record version, but the
data model defines no common `row_version` or equivalent. `claim_version` is a
worker fencing token and cannot version non-claimable Thread, Review, and
authorization state.

### Recommended resolution

- Add monotonic `row_version` to every mutable human-command target.
- Define which transitions increment it.
- Require dashboard commands to match target ID plus displayed `row_version`.
- Keep `claim_version` separate and exclusive to worker ownership fencing.
- Define how command receipts record the version read and version produced.

### Documents to update

- `docs/specs/data-model.md`
- `docs/specs/dashboard.md`

### Done when

Every command race has a deterministic success/conflict result without using a
worker lease as a UI concurrency mechanism.

## 8. Complete status and transition definitions

**Priority:** P0

### Required fixes

- Resolve `ModelInvocation(outcome=started)` versus
  `ModelInvocation(status=started)`.
- Define the closed lifecycle for `gemini_budget_reservations`, including
  reserved, settled, released, and uncertain states.
- Define `PostAttempt` and `PublicationResource` status sets.
- Add a transition matrix for non-claimable mutable records:
  `ContentThread`, `ReviewRequest`, `PostRequest`, configuration registries,
  and human reconciliation decisions.
- Define whether ContentJob retains aggregate status after it stops being a
  claimable queue.
- Remove the overly broad common lifecycle sentence when an entity has valid
  terminal states such as `needs_clarification`, `publication_unknown`, or
  `expired` that are not in that sentence.

### Done when

Every persisted status has one owner, one closed set, allowed actors, legal
predecessors, and required side effects.

## 9. Add exact machine-checkable JSON contracts

**Priority:** P0

### Required schemas

At minimum:

- `brief_v1`
- Intake result/clarification result
- `determination_result_v1`
- capability snapshot and executable recipe
- `o2_creative_v1`
- O2 metadata result and deterministic caption components
- `visual_spec_v1`
- render manifest
- safe provider-attempt result
- reconciliation evidence/result
- configuration manifests

Recommended location:

```text
docs/contracts/
```

or another clearly routed canonical directory. JSON fields in SQLite should
name their schema ID/version, and boundary tests should validate the same
schema artifacts.

### Documents to update

- `docs/system.md`
- `docs/specs/data-model.md`
- each owning component/pipeline specification
- `scripts/check_docs.py`

### Done when

No worker prompt, parser, or package serializer must infer a JSON shape from a
Markdown example.

# Phase 4 — Define configuration, readiness, and reference ownership

## 10. Create one versioned configuration control plane

**Priority:** P0

### Problem

The architecture contains persisted source instances, cluster aliases,
pipeline capabilities, posting policies, renderer profiles/templates/themes,
and teaching references. The dashboard cannot administer them, but no other
component is defined as their writer.

### Recommended resolution

Use versioned repository manifests plus an explicit validation/apply operator
command:

- manifests are reviewed, non-secret inputs;
- applying them creates immutable configuration versions and audit records;
- workers consume only a named activated version;
- startup validates but never silently changes registry data;
- exactly one effective version exists per applicable scope;
- secrets remain in environment/credential stores and are referenced only by
  safe configuration keys; and
- rollback means activating a previously validated version, not deleting
  history.

Define the configuration fingerprint included in detection runs, capability
snapshots, rendering, and posting policy decisions.

### Documents to update

- `docs/specs/data-model.md`
- `docs/specs/detection.md`
- `docs/specs/idea-intake-and-determination.md`
- `docs/specs/visual-rendering.md`
- `docs/specs/posting.md`
- `docs/specs/reliability.md`
- `docs/system.md`

### Done when

Every registry has a named writer, validation process, activation transaction,
and historical audit trail.

## 11. Add persisted capability and destination readiness

**Priority:** P0

### Problem

Determination freezes prerequisite availability, capability re-evaluation
depends on a changed readiness fingerprint, and the dashboard displays Meta
token-expiry health. The docs do not define one persisted readiness source.
Meta says `token_expires_at` may live in configuration or an unspecified health
record.

### Recommended resolution

Add a safe `capability_readiness` or `destination_health` record containing:

- capability/destination/account identity;
- configuration fingerprint;
- checked time and expiry;
- enabled/ready/degraded/blocked state;
- typed blocking reasons;
- non-secret token expiry;
- renderer/profile availability;
- provider/media-domain readiness; and
- updater/build/version information.

Define which process updates it and at what cadence. Determination, route
re-evaluation, dashboard health, and posting preflight must consume the same
persisted record.

### Documents to update

- `docs/specs/data-model.md`
- `docs/specs/idea-intake-and-determination.md`
- `docs/specs/runtime.md`
- `docs/specs/dashboard.md`
- `docs/specs/posting.md`
- `docs/platforms/meta.md`

### Done when

Changing safe dependency readiness produces one auditable fingerprint change
that all consumers interpret consistently.

## 12. Define the O2 teaching-reference catalog

**Priority:** P0

### Problem

O2 requires every teaching claim to map to a versioned operator-approved
reference, but the catalog has no location, format, owner, initial contents,
refresh policy, or activation process. A source content hash alone is
insufficient to prove which claim it supports.

### Recommended resolution

Define a catalog entry with:

- stable reference ID and version;
- provider/title/source URL;
- retrieved/approved time;
- approved structured meaning, nuance, register, region, usage, and misuse
  assertions or bounded excerpts;
- content hash;
- permitted claim IDs/types;
- active/superseded state; and
- human approval/audit metadata.

Define how the pipeline obtains these assertions, what Gemini receives, what is
validated deterministically, and what happens when a source changes. Do not use
trend evidence as teaching evidence unless it independently supports the claim.

### Documents to update

- `docs/pipelines/o2-english-instagram.md`
- `docs/specs/data-model.md` or the configuration-manifest contract
- `docs/specs/reliability.md`

### Done when

An O2 claim can be traced to the exact approved assertion supplied during
generation without fetching or interpreting an undocumented source at runtime.

# Phase 5 — Complete deterministic detection

## 13. Define source-specific scoring mathematics

**Priority:** P0

### Problem

The scoring model defines `A_s` only for publisher feeds and Wikimedia, while
YouTube and Hacker News are target-enabled. The generic completed 24-hour
window also does not directly fit 30-minute rank snapshots and cumulative
provider statistics.

### Required source table

For each source kind define:

- measurement window and snapshot time;
- exact raw observation;
- exact `A_s` activity;
- equivalent baseline window for `B_s`;
- `G_s` momentum;
- prominence population and `P_s`;
- completeness criteria;
- missing/degraded behavior;
- pagination/stopping rules;
- repeated-snapshot de-duplication; and
- persistence/freshness contribution.

For YouTube, specify `maxResults=50`, pagination through the intended chart
limit, included `part` values, and the local quota calculation. The official
`videos.list` method defaults to five items and permits up to 50 per page:
https://developers.google.com/youtube/v3/docs/videos/list

For Hacker News, correct the impossible rule that detail is fetched when a
stored score “changed.” The Top Stories endpoint returns ordered IDs, not the
new item scores needed to detect that change. Choose a bounded refresh policy
for current listed items. Official API:
https://github.com/HackerNews/API

### Documents to update

- `docs/specs/detection.md`
- `docs/specs/data-model.md`
- source-provider references if split out

### Done when

The same frozen source fixtures always produce a fully specified score for all
four enabled source kinds.

## 14. Split source collection attempts from aggregate Scout evaluation

**Priority:** P0

### Problem

`detection_runs` currently appears to represent both a source-provider call and
the complete aggregate scoring/shortlist cycle. Partial source failure and
retry behavior are therefore ambiguous.

### Recommended model

```text
SourceCollectionAttempt (one source instance/provider operation)
  → ScoutEvaluationRun (one frozen set of usable collections)
  → candidate snapshots
  → shortlist transaction
```

The evaluation run should record which collections were current, reused,
degraded, unavailable, failed, or quota-limited. Retrying one provider should
not repeat successful calls or silently replace the frozen input of a completed
evaluation.

### Documents to update

- `docs/specs/data-model.md`
- `docs/specs/detection.md`
- `docs/specs/runtime.md`
- `docs/specs/reliability.md`

### Done when

One failed source has deterministic effects on collection retry, source health,
scoring eligibility, and the frozen evaluation audit.

## 15. Complete URL, feed, and collection canonicalization

**Priority:** P1

Define:

- canonical URL normalization when a feed GUID is absent;
- HTTP redirect handling and final-URL audit;
- duplicate items across source instances in the same independence group;
- YouTube/Hacker News title changes over time;
- provider timestamps that are absent, future-dated, or malformed;
- maximum feed/item/title/payload sizes;
- pagination completeness and partial response behavior; and
- exact state/event written for rejected, dead, deleted, or non-story provider
  items.

Keep these rules deterministic and LLM-free.

# Phase 6 — Align target configuration documentation

## 16. Replace legacy `.env.example` settings

**Priority:** P0

### Conflicts to remove

- `CONTENT_FACTORY_MINIMUM_TREND_SCORE=0.25` conflicts with `0.6000`.
- `CONTENT_FACTORY_TOP_N_CANDIDATES=5` conflicts with rolling 2/6 budgets.
- generic `CONTENT_FACTORY_RETENTION_DAYS=90` conflicts with the tiered
  retention policy.
- arbitrary RSS/Atom URL lists and BBC/NPR examples conflict with the persisted
  source registry and approved initial NASA instance.
- Reddit and Google Trends are not target-enabled source kinds.

### Recommended resolution

- Make `.env.example` contain only target runtime secrets and composition-root
  settings.
- Put non-secret source/capability/policy/profile configuration in the versioned
  configuration manifests from Item 10.
- Add missing target settings for artifact root, backup volume, dashboard bind,
  budget pricing/fallback, and any explicitly configurable runtime values.
- Ensure every environment key has exactly one owning specification.

### Documents/files to update

- `.env.example`
- `docs/system.md`
- relevant owning specifications
- `scripts/check_docs.py`

### Done when

No setting in `.env.example` enables a removed source or contradicts a target
policy.

# Phase 7 — Finish O2 and visual content contracts

## 17. Remove contradictory deferred visual language

**Priority:** P0

### Problem

`visual_spec_v1` now defines dimensions, safe areas, font family, encoding,
templates, capacities, and regression thresholds. The same document still says
those fields, tokens, and tests are deferred to a future deep dive.

### Recommended resolution

- Delete obsolete “deferred,” “planned,” and “will be defined” statements for
  matters already decided.
- Identify the few genuinely unresolved profile details explicitly.
- Do not label the contract implementation-ready until those details are
  complete.

### Document to update

- `docs/specs/visual-rendering.md`

## 18. Complete `editorial_clean_v1` and visual regression rules

**Priority:** P0

Define:

- actual palette tokens and contrast requirements;
- typography scale, weights, line heights, and exact font files/hashes;
- template geometry and binding types;
- font readiness and screenshot timing;
- browser animation/transition disabling;
- pinned Playwright/Chromium/device-scale/runtime contract;
- perceptual-difference algorithm/tool and color space;
- how the 0.5% threshold is calculated;
- golden-fixture review/update procedure; and
- validation error categories.

Recommended structure:

```text
docs/profiles/editorial-clean-v1.md
```

Keep the shared Visual Rendering document focused on generic renderer behavior.

### Done when

Two implementations can render the same fixture without choosing undocumented
design tokens, timing, or comparison behavior.

## 19. Complete O2 creative, metadata, and evidence validation

**Priority:** P0

Beyond the JSON Schemas from Item 9, define:

- exact normalization performed before `o2_word_count_v1`;
- field-level claim-reference placement;
- deterministic caption components and serializer;
- allowed CTA forms;
- deterministic tag/hashtag serialization;
- how CEFR B1–B2 suitability is assessed;
- which teaching checks are structural versus model-assisted;
- how generated-example naturalness and intended sense are validated;
- exact prompt/schema/model configuration ownership; and
- validation/error categories controlling the two creative and metadata
  attempts.

### Documents to update

- `docs/pipelines/o2-english-instagram.md`
- O2 JSON Schemas
- `docs/specs/reliability.md` for model-attempt safety only

### Done when

The pipeline can accept or reject an output solely from frozen job/reference
input, versioned schemas, and named validation rules.

# Phase 8 — Resolve review, delivery, cost, and capacity policy

## 20. Correct fresh-review-cycle expiry

**Priority:** P0

### Problem

An awaiting review expires 14 days after its RenderRun succeeds, but an
unchanged package may open a fresh cycle after that expiry. A new cycle over the
same RenderRun would already be expired if the same timestamp remains the
deadline basis.

### Recommended resolution

- Calculate a permitted fresh cycle's expiry from the new ReviewRequest's
  creation time after revalidating the unchanged asset bytes, hashes,
  destination, and current provider policy; or require a new RenderRun.
- Recommended for unchanged verified bytes: allow a new review-cycle deadline
  from cycle creation.
- Reject a new cycle if physical delivery assets have been deleted or cannot be
  revalidated.
- Keep a confirmed-published package permanently ineligible.

### Documents to update

- `docs/specs/posting.md`
- `docs/specs/dashboard.md`
- `docs/specs/data-model.md`
- `docs/specs/reliability.md`

### Done when

An expired item has one implementable path: permanently closed, re-rendered, or
newly reviewable from a well-defined timestamp.

## 21. Separate content approval from delivery readiness

**Priority:** P1

Clarify whether an expired token or temporary provider outage invalidates the
human's content approval or merely blocks/defers the Post Record. Recommended:

- content/package/hash approval remains historical truth;
- the Post Request may expire under its authorization policy;
- destination/account changes invalidate the binding;
- temporary credential/provider readiness blocks delivery but does not pretend
  the human rejected the content; and
- renewed delivery after authorization expiry requires a fresh review cycle.

## 22. Make Gemini cost policies enforceable

**Priority:** P0

### Problem

The docs define USD 5/USD 8 daily thresholds, a USD 0.25 O2 job cap, and
worst-case reservations. The environment contract permits blank/unknown price
rates. A USD hard stop cannot be enforced when model pricing is unknown.

### Recommended resolution

- Keep token limits independently enforceable.
- Require an activated, versioned local price estimate before claiming that a
  USD ceiling is enforced.
- If price is unknown, either block new Gemini work or explicitly enter a
  visible token-only budget mode.
- Reserve worst-case cost against both daily and per-job limits before the call.
- Define `gemini_budget_reservations` status transitions and uncertain-call
  settlement/release authority.

### Documents/files to update

- `docs/specs/reliability.md`
- `docs/specs/data-model.md`
- `docs/pipelines/o2-english-instagram.md`
- `.env.example` or the configuration manifest

### Done when

Every model admission decision is computable before the provider call, even
when the prior attempt is cost-uncertain.

## 23. Add production admission and backlog control

**Priority:** P0 for unattended automation

### Problem

Detection may select six candidates per day, while O2 may publish only one item
per account day. No policy stops automatic generation/rendering from producing
review backlog and cost faster than delivery capacity.

### Recommended resolution

- Add a versioned pipeline/account production-admission policy.
- Keep accepted jobs persisted, but make expensive GenerationRuns eligible only
  while review/approved backlog is below a small threshold.
- Distinguish `waiting_capacity` from technical retry/failure.
- Give explicit human ideas a documented priority or override.
- Display capacity state and estimated queue age in the dashboard.

Recommended POC default: at most one or two unreviewed O2 packages at once.

### Documents to update

- `docs/specs/data-model.md`
- `docs/specs/runtime.md`
- `docs/specs/dashboard.md`
- `docs/specs/idea-intake-and-determination.md` if capacity affects routing
- `docs/pipelines/o2-english-instagram.md`

### Done when

Automatic selection cannot create an indefinitely growing paid production
backlog under the one-post-per-day destination policy.

## 24. Complete cancellation after external staging

**Priority:** P1

Define the race in which R2 objects or Meta child containers exist but the final
publication marker has not been committed:

- recheck cancellation in the final-marker transaction;
- prevent `media_publish` when cancellation won;
- terminate the active PostAttempt with an explicit status;
- create cleanup tasks for staged R2 objects;
- retain/audit unused Meta resources; and
- prove the behavior with a boundary test.

Do not weaken the rule that a possibly transmitted final request becomes
`publication_unknown`.

## 25. Add exact Meta adapter request/response contracts

**Priority:** P1 before adapter implementation

The Meta reference should define, for the pinned API version:

- exact child-container request fields;
- parent-carousel request fields and ordering;
- status polling fields and provider status mapping;
- readiness timeout/poll strategy;
- final publish request/response;
- typed error mapping and safe retry stage;
- publication resource roles; and
- exact read-only reconciliation queries and pagination.

Continue rechecking official provider support before implementation. The
Facebook documentation was rate-limited during this review, although Meta's
maintained Postman collection broadly confirms the Professional-account,
Page-link, permission, public-media, and `media_publish` model:
https://www.postman.com/meta/instagram/documentation/6yqw8pt/instagram-api

## 26. Harden transient R2 object exposure

**Priority:** P1 before unattended publication

The decision to prohibit `r2.dev` for production is correct. Cloudflare also
documents it as a rate-limited development endpoint:
https://developers.cloudflare.com/r2/buckets/public-buckets/

Add:

- high-entropy attempt-specific object keys;
- byte/hash verification after upload;
- appropriate non-cacheable or short-cache headers;
- custom-domain cache/purge behavior;
- verified anonymous retrieval before container creation;
- verified unreachability after cleanup where caching permits; and
- bucket lifecycle configuration verification, not just an assumed seven-day
  backstop.

# Phase 9 — Complete recovery, storage, and maintenance

## 27. Add audited recovery for terminal local failures

**Priority:** P1

### Problem

After the maximum executions, local work becomes terminal `failed`. The
dashboard exposes no retry control, but runtime promises a safe operator action.
A temporary provider outage or repaired renderer defect can therefore strand a
valid immutable job/package.

### Recommended resolution

Define an audited `RecoveryRequest` or explicit operator command that may create
a new GenerationRun, RenderRun, CleanupTask, or other safe local work item from
unchanged immutable input.

It must:

- identify the failed record and reason;
- validate that no ambiguous external side effect occurred;
- use a unique command ID and actor;
- preserve the failed record;
- create a new linked work item rather than reset history; and
- prohibit recovery-based retries of `publication_unknown`.

### Documents to update

- `docs/specs/data-model.md`
- `docs/specs/runtime.md`
- `docs/specs/reliability.md`
- `docs/specs/dashboard.md` if the UI may request recovery

## 28. Bound high-volume SQLite retention

**Priority:** P1 — local-first sustainability

### Problem

All SQLite audit rows are currently retained indefinitely, including frequent
unselected observations, source health, detection runs, worker runs, and
five-minute storage samples. Artifact bytes are bounded, but database growth is
not.

### Recommended retention tiers

- Indefinite: selected-candidate frozen evidence, thread/revision lineage,
  decisions, packages, review, delivery, reconciliation, configuration
  versions, and publication history.
- Time bounded: unselected raw observations and unsuccessful candidate detail,
  for example 90 days.
- Rolled up/time bounded: worker runs, source-health detail, storage samples,
  and other high-frequency operational telemetry.
- Preserve audit summaries/checksums and retention-run counts when detail is
  removed.
- Never remove data needed to explain selected content or a public/uncertain
  publication.

### Documents to update

- `docs/specs/reliability.md`
- `docs/specs/data-model.md`
- `docs/specs/dashboard.md`

## 29. Add a Maintenance Worker/runtime contract

**Priority:** P1

### Problem

Reliability defines daily backup, monthly restore verification, WAL checkpoint,
and artifact retention. The data model defines `maintenance_runs`, but runtime
has no owning process or schedule.

### Required contract

- process/worker name;
- `launchd` schedule;
- overlap lock;
- backup retry and failure policy;
- old-backup deletion ownership;
- monthly restore trigger;
- WAL checkpoint behavior;
- artifact/telemetry retention scheduling;
- heartbeat/freshness thresholds; and
- dashboard operator guidance.

Also define fail-safe startup and claim behavior when the Storage Monitor has no
sample or its latest sample is stale. Recommended: block new expensive/model/
external claims until one current normal sample exists.

### Documents to update

- `docs/specs/runtime.md`
- `docs/specs/reliability.md`
- `docs/specs/data-model.md`
- `docs/specs/dashboard.md`

# Phase 10 — Reduce documentation drift as the system grows

## 30. Preserve the Tier 1/Tier 2 model but add supporting document classes

**Priority:** P1

The current structure is still workable. Do not perform a wholesale rewrite.
Instead, describe it as two **canonical** tiers plus supporting classes:

```text
docs/
  system.md                  # canonical Tier 1 map/router
  specs/                     # canonical shared Tier 2 contracts
  contracts/                 # canonical machine-checkable schemas
  pipelines/                 # canonical pipeline contracts
  sources/                   # time-sensitive detection-provider references
  platforms/                 # time-sensitive delivery-provider references
  profiles/                  # concrete renderer profile/theme contracts
  plans/                     # noncanonical implementation plans
  archive/                   # historical rationale
```

Split only concerns with a distinct owner and change cadence. Do not create one
document per table or minor concept.

### Documents to update

- `docs/system.md`
- `README.md`
- `AGENTS.md`
- `scripts/check_docs.py`

## 31. Tighten canonical ownership and remove repeated exact policy values

**Priority:** P1

Recommended ownership:

| Concern | Canonical owner |
| --- | --- |
| Columns, statuses, FKs, constraints | Data Model |
| Poll/lease/retry timing | Runtime |
| Cross-stage safety invariants | Reliability |
| Post now/cadence/review expiry | Posting |
| Meta endpoints/provider limits/statuses | Meta platform reference |
| Generic rendering/profile implementation | Visual/profile contract |
| O2 content, role bindings, format | O2 pipeline |

Other documents should summarize and link, not repeat exact values unless a
documentation check verifies equality. Current duplication includes posting
cadence, final-publication safety, visual capacities, delivery steps, and Meta/
R2 configuration.

## 32. Align `AGENTS.md`, README, and the system guide

**Priority:** P1

Required fixes:

- `AGENTS.md` requires both tests and documentation checks for every handoff,
  while `docs/system.md` requires only the documentation check for docs-only
  changes. Choose one rule and make both identical.
- Update the AGENTS responsibility-chain summary to include or link to the
  durable Intake, GenerationRun, RenderRun, ReviewRequest, PostRequest, and
  PostRecord boundaries.
- README's documentation layout does not mention the noncanonical plan or
  future contract/source/profile classes.
- Ensure all entry points say legacy application code is not architectural
  authority.

## 33. Move and version the noncanonical implementation plan

**Priority:** P1

Recommended path:

```text
docs/plans/target-implementation.md
```

Add:

- plan status;
- created/last-reviewed date;
- target contract revision or commit;
- owner;
- completion/update rule; and
- explicit statement that canonical contracts win.

Reorder the initial vertical slice so four-source detection does not block the
human-originated O2 proof:

1. state foundation;
2. human Intake and Determination;
3. O2 generation;
4. rendering and review;
5. dashboard Post now;
6. Posting/Meta safety;
7. detection sources incrementally; and
8. runtime hardening.

At minimum, Detection must depend on the completed Thread/Intake boundary
because selected candidates create those records.

## 34. Add contract maturity metadata

**Priority:** P2

Each canonical document should state:

- role;
- owner;
- maturity: `draft`, `approved_for_implementation`, or `superseded`;
- contract/version identifiers;
- last architectural review date;
- upstream/downstream dependencies; and
- whether provider facts require reverification.

This describes contract maturity, not implementation status.

Also define normative use of “must,” “should,” and “may.”

## 35. Strengthen documentation conformance checks

**Priority:** P2, after canonical corrections

The current checker passes despite the conflicts above. Extend it to detect:

- missing required documents and metadata;
- unresolved local links and invalid anchors;
- empty same-level headings;
- forbidden legacy environment settings;
- required JSON Schema files;
- canonical record and status names;
- duplicate exact policy definitions where possible;
- missing provider verification dates;
- system-router coverage for every active contract; and
- stale/deferred markers in approved-for-implementation contracts.

Two present structural examples are empty `## Health and operations` and empty
`## Required constraints and indexes` headings before another same-level
heading.

## 36. Define operational-data classification and minimization

**Priority:** P2

Human messages and snapshots are retained in backups and may contain accidental
personal information or secrets. Define:

- operator warning not to paste credentials;
- which human/source text is sent to Gemini;
- maximum retained text sizes;
- redaction behavior for diagnostics versus authoritative messages;
- whether an explicit privacy deletion process is needed before production;
- backup implications; and
- fields that must never contain raw provider payloads or credentials.

# Final completion gate

The documentation is ready for broad spec-driven implementation when all of
the following are true:

- opportunity identity and coverage identity are distinct and collision-safe;
- every work record has one named creator and one consumer;
- the Pipeline Runner and Visual Renderer each have one claimable input;
- the baseline schema and JSON contracts require no implementation invention;
- all registries have a controlled writer and activated version;
- capability/destination readiness has one persisted source;
- all four detection sources have exact collection and scoring rules;
- `.env.example` contains only target configuration;
- O2 teaching evidence and visual profile contracts are complete;
- review renewal, budget admission, production capacity, and terminal recovery
  are implementable;
- high-volume SQLite data and maintenance work are bounded and owned;
- Tier 1, AGENTS, README, derived plans, and tooling describe one documentation
  operating model; and
- `py scripts/check_docs.py` passes strengthened semantic checks.

After that gate, implementation should proceed by the revised vertical-slice
plan, deriving boundary tests directly from each canonical contract.
