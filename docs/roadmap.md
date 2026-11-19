# Roadmap

The [product measures](product.md) guide scope. English content-quality and visual
design refinement are deliberately **last**. Publishing and measurement foundations
can be developed independently with synthetic content; offline success establishes
no live publication, model quality, learner outcomes or revenue.

| Phase | Deliverable | Completion gate |
| --- | --- | --- |
| 1 — repository foundation (done) | Current contracts, repository cleanup and goal-oriented docs. | Retained safeguards and fresh bootstrap have offline coverage. |
| 2A — English evaluation preparation (done) | Global A1–B1 brief, rubric, reusable cases and evaluation procedure. | Offline preparation only; no measured quality claim. |
| 2B0 — acceptance safety (done) | Per-attempt provider caps and truthful failure/cost accounting. | Offline safeguards retained; paid calibration remains deferred. |
| 3A — offline Instagram readiness | Deterministic unapproved JPEG candidates; isolated explicit review/Post now rehearsal through existing posting, relay, cleanup and reconciliation contracts; read-only evidence. | Offline tests and docs pass, exact-asset approval is preserved, and PR receives ChatGPT architectural review. No production DB migration, live adapter, upload or public send. |
| 3B1 — exact JPEG review and authorization | Append-only delivery revisions, independent human approval, separate Post now, explicit v18→v19 offline migration and local report/CLI. | Offline regression and migration/recovery checks pass; hold PR for ChatGPT architectural review. No provider calls or publication. |
| 3B2 — provider foundation (complete offline only, PR #12) | Disabled-by-default adapter, bounded preflight/run authorization, acceptance and verified offline receipt evidence, conservative reconciliation and safe resource management. | Offline foundation merged. Real account identity, permissions, media/owner/readback semantics and R2 behavior remain unverified. |
| 3B live verification/activation — pending | Separately authorized account/login/version/quota and narrowly bounded delivery/resource tests. | Explicit owner approval, finite external-call/billing plan and independently verified provider contracts; no unattended publishing. |
| 4A — measurement foundation (complete offline only, PR #14) | Immutable observations, correction history, cost attribution and one-destination reports on schema v20. | Merged. Authenticated platform evidence requires a separate issuer. |
| 4B0 — offline Insights collection | Documented Instagram Login v27 account reach and carousel saves through bounded fixture GETs and schema v20. | Offline tests and documentation checks. ChatGPT architectural review requested. |
| 4B1 — real read-only preflight (pending owner authorization) | One professional account, least-privilege token, independently verified version, identity, receipt and metric windows. | Approve a finite GET budget and verify live account behavior before enabling any authenticated writer. |
| 5 — account-first expansion where justified | Account-specific identity, policy, credentials, history and budgets; other platforms only where useful. | Demonstrated one-account loop and isolated authorization/attribution tests before expansion. |
| Final — English quality, visual refinement and paid calibration | Bounded Gemini samples and human teaching/design review; evidence-based prompt/layout corrections and economics calibration. | Separate authorization and finite budgets; unknown spend reconciled, quality and effort assessed by level/family, provisional targets agreed with owner. |

## Next integration decisions

The first audience remains [global English learners at A1–B1](product.md#english-learning-pilot-brief).
The [posting contract](specs/posting.md) maps the existing infrastructure and the
implemented immutable-package boundary, fake-provider integration and remaining real-adapter requirements. Its versioned Meta adapter specification
separates documentation evidence from tested behavior. Reuse the current
domain-to-one-destination binding; no speculative account schema redesign.

The [quality/cost baseline](../acceptance/english-pilot.md) is retained for the final
phase, not a prerequisite for offline infrastructure. Existing prompts, renderer
algorithms, archetypes and accepted baseline are preserved. Human approval of each
exact delivery artifact and caption/alt text remains mandatory even while design
improvement is deferred. Synthetic review commands do not approve real content.

Live validation requires separate authorization. The pending integration must preserve the implemented separate delivery approval boundary and
connect one selected
login flow and one account under a finite test plan. Do not enable unattended
publishing, schedule posts or expand providers as part of that connection.

## Known limitations to carry forward

Gemini typography and factual/editorial quality still require human review.
Text-load thresholds are provisional; no retained historical report establishes
current live fidelity. Retry/checkpoint recovery has offline coverage, but live
behavior needs authorized observation. Psychology policy changes and hybrid text
rendering remain separate product experiments. A simulated receipt is not an
Instagram media ID, and the current rehearsal collects no real metrics.

## Phase 3B2 checkpoints

Checkpoint 1 implements disabled-by-default production registration/composition,
bounded authenticated transport, credential resolution/rotation checks, trusted
read-only preflight interfaces, expiring offline evidence and scoped run activation.
4–6-slide journeys use the real configuration/factory and authorization gates.
The short start window is separate from a bounded active execution grant, with
renewable fenced leases, guarded evidence refresh and realistic minute-spaced
polling. Fake clocks exercise long runs, cancellation, expiry and crash/restart;
consumed attempts cannot automatically resume or retry.
The live contract registry is empty: API version/token-introspection semantics and
owner account/app/permissions/quota require external verification. No real services
are enabled. See [posting](specs/posting.md#checkpoint-1-registered-composition-and-trusted-boundaries).

Checkpoint 1 received architectural approval as a completed checkpoint, without
merge/activation approval for the whole PR. Checkpoint 2 implements distinct
acceptance/verification/uncertainty evidence and bounded read-only reconciliation.
Only issued positive media/account evidence can confirm automatically; missing
IDs and unavailable/inconsistent readbacks stay unknown. All evidence is offline;
the selected live ownership/readback contract remains an explicit external gate.

Checkpoint 2 also received acceptance as an offline code-review checkpoint.
Checkpoint 3 implements durable child/parent orphan investigation, conservative
source-retention policy, separate exact-object release commands and bounded,
conditional R2 cleanup. Its fake-provider restart/concurrency/failure coverage
does not verify live ingestion or R2 semantics. The offline foundation merged in PR #12.
Container quota policy, detailed provider fidelity and AI-label behavior remain
deferred. The merge does not authorize live activation.
English quality and design work remains last.

## Phase 4A and remaining 4B gates

The [measurement contract](specs/measurement.md) defines synthetic versus
authenticated, human-estimated and uncollected evidence, immutable corrections,
UTC windows, incomplete internal costs and retention. Operators can inspect JSON
reports and source/receipt IDs without refreshing readiness or contacting providers.
Missing metrics remain unknown and internal cost settlement is not an invoice.

Phase 4B0 rehearses the [Instagram Login pilot contract](specs/measurement.md#instagram-login-pilot-contract).
Phase 4B1 requires separate owner authorization and evidence from the selected
account before any authenticated audience claim. English quality, visual
refinement and paid calibration remain the final phase.
