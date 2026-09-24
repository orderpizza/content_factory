# Live Gemini Text Acceptance Report

## Executive summary

This report supersedes the Pass 2B report. Pass 2C improved evidence identity,
AI/Tech source-bound prompting, and semantic acceptance checks, but the Gemini
text workflow is **not ready for Pass 3 image acceptance**.

The required incomplete-idea reproduction initially passed 5/5, but its final
10-attempt run passed 9/10; the remaining attempt ended at the one-attempt,
60-second Vertex deadline. The AI/Tech frozen full chain has not achieved a
valid repeat: its previous title-only fixture correctly became
`not_recommended`, the repaired bounded-evidence chain exposed a semantic
evaluator false positive, and subsequent confirmations encountered Generation
output truncation and a provider 429. No image rendering was invoked.

## Environment and campaign boundaries

- Text model: `gemini-3-flash-preview`.
- Every live attempt used an isolated current-schema SQLite database under
  `data/acceptance/`; no production database or worker was used.
- All live commands used `CONTENT_FACTORY_ENABLE_LIVE_GEMINI_TESTS=1`,
  `--live-gemini`, finite USD/call/case limits, and an image-call budget of
  zero. Recorded actual image calls: **0**.
- Offline verification after the final code change: **278 passed, 199 subtests
  passed**; documentation check passed (18 current documents, 65 schema tables).
- Full and regression dry-runs were repeated after relevant changes. The latest
  full dry-run planned 29 cases and a maximum $0.638; the latest regression
  dry-run planned five cases and a maximum $0.234. They make no provider calls.

## Pass 2C live evidence

| Run workspace | Scope | Result | Calls / estimated cost |
| --- | --- | --- | --- |
| `20260924T064615-66ecb7e1` | `incomplete_idea`, reproduction ×5 | 5 PASS | 5 / $0.003892 |
| `20260924T064638-d54f2d92` | `incomplete_idea`, final ×10 | 9 PASS, 1 ERROR | 10 / $0.023008 |
| `20260924T064917-41038f63` | earlier title-only AI fixture, ×10 | 10 ERROR: 9 correctly `not_recommended`; 1 determination error | 10 / $0.013920 |
| `20260924T065415-394aa396` | bounded-evidence AI full chain | all handoffs completed; semantic evaluator false-positive FAIL | 4 / $0.035283 |
| `20260924T065705-49ac14b2` | corrected-evaluator AI confirmation | Generation `MAX_TOKENS` / incomplete JSON | 3 / $0.019585 |
| `20260924T065758-5b664090` | 6,000-token Generation-headroom probe | Editorial Planning Vertex 429 | 2 / $0.001661 |

Pass 2C live estimated spend was $0.097349. Earlier Pass 2B evidence remains
in its existing workspaces and recorded $0.135368 for its repeated regression;
the aggregate is advisory only because uncertain invocations preserve their
configured reservation.

## Findings and changes

- **Evidence identity mismatch fixed.** External `reference_id` values now pass
  through unchanged (for example `fixture:acme:1`) while internal IDs retain
  their namespaced form. Editorial Planning and Generation explicitly require
  exact allowed IDs. This removed the prior three-of-three unknown-reference
  planning failures.
- **Title-only evidence is now handled safely.** The AI planner and generator
  treat a title, ID, brief target, and proposed plan details as non-evidence.
  The title-only fixture therefore returned `not_recommended` instead of
  inventing product capabilities. The chain fixture was then replaced with
  three explicit source facts (October 2026 Enterprise-plan availability,
  centralized administrative controls, and Acme Data Workspace integration)
  plus named unknowns.
- **Semantic acceptance is stricter and more accurate.** The fixture checks
  that required facts appear and unsupported details do not appear as asserted
  facts. It permits the required form of limitation: an unsupported category
  may be present when explicitly described as unstated or unknown. The first
  bounded-evidence chain completed all text handoffs and demonstrated this
  correction; its initial failure was solely the now-fixed lexical false
  positive.
- **Incomplete Intake remains intermittent.** Attempt 6 of the final run
  recorded `504 DEADLINE_EXCEEDED` from `2026-09-24T06:47:38` to
  `2026-09-24T06:48:36`, with no provider usage. It is safely retained as a
  transport failure; the worker did not retry it.
- **AI full-chain reliability remains blocked.** After the evaluator fix,
  Generation exhausted the default 4,000 output-token allowance before a
  complete JSON response (2,900 input / 3,985 output tokens). A one-off,
  documented 6,000-token acceptance-only override did not test Generation:
  Editorial Planning received Vertex `429 RESOURCE_EXHAUSTED`. Default runtime
  configuration was not changed.

## Readiness decision

Do **not** start image/storyboard acceptance. Pass 3 requires, at minimum:

1. A successful bounded-evidence AI full-chain confirmation, followed by the
   required repeat-three and repeat-ten stability runs under an explicitly
   selected Generation token policy.
2. A fresh incomplete-idea final sample that meets the agreed reliability
   threshold without a 504, or an explicit operator decision that provider
   availability is outside that threshold.
3. Only after those gates pass, the remaining intended live text matrix and
   human semantic review of the inspectable artifacts.

The report deliberately does not claim full-matrix completion, model-quality
readiness, or image readiness. It records the actual blockers rather than
substituting dry-run or partial-chain coverage.
