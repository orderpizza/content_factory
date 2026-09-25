# Current acceptance status

The live acceptance/regression framework is permanent, opt-in project
infrastructure. Normal CI stays offline; live campaigns require explicit
authorization and a finite budget as documented by the runner.

## Validated review baseline

- Text-stage live acceptance definitions and isolated evidence handling exist.
- The Gemini visual-rendering contract is validated for all supported board
  shapes, including deterministic splitting and normalization.
- The review flow reaches a persisted `ReviewRequest` with exact final slides.

## Current offline fidelity controls

Content pagination and render pagination are separate. The shared text-aware
planner persists deterministic slide/board measurements and provisional capacity
budgets for every domain, including English multi-board rendering. Offline tests
cover packing, assigned-copy prompts, immutable packages, ordering, raw provenance,
overlays, budget refusal and the accepted English six-panel compatibility path.
The new thresholds and multi-board visual continuity have not been live validated.

The permanent `fidelity` profile compares one identical English package under
6, 4+2, 2+2+2 and six singleton calls. [Runner operation](../../acceptance/README.md#controlled-text-fidelity-experiment)
owns the exact opt-in experiment and human rubric. Pass 2/3 evidence remains
historical; it does not prove this policy's typography benefit.

## Known debt and deferred work

- Gemini visual typography fidelity remains a human-review limitation.
- Provider retry/resume and reliability/latency observability need a dedicated
  persisted recovery phase.
- Psychology’s future editorial-policy recalibration is recorded in the
  [acceptance architecture](README.md#deferred-architecture-decisions); current
  conservative behavior is unchanged.
- Posting remains disabled. Hybrid rendering and unattended publication are
  deferred experiments/features, not present capabilities.

Historical reports preserve the conclusions and recommendations made at the
time. They are evidence, not statements of current product policy.
