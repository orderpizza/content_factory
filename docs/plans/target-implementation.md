# Target Implementation Plan and Acceptance Matrix

**Document role:** Noncanonical implementation sequencing aid. The Tier 1
[system guide](../system.md) and its routed Tier 2 contracts remain the source of
truth; when this plan conflicts with one of them, the contract wins.

**Plan status:** Active Phase 1 target plan, not implementation status.
Actual completion, demo-only exceptions and legacy paths are recorded in
[Current state](../current-state.md); the [repository audit](../../audit_report.md)
retains repair and verification evidence.
**Owner:** System architecture.
**Created:** 2026-09-07. **Last reviewed:** 2026-09-13.
**Current milestone contracts:** immutable SQLite schemas v1–v4 and the routed
Detection, Intake/Determination, Production, Rendering, Dashboard, Posting,
Configuration, Runtime, Reliability, and Data Model contracts current at the
review date. Later work uses forward migrations toward the complete target
record model. Update this plan only after a
canonical contract changes; it must never override one.

**Use this for:** Planning a cohesive implementation slice and its boundary
tests. Do not use it to invent a schema field, status, provider fact, or product
behavior.

## Delivery sequence

| Stage | Implement only after | Scope | Acceptance evidence |
| --- | --- | --- | --- |
| 1. Detection state and configuration foundation | No prerequisite | Forward SQLite migrations for the configuration, source, collection, health, observation, evaluation, candidate, worker-health, seed-thread, and Intake-handoff records needed by the first slice; foreign keys, status validation, fenced claims, and a read-only reporting connection. | A fresh development database migrates deterministically; invalid FK/status/duplicate source schedule is rejected; two collectors cannot both finalize; the dashboard connection cannot write or migrate. |
| 2. Source ingestion | Stage 1 | Activated source registry and one adapter at a time: NASA RSS, Wikimedia pageviews, YouTube US popular, then Hacker News; bounded collection, immutable observations/item events, quota accounting, and source health. | Recorded fixtures and adapter fakes prove provenance, completeness, canonical input handling, idempotent retry, typed degradation, and zero Gemini invocation. A local run produces inspectable observations in SQLite. |
| 3. Scout evaluation and shortlist | Stages 1–2 | Frozen `ScoutEvaluationRun` inputs, deterministic clustering, approved hybrid `attention_v2` through explicit safety-v3/configuration rollout, candidate persistence, ranking, selection budget, recurrence, and selected `ContentThread` + `IntakeRequest` handoff. Preserve `attention_v1` for historical replay only. | The same fixtures always produce the same scores/order; every candidate is persisted before selection; budget/cooldown/material-evidence cases are deterministic; duplicate/restart cannot create a second seed thread or Intake handoff. |
| 4. Detection dashboard | Stages 1–3 | Loopback service, read-only reporting model, Trend Opportunities landing page, source health/freshness, observation/evidence drill-down, score breakdown, shortlist status, filters, pagination, and worker state. | Running collection and Scout commands causes the browser feed to update from SQLite without a dashboard-triggered worker/API call; stale/error states are visible; browser refresh cannot mutate state. This completes the first observable milestone. |
| 5. Freeze Phase 1 executable contracts | Stages 1–4 preserved | Multi-route/angle/brief schemas, domain extensions, canonical/output/adaptation records, separate domain/destination registries, capacity/reuse/identity constraints; reviewed forward migrations. Retire single-route draft consumers. | Positive/negative schema fixtures cover all five domains and zero/one/many jobs; SQL uniqueness permits multiple jobs/request and packages/canonical while rejecting duplicates. Existing detection v1 checksum and handoffs stay unchanged. |
| 6. Intake and five-domain routing | Stage 5 | Human commands, route-neutral briefs/coverage, source/reference context, deterministic identity serialization, Gemini ledger, five explicit route assessments, distinct angles, skips/rejection/block/reuse, atomic fan-out. | Operator-labeled fixtures prove one domain, several domains, weak-domain skip, whole-trend reject, disabled/unbound cases, duplicate/uncertain-cost guards, and no mandatory five-way output. |
| 7. Canonical domain production | Stages 5–6 | Implement English first to preserve teaching validation, then AI/Tools, Personal Finance, Business/Side Hustles, Psychology/Behavior. One shared runner with domain strategies; canonical checkpoints, evidence/claim validation, reservations and cost caps. | Each domain validates its own extension; unchanged creative is generated once; failures/restarts do not repeat paid work; no account/caption/slide geometry in canonical payload. |
| 8. Instagram/X output adaptation and static renderer | Stages 5–7 | Shared Adaptation Worker, Instagram carousel and X image + native text, immutable output packages, versioned static profiles/geometry/fonts/runtime, manifests, new visual schemas and golden fixtures. Verify provider native limits before enabling bindings. | One canonical result yields two distinct native outputs without a second generation call; adaptation/metadata retry preserves checkpoints; sibling failure is isolated; all five domains fit supported templates; exact bytes/text pass validation. |
| 9. Branch-aware dashboard and human review | Stages 6–8 | Five-domain routing trace, canonical/output portfolio, independent review cards, scoped rework, exact package/manifest/text binding, CSRF/version/idempotency commands, cost attribution. | Approving Instagram grants no X authority; scoped rework preserves unaffected siblings; source-to-output trace, skips, blockers, reuse, and costs remain visible. |
| 10. Instagram and X single-post delivery | Stage 9 plus separately verified provider contracts | Shared Posting Agent with platform-specific delivery adapters, account-scoped cadence, Meta R2 relay where required, X media workflow, attempt/resource audit, cancellation, uncertainty, cleanup/reconciliation. | Fake-provider tests cover every pre-final/final boundary; no posting-generated content; live exact-package Post now checks require separate explicit authorization for each destination. |
| 11. Optional X thread gate | Stages 8–10; optional, default disabled | Exact PublicationStep schema/state extension, ordered frozen reply text, per-step markers/IDs, partial-prefix outcomes, per-step cadence accounting, reconciliation and UI. | Fault injection at every reply boundary proves no repeated published/uncertain step, no whole-thread retry after a prefix, no false complete/unpublished status, and no unreviewed text. |
| 12. Operational and routing-quality acceptance | Stages 5–10 (11 only when enabled) | Shared launchd workers, current readiness/storage, backup/restore/retention, fan-out capacity, scoped cancellation, labeled routing replay and observed generation/review/delivery loop. | All five domains and required Instagram/X outputs exercised; routing quality reviewed, forced connections rejected, paid call counts/cost bounded, migrations/restart/restore safe. |


Stages 1–4 remain the stable detection milestone. Schemas v2–v4 now implement a
bounded path through Stages 6–10: Gemini Intake/five-domain Determination,
closed domain generation, Instagram/X adaptation, checkpointed priced calls,
pinned-font static rendering, exact review/Post now, fake-tested Instagram/X
single-post delivery, cleanup/reconciliation, storage admission, and local
backup/restore. Default/synthetic modes remain non-deliverable, and production
requires explicit Option B migration/configuration/readiness/authorization.
Stage 5 is only partially closed because model payload schemas remain in code
and target reuse/capacity records are absent. Stage 12 and live-provider/visual
quality acceptance remain open; Stage 11 remains disabled.

## Remaining work, in order

1. **Owner configuration and live acceptance:** choose prices/budgets, accounts,
   cadence, destination bindings, font/profile quality, and R2 custom-domain/
   lifecycle policy; use the implemented non-network preflight, then run
   explicit readiness and first-post acceptance per destination. These are
   genuine human/external gates, not code defaults.
2. **Routing and reference quality:** curate operator-labeled one/many/weak-skip/
   whole-reject fixtures and domain evidence standards. Measure forced routes,
   missed value, support quality, duplicate angles, and actual cost. Add a
   research service only through a separate bounded design.
3. **Runtime hardening:** basic stage heartbeats and contract-aligned initial
   leases are implemented. Add mid-call lease renewal, per-stage process
   isolation or equivalent supervision evidence, active-claim/restart
   visibility, and execution/output capacity admission. Complete unattended Mac
   Mini restart/sleep/load checks.
4. **Identity, reuse, and recurrence:** add forward records/serializers for
   cross-revision canonical reuse, material-new-evidence recurrence, cooldown,
   and consumption without weakening confirmed/uncertain publication guards.
5. **Retention and recovery:** add safe artifact/high-volume SQLite retention,
   off-device backup/runbook, operational maintenance views, and explicit local
   recovery requests. Never revive the destructive legacy cleanup path.
6. **Standalone contracts and goldens:** promote the closed in-code model
   payloads to independently versioned artifacts where operationally useful and
   add accepted visual goldens. Existing validators remain authoritative until
   a forward version replaces them.
7. **Optional X threads:** design/test ordered per-step publication, partial
   prefixes, cadence, and reconciliation before enabling the format.

## Audit-to-plan disposition

The [audit history](../archive/audits/repository-audit-2026-09.md) preserves the
original findings. The table below now lists only gaps that remain after the v4
bounded production implementation; the [active audit](../../audit_report.md)
retains historical repair verification rather than this backlog.

| Future work | Original findings | Dependency / acceptance |
| --- | --- | --- |
| Canonical reuse, consumption/cooldown/material-evidence recurrence | Remaining H10–H12, D7, D10 | New identity/reuse/recurrence records and fixtures. V4 preserves duplicate publication guards but does not claim creative reuse. |
| Capacity accounting and production supervision | Remaining H13 and production H6/M14 | Basic workflow heartbeats now exist; add slot admission, mid-call lease renewal, full claim/restart visibility, and unattended restart/load evidence. Unknown paid/public work already fails closed. |
| Reference/routing quality | Remaining H12/H14 quality work | Operator-labeled semantic fixtures, supported reference policy, and observed costs; structural schemas alone do not prove editorial quality. |
| Visual/provider acceptance | Remaining H8/H14/H15 | Pinned production font/profile and adapters are implemented/fake-tested; the owner must approve visual output and verify live Meta/X/R2 behavior. |
| Full operations portfolio and recovery | Remaining H7, M7–M11, H16 | Dashboard shows core production state and supports Post now/cancel/reconciliation; add full worker/maintenance health, local recovery commands, artifact/SQL retention, and off-device recovery. |
| Mac deployment and full production acceptance | Remaining M13/M14/D12 | Templates exist but are not installed; actual launchd/provider/visual/load/restore acceptance remains a deployment gate. |
| Optional optimizations or later migrations | M3 follow-on | Conditional feed cache/304 reuse and in-place historical normalization conversion are not prerequisites for the unconditional collector/separate-DB corrected experiment. No automatic identity rewrite. |

## Integration gates

1. Run `py scripts/check_docs.py` for docs-only work and both that command and
   `py scripts/run_tests.py` for implementation or documentation-checker changes.
2. Do not enable an unattended production worker until its input/output schema,
   migration, configuration, readiness checks, and boundary fixtures are present
   and approved. The v4 path is opt-in and remains blocked until owner/live gates
   in [Current state](../current-state.md#genuine-human-review-and-external-gates)
   are completed.
3. Use local fakes/fixtures for Gemini, Meta, X, and R2 by default. Live publishing
   requires explicit authorization for each exact package/account.
4. Preserve the existing detection/dashboard milestone and SQLite handoffs.
   These strategy changes do not authorize a DB reset or runtime activation.
5. Complete at least one observed end-to-end path per domain, the four routing
   cases (one/many/weak-skip/whole-reject), and—after it is implemented—canonical reuse across Instagram/X.
   Record versions, validation and cost evidence, human review, and delivery
   outcome; missing optional destinations are explicit, not false failures.
6. A later domain or output must reuse shared persistence, renderer, review,
   posting and runtime boundaries. No future-video infrastructure belongs in
   the Phase 1 work list.
