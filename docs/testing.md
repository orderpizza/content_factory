# Testing and acceptance

## Offline verification

From the repository root with the development environment installed:

```sh
.venv/bin/python scripts/run_tests.py
.venv/bin/python scripts/check_docs.py
```

The suite uses temporary databases, fake providers and local browser checks.
Install Chromium using `.venv/bin/python -m playwright install chromium` first;
if using a custom `PLAYWRIGHT_BROWSERS_PATH`, export the same path for tests.
No paid Gemini calls or public posting belong in routine verification.
The documentation check validates links, contract routing, schema inventory,
source roster, operator commands and environment settings.

## Safeguards and regression owners

| Boundary | Coverage in `tests/` |
| --- | --- |
| Fresh schema, configuration and packaged contracts | `test_hybrid_detection.py`, `test_configuration.py`, `test_packaged_contracts.py`, `test_visual_configuration.py` |
| Atomic handoffs, idempotency and lease fencing | `test_workflow_claims.py`, `test_planning_flows.py`, `test_workflow_planning.py`, `test_adaptation_checkpoints.py` |
| Evidence, claims and domain integrity | `test_detection.py`, `test_semantic_detection.py`, `test_gemini_workflow.py`, `test_prompt_contracts.py`, `test_domain_boundaries.py` |
| Budget, uncertainty and bounded retries | `test_model_budget.py`, `test_gemini_transport_reliability.py`, `test_render_recovery.py` |
| Geometry, asset integrity and checkpoint recovery | `test_storyboard_pagination.py`, `test_gemini_image_renderer.py`, `test_render_text_policy.py`, `test_render_recovery.py` |
| Review and duplicate-delivery protection | `test_delivery_boundaries.py`, `test_delivery_simulation.py`, `test_visual_configuration.py`, `test_workflow_planning.py`, `test_r2_relay.py` |
| Dashboard security and operator recovery | `test_dashboard.py`, `test_gemini_workflow.py`, `test_storage_and_maintenance.py` |
| Acceptance isolation and documentation integrity | `test_acceptance_harness_offline.py`, `test_acceptance_safety.py`, `test_documentation_contracts.py` |

Delivery logic is composed only into the isolated offline rehearsal, never a live
posting service. `test_delivery_simulation.py` blocks networking and exercises
exact JPEG approval, 4–6 slide success, tampering/missing assets, wrong destinations,
stale/expired reviews, preparation without inherited PNG approval, mode isolation,
pre-final outage/cancellation, crash/restart, uncertain final results, manual
resolution and independent cleanup. CLI tests cross process boundaries. Tests
authorize synthetic fixtures explicitly; they never approve operator content.
Existing tests protect
explicit approval and conservative uncertain outcomes for future integration.
Do not delete these checks merely because current operation stops at review.
Current domain/visual policy tests are not obsolete just because future accounts
will be configurable. Replace a contract and its coverage together when that
future design is approved.

## Fresh bootstrap smoke

Follow [operations](operations.md#fresh-setup) to create a new timestamped DB.
The deterministic `scripts/run_workflow.py` default exercises planning only.
Existing fake-provider journey tests exercise generation through exact review
assets; they validate mechanics, not real model quality. Never reset a local
operator database to run a smoke check.

## Opt-in paid acceptance

English quality/design calibration is deferred to the final [roadmap](roadmap.md)
phase. Retain this procedure and the Phase 2B0 attempt/accounting safeguards; they
are not prerequisites for synthetic publishing-readiness work.

[The acceptance runner](../acceptance/README.md) owns stage, chain and full-journey
commands, finite budget requirements and authorization switches. Reusable
scenarios and fixtures remain tracked in `acceptance/`; results, databases,
boards and galleries belong in ignored `data/acceptance/`. A golden scenario
asserts stable evidence/routing/output constraints, never exact generated prose.

Live acceptance needs explicit authorization and does not enable publication.
Human reviewers must inspect editorial accuracy, qualifications, typography and
visual continuity. Successful geometry or schema checks do not establish those
qualities. The controlled fidelity profile compares the same frozen package
under different board layouts; thresholds remain provisional until measured.

## English pilot human review

This rubric evaluates the [selected learner brief](product.md#english-learning-pilot-brief).
Use the [execution guide](../acceptance/english-pilot.md) and copy the
[blank report](../acceptance/templates/english-pilot-review.md) into each ignored
attempt directory. No score or decision is prefilled. An automated PASS/WARN is
not human approval. Null/unreviewed means unknown, never pass; incomplete assets
cannot pass. A report is review evidence, not a publishing authorization.

Review the canonical claim registry, adaptation/caption/alt text, raw boards and
**every final slide** in order. Compare rendered words against frozen package
copy at full resolution, then inspect the carousel at a consistent 360 CSS-pixel
width without zoom (record actual device/viewport). Review visible level/goal
signals and whether a learner could do the promised action. Log exact slide,
claim ID, expected/observed wording and artifact hash for each issue. Automated
phrase-presence tests are normalized lexical checks, not verbatim image reading.

Score each dimension 0 (unusable/incorrect), 1 (requires correction), or 2 (meets
the anchor below). Do not average away a zero. Record evidence even for a 2.

| Dimension / failure code | Anchor for 2 | Examples requiring correction or rejection |
| --- | --- | --- |
| Meaning correctness / `meaning` | Target definition, correction and model answer are accurate for the chosen use. | Wrong meaning or a taught grammatical error; unsupported etymology. |
| Naturalness / `naturalness` | Examples and replies are plausible, idiomatic and logically responsive. | Grammatically possible but unnatural expression; dialogue answers a different question. |
| Register and nuance / `nuance` | Formality, region and contextual limits are honest and understandable. | “Always” rules; certainty about private intentions; missing qualification. |
| Level and comprehension / `level` | Intended level and goal are visible; simple definitions and manageable new vocabulary explain the lesson without a shared first language. | Unexplained jargon/idioms; unsupported culture or occupation assumptions. |
| Semantic fidelity / `semantic_drift` | Canonical claims, qualification and exact target survive public adaptation and image rendering. | Reversed polarity, missing required claim, invented advice or misleading visual implication. |
| Visual readability / `readability` | All text readable at the recorded mobile width; clear contrast, whitespace, speaker attribution and useful visuals; caption/alt text agree. | Tiny text, cropping, clutter, color-only explanation, ambiguous speaker or object. |
| Typo/text fidelity / `text_fidelity` | All intended words, spelling, punctuation and target casing remain correct and legible; no invented text. | Missing/duplicated/altered words, malformed glyphs; duplicated deterministic labels. |
| Slide count and sequence / `sequence` | Requested 4–6 slides, correct semantic progression, no missing/repeated/empty slide or board seam disruption. | Wrong count/order, visible grid leakage, dropped dialogue/takeaway. |
| Coherence / `coherence` | One goal connects hook, meaning, examples/dialogue and practice; visuals/characters remain understandable across boards. | Disconnected story, contradictory examples, unstable speaker identities. |
| Distinctiveness / `distinctiveness` | Each slide adds learning value and this lesson has a specific use, beyond generic motivation or restating the title. | Padding to reach a count; duplicate examples; indistinguishable lesson with only target swapped. |
| Actionability / `actionability` | Learner can try one small realistic action using a model answer or usable pattern. | Only “save/follow”; exercise depends on unexplained knowledge or has no usable response. |

Mechanical coverage already includes closed schemas, claim/reference membership,
copy capacities, count/roles, target presence, speaker alternation, detectable
polarity reversals, geometry, ordinals, hashes and review handoffs. It does **not**
prove meaning, naturalness, full entailment, image text accuracy, accessibility,
learner comprehension or commercial usefulness. No OCR/LLM judge is introduced.

### Decisions and severity

- **pass**: all 11 dimensions score 2, no unresolved mechanical failure or human
  issue, complete exact assets reviewed. One pass is permission to consider this
  sample for a later publication workflow, not permission to publish it.
- **needs edit**: one or more 1s, no 0/critical failure, and a specific bounded
  correction can preserve the lesson goal. Describe the change and estimate its
  effort; it is not approved until the resulting assets receive a new review.
- **reject**: any 0, a critical error, incomplete output, or correction would require
  a different lesson/wholesale rewrite. Retain the failed sample and its costs.

Critical failures include incorrect taught meaning/answer, misleading universal
usage claims, loss/reversal of essential qualification, harmful stereotyping,
misleading source claims, missing slides, or unreadable/altered target text.
Minor punctuation elsewhere still needs edit; visual polish cannot compensate
for teaching errors. Add `input_ambiguity`, `contract`, `provider`, `budget`,
`billing_unknown` or `missing_artifact` for failures outside the 11 dimensions.
Use severity critical/major/minor and stage intake/canonical/adaptation/render/
review to distinguish origin from where a problem was noticed.

For the ambiguous-input control, do not apply carousel scores: mark them N/A,
not 2. Control **pass** requires a relevant clarification question and no invented
brief or downstream content. A generic unhelpful question needs edit; invented
teaching content is reject. Control results never enter carousel approval rates.

A reviewer competent in English teaching should complete each report. A second
reviewer independently assesses all critical findings and at least one completed
sample per level. Keep both ratings and adjudicate differences with evidence;
an unresolved disagreement prevents pass. Agent observations may help triage,
but are not a completed human panel or evidence of learner performance.

Capture first decision before any edits; keep review time separate from active
editing and re-review time. Record estimated and actual minutes, edit scope
(copy/visual/both/replan), changed units, revision count, provider calls for
regeneration, and exact reviewed package/asset hashes. Never silently overwrite
immutable evidence or count a proposed edit as completed. Link a revised attempt
to the original and count the same lesson only once in final approvals.

### Provisional operating targets

These are proposed discussion thresholds, adjustable with the owner **after** the
baseline, not a validated SLA or a reason to remove failed attempts:

- Zero critical errors in approved assets; every attempted carousel has a decision
  or an explicit missing-review reason and reconciled spending evidence.
- At least 8/10 planned positive carousel attempts pass on first review, and at
  least 9/10 after at most one bounded edit/re-review. Report raw counts by level
  and family; a 10-sample result has large uncertainty.
- Median first-review time at most 5 minutes per completed carousel; median active
  edit time at most 10 minutes among edited samples; report range and sample count.
- Provisional model-spend target at most USD 1 per finally approved carousel,
  including failed/rejected attempts and the ambiguity controls. Report operator
  time separately and at an owner-selected hourly rate; no assumed free labor.

The initial plan is 10 positive attempts plus two clarification controls. Report
first-pass approvals / 10 planned positive attempts alongside approvals /
actually started positive attempts and approvals / completed renders, with all
three denominators stated. A budget skip is not a quality failure, but it is a
missing planned sample and does not silently reduce the plan denominator.
Report provider/contract failures, rejections and needs-edit counts separately.
Cost per approved = all campaign model spend / distinct finally approved lessons;
tokens and image calls per approved use the same denominator. Include all attempts
and revisions, not just successful render-board entries. If none are approved,
report undefined rather than zero. Report settled costs, outstanding reservations
and uncertain holds separately; do not present a partial settled total as complete.

Published count and cost per published are N/A in Phase 2A/2B. Later, divide all
campaign costs by confirmed published carousels and include delivery costs, with
receipt/observation window provenance. Engagement, retention and learning gains
require separate audience measurement; a human rubric pass establishes none.


## Phase 3B1 offline delivery revision coverage

`tests/test_delivery_revision.py` drives real intake, determination, editorial,
generation, adaptation, storyboard and PNG rendering workers with injected offline
responses, then the production preparation/approval/Post now path. It runs on
fresh and migrated schemas; it never uses `seed_review` to import production
lineage. It checks original evidence retention, independent approvals, immutable
copy/alt/provenance, exact bytes/order/count, stale commands, destination/account,
revoked readiness, expiry/rejection, path containment, duplicate canonical
publication identities, process restart and the empty adapter registry.
Migration checks cover read-only dry run, preserved rows/ledger/backup,
transaction rollback before commit, restore-copy validation, idempotent bootstrap
and rejection of altered schemas/overwritten backups. CLI/report tests verify
read-only self-contained escaped HTML and explicit inspection acknowledgment.
The prior delivery simulation, claim/fencing, uncertain-outcome, R2 and acceptance
safety tests remain part of `scripts/run_tests.py`. No test authorizes or proves a
real provider send; current configuration/readiness integration remains a Phase
3B2 gate. English quality and visual refinement stay in the final phase.


### Phase 3B2 offline integration (incomplete)

`tests/test_instagram_posting_integration.py` exercises 4-, 5- and 6-slide genuine
Phase 3B1 revisions through immutable production registration, preflight, JPEG
approval, Post now, scoped activation and the actual adapter factory. There is no
production-configuration monkeypatch. Fake HTTP and storage cover child/parent/final
response loss, receipt persistence failure, freshness/rotation/activation expiry,
restart, durable quota reservations and no duplicate send. Fresh and migrated
schemas are exercised without migrating an operator DB.

`test_instagram_composition.py` checks default-disabled registration, no side
effects from configuration/preflight, trust provenance, caller-forged evidence,
account/app/login/scopes/version/token/quota failures and secret-free persistence.
Offline evidence stays degraded and is ineligible outside the network-refusal
boundary. `test_instagram_http.py` covers TLS host pinning, bounded request/response
sizes, redirects, response version, safe diagnostics, no POST retry and hard child
process deadlines. All external dependencies are fake; no live endpoint is tested.
The original protocol tests retain exact bytes/order/alt mapping and intent fences.

`test_instagram_execution.py` uses fake wall/monotonic clocks and the same real
factory/configuration path for 4–6 slides. Provider responses consume simulated
time; containers process for one, two or four minutes each, with total attempts
exceeding both two and five minutes. Assertions cover minute-spaced bounded polls,
lease renewal, fresh readiness and single consumption/final send. Failure cases
cover expired unused activation, execution deadlines, clock rollback, cancellation,
claim loss (including during refresh and after the final marker), revoked readiness,
credential/asset changes, late responses, and restart after crashes before upload or
after create. No real sleeps or external operations are needed for these journeys.

The full suite still owns legacy delivery/idempotency/migration/review safeguards.
Passing it does not prove a supported live API version, authenticated account
capabilities, real receipt attribution or safe cleanup timing. Those gates remain
explicitly blocked/deferred in the [posting contract](specs/posting.md).
