# Roadmap and Acceptance

This is the sole backlog for unimplemented capabilities and future acceptance.
[Operations](../current-state.md) describes what runs now; focused specs describe
current contracts. Priorities below are not authorization to spend, publish,
delete evidence or change external accounts.

## 1. Planning acceptance

Run Detection, Gemini planning-only and dashboard against one development database.

| Check | Acceptance evidence | Owner |
| --- | --- | --- |
| Vertex access and budget fit | Explicitly authorized bounded real calls; inspect usage/reservations and failures | Human operator |
| Human idea → job | Review clarification, brief fidelity, five domain reasons, selected angles and job recipes | Human editorial review |
| Detection → job | Inspect source health, frozen grouping/scoring and selected handoff lineage; respect baseline warm-up | Human + developer |
| Dashboard usefulness | Read both origins, follow item/Cluster/Opportunity/job links and refine conversations without losing drafts | Human operator |

Do not lower conservative Selection gates merely to produce jobs. Offline tests
establish boundary behavior, not editorial truth or live provider access.

## 2. Content quality and validation

Before unattended production, strengthen evidence checking beyond structural
reference IDs. Add an approved, versioned teaching-reference catalog if English
quality requires it, and evaluate target/sense compatibility and natural examples.
Other domains need dated evidence, jurisdiction/context and qualified-claim
checks. Do not give generation unbounded research tools.

Acceptance: labeled fixtures for unsupported claims, misleading references,
unsafe domain advice and adaptation loss of qualifications, plus human quality
review of all five domains and both output profiles. A schema-valid response
must not be labeled fact-verified.

## Reliability and scale

Prioritize observed reliability needs before queue infrastructure:

- **Budget bounds:** validate actual input tokens against reserved phase maxima,
  including prompt/schema overhead. Current admission uses configured maxima and
  a character-size guard, not exact input token counting. Test that accepted
  calls cannot silently exceed the intended reservation assumptions.
- **Audited recovery:** define explicit operator handling for failed/uncertain
  paid calls, closed threads and expired reviews. No blind replay or approval
  reuse. A renewed review must revalidate exact bytes/destination and get fresh
  Post now authorization.
- **Coverage/reuse:** define immutable reuse links and duplicate publication
  guards before reusing canonical content across revisions. Output-only rework
  should eventually avoid generation while keeping the original job's spend.
  Test preserved siblings, changed evidence and uncertain publication.
- **Capacity/fairness:** add bounded local execution/unreviewed-output admission
  only when measured backlog warrants it. Specify slot acquisition/release and
  starvation tests; no distributed queue is justified.
- **Semantic quality:** build a labeled event corpus measuring false merges and
  missed equivalents across sources, entities, numbers and languages. Do not
  pool inferred cross-cluster scoring credit without a separately validated design.
- **Visibility:** extend historical search and summarized semantic-pair inspection
  when retained evidence becomes cumbersome; preserve bounded read-only views.

## Storage measurement and retention

Inspect actual component sizes, table counts and JSON-byte growth after 7 and
30 days. Missing/partial measurements are not zero growth. Only then choose
bounded, audited retention rules separately for database rows and rendered assets.
Preserve selected source evidence, frozen handoffs, conversations, briefs,
decisions and jobs. Backup pruning/WAL checkpoints are not database retention.
Planning must remain independent of sample freshness or measured free space.

## Delivery acceptance

Preview and production exist but need separate domain/profile quality acceptance.
Before enabling a real destination, review account bindings, font/profile,
prices/budgets, backup/restore and live readiness. A public smoke test needs exact
per-destination Post now; credentials alone do not authorize it.

Remaining integration work:

- Validate X text-weight boundaries against the provider and configured account
  entitlements; X delivery remains on hold.
- Verify Meta permissions/token lifecycle and R2 public-byte availability.
  Keep the selected r2.dev origin unless measured reliability requires a change;
  verify a bucket lifecycle backstop before unattended operation.
- Strengthen provider reconciliation with bounded pagination/time filtering and
  identity evidence. Current one-page text matching always needs human resolution.
- Consider a whole-attempt delivery deadline covering R2 and final publication,
  not only Meta container staging/polling.
- Token renewal, expiry warnings and off-device backup scheduling need explicit
  operations work; they are not installed by the pollers.

YouTube collection remains disabled/on hold unless explicitly enabled.

## Optional expansion

X threads require a persisted step per public post, exact reviewed text/reply
links, a final-send marker per step, published-prefix audit, cadence accounting
and explicit uncertain/partial recovery. They cannot be enabled by looping the
single-post adapter. No automatic resend, deletion or restart of a published prefix.

Additional sources, regional coverage and visual families require measured value
and focused contracts before implementation. Human scheduling, unattended
editorial approval and video are outside the current scope.
