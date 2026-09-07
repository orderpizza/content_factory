# Target Implementation Plan and Acceptance Matrix

**Document role:** Noncanonical implementation sequencing aid. The Tier 1
[system guide](../system.md) and its routed Tier 2 contracts remain the source of
truth; when this plan conflicts with one of them, the contract wins.

**Plan status:** Active Phase 1 target plan, not implementation status.
**Owner:** System architecture.
**Created:** 2026-09-07. **Last reviewed:** 2026-09-08.
**Current milestone contract:** `detection_dashboard_schema_v1` and the routed
Detection, Dashboard, Configuration, Runtime, and Data Model contracts current
at the review date. Later stages extend the database through forward migrations
toward the complete target record model. Update this plan only after a
canonical contract changes; it must never override one.

**Use this for:** Planning a cohesive implementation slice and its boundary
tests. Do not use it to invent a schema field, status, provider fact, or product
behavior.

## Delivery sequence

| Stage | Implement only after | Scope | Acceptance evidence |
| --- | --- | --- | --- |
| 1. Detection state and configuration foundation | No prerequisite | Forward SQLite migrations for the configuration, source, collection, health, observation, evaluation, candidate, worker-health, seed-thread, and Intake-handoff records needed by the first slice; foreign keys, status validation, fenced claims, and a read-only reporting connection. | A fresh development database migrates deterministically; invalid FK/status/duplicate source schedule is rejected; two collectors cannot both finalize; the dashboard connection cannot write or migrate. |
| 2. Source ingestion | Stage 1 | Activated source registry and one adapter at a time: NASA RSS, Wikimedia pageviews, YouTube US popular, then Hacker News; bounded collection, immutable observations/item events, quota accounting, and source health. | Recorded fixtures and adapter fakes prove provenance, completeness, canonical input handling, idempotent retry, typed degradation, and zero Gemini invocation. A local run produces inspectable observations in SQLite. |
| 3. Scout evaluation and shortlist | Stages 1–2 | Frozen `ScoutEvaluationRun` inputs, deterministic clustering, `attention_v1`, candidate persistence, ranking, selection budget, recurrence, and selected `ContentThread` + `IntakeRequest` handoff. | The same fixtures always produce the same scores/order; every candidate is persisted before selection; budget/cooldown/material-evidence cases are deterministic; duplicate/restart cannot create a second seed thread or Intake handoff. |
| 4. Detection dashboard | Stages 1–3 | Loopback service, read-only reporting model, Trend Opportunities landing page, source health/freshness, observation/evidence drill-down, score breakdown, shortlist status, filters, pagination, and worker state. | Running collection and Scout commands causes the browser feed to update from SQLite without a dashboard-triggered worker/API call; stale/error states are visible; browser refresh cannot mutate state. This completes the first observable milestone. |
| 5. Freeze Phase 1 executable contracts | Stages 1–4 preserved | Multi-route/angle/brief schemas, domain extensions, canonical/output/adaptation records, separate domain/destination registries, capacity/reuse/identity constraints; reviewed forward migrations. Retire single-route draft consumers. | Positive/negative schema fixtures cover all five domains and zero/one/many jobs; SQL uniqueness permits multiple jobs/request and packages/canonical while rejecting duplicates. Existing detection v1 checksum and handoffs stay unchanged. |
| 6. Intake and five-domain routing | Stage 5 | Human commands, route-neutral briefs/coverage, source/reference context, deterministic identity serialization, Gemini ledger, five explicit route assessments, distinct angles, skips/rejection/block/reuse, atomic fan-out. | Operator-labeled fixtures prove one domain, several domains, weak-domain skip, whole-trend reject, disabled/unbound cases, duplicate/uncertain-cost guards, and no mandatory five-way output. |
| 7. Canonical domain production | Stages 5–6 | Implement English first to preserve teaching validation, then AI/Tools, Personal Finance, Business/Side Hustles, Psychology/Behavior. One shared runner with domain strategies; canonical checkpoints, evidence/claim validation, reservations and cost caps. | Each domain validates its own extension; unchanged creative is generated once; failures/restarts do not repeat paid work; no account/caption/slide geometry in canonical payload. |
| 8. Instagram/X output adaptation and static renderer | Stages 5–7 | Shared Adaptation Worker, Instagram carousel and X image + native text, immutable output packages, versioned static profiles/geometry/fonts/runtime, manifests, new visual schemas and golden fixtures. Verify provider native limits before enabling bindings. | One canonical result yields two distinct native outputs without a second generation call; adaptation/metadata retry preserves checkpoints; sibling failure is isolated; all five domains fit supported templates; exact bytes/text pass validation. |
| 9. Branch-aware dashboard and human review | Stages 6–8 | Five-domain routing trace, canonical/output portfolio, independent review cards, scoped rework, exact package/manifest/text binding, CSRF/version/idempotency commands, cost attribution. | Approving Instagram grants no X authority; scoped rework preserves unaffected siblings; source-to-output trace, skips, blockers, reuse, and costs remain visible. |
| 10. Instagram and X single-post delivery | Stage 9 plus separately verified provider contracts | Shared Posting Agent with platform-specific delivery adapters, account-scoped cadence, Meta R2 relay where required, X media workflow, attempt/resource audit, cancellation, uncertainty, cleanup/reconciliation. | Fake-provider tests cover every pre-final/final boundary; no posting-generated content; live exact-package Post now checks require separate explicit authorization for each destination. |
| 11. Optional X thread gate | Stages 8–10; optional, default disabled | Exact PublicationStep schema/state extension, ordered frozen reply text, per-step markers/IDs, partial-prefix outcomes, per-step cadence accounting, reconciliation and UI. | Fault injection at every reply boundary proves no repeated published/uncertain step, no whole-thread retry after a prefix, no false complete/unpublished status, and no unreviewed text. |
| 12. Operational and routing-quality acceptance | Stages 5–10 (11 only when enabled) | Shared launchd workers, current readiness/storage, backup/restore/retention, fan-out capacity, scoped cancellation, labeled routing replay and observed generation/review/delivery loop. | All five domains and required Instagram/X outputs exercised; routing quality reviewed, forced connections rejected, paid call counts/cost bounded, migrations/restart/restore safe. |


Stages 1–4 are the current implementation milestone. Later stages remain
architecturally routed but must not delay a working, observable trend-ingestion
feed unless the first slice depends on their persisted boundary.

## Implementation-readiness work, in order

1. **Payloads and persistence:** define new versioned brief/routing/domain-angle/
   canonical/output payloads, exact five domain extensions, reuse references,
   parent budget ownership, forward SQL, and all status/uniqueness tests. The
   current schemas are detection-only or legacy drafts; do not implement the
   old one-job-per-request / one-package-per-job model.
2. **Editorial evidence and policies:** prepare bounded, approved evidence and
   English sense/usage assertions; freeze domain audience/jurisdiction and
   claim-validation fixtures. Detection headlines alone will not support every
   new pipeline. No research service is added implicitly.
3. **Configuration choices:** choose actual accounts and destination bindings,
   which optional English/Psychology X outputs are enabled, explicit per-account
   posting policy, supported domain reference sets, and priced per-phase limits.
   These are operator release choices, not hard-coded domain IDs.
4. **Review proposed internal defaults:** one angle/domain/revision, one
   Instagram plus one X output/domain, execution and unreviewed-capacity limits,
   shared per-job adaptation budget, output copy limits, and proposed canvases
   are conservative starting parameters in the owning contracts. Freeze and
   validate them in the first production release before any paid/public work.
5. **Native platform and profile validation:** reverify Meta and establish X's
   exact auth/media/text/error/reconciliation contract from official sources.
   Create new profile geometry, binding schemas, pinned fonts/runtime, and
   regression assets. Existing 1080×1920 geometry is not silently reused as
   1080×1350 Instagram or 1200×675 X output.
6. **Optional-thread design:** finalize per-step states, partial publication,
   expiry and cadence accounting, and human resolution before enabling threads.
   This is not required to deliver the default X image + single post.
7. **Routing evaluation:** curate operator-labeled fixtures and agree the
   acceptable routes/angles/skip rationales. Evaluate forced-route false
   positives, missed useful domains, source support, duplicate avoidance, and
   actual cost. Publication count alone does not prove the central experiment.

## Integration gates

1. Run `py scripts/check_docs.py` for docs-only work and both that command and
   `py scripts/run_tests.py` for implementation or documentation-checker changes.
2. Do not enable a worker until its input/output schema, migration, configuration,
   readiness checks, and boundary fixtures are present and approved.
3. Use local fakes/fixtures for Gemini, Meta, X, and R2 by default. Live publishing
   requires explicit authorization for each exact package/account.
4. Preserve the existing detection/dashboard milestone and SQLite handoffs.
   These strategy changes do not authorize a DB reset or runtime activation.
5. Complete at least one observed end-to-end path per domain, the four routing
   cases (one/many/weak-skip/whole-reject), and canonical reuse across Instagram/X.
   Record versions, validation and cost evidence, human review, and delivery
   outcome; missing optional destinations are explicit, not false failures.
6. A later domain or output must reuse shared persistence, renderer, review,
   posting and runtime boundaries. No future-video infrastructure belongs in
   the Phase 1 work list.
