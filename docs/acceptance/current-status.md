# Current acceptance status

The live acceptance/regression framework is permanent, opt-in project
infrastructure. Normal CI stays offline; live campaigns require explicit
authorization and a finite budget as documented by the runner.

## Validated review baseline

- Text-stage live acceptance definitions and isolated evidence handling exist.
- The Gemini visual-rendering contract is validated for all supported board
  shapes, including deterministic splitting and normalization.
- The review flow reaches a persisted `ReviewRequest` with exact final slides.

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
