# Live acceptance and regression architecture

**Owner:** Permanent acceptance architecture, regression philosophy and the
distinction between reusable definitions, runtime artifacts and conclusions.
Runner commands, authorization and campaign budgets belong in
[`acceptance/README.md`](../../acceptance/README.md).

## Purpose and scopes

Live acceptance is permanent project infrastructure for inspecting real
Gemini-backed behavior without making paid inference part of normal tests. It
does not replace deterministic tests or human editorial/visual review.

| Scope | Frozen boundary | Purpose |
| --- | --- | --- |
| Stage | Frozen upstream input → one live Gemini stage | Isolate a model-owned boundary and diagnose prompt, schema or model regressions without upstream noise. |
| Chain | Persisted handoffs across consecutive stages | Validate lineage, conservation and cross-stage behavior. |
| Full journey | Human idea or frozen Detection → final review artifact | Exercise the integrated review path. |

The current full journey can reach:

```text
Human / Detection
→ Intake / Determination
→ Editorial Planning
→ Canonical Generation
→ Visual Planning
→ Adaptation
→ Storyboard Planning
→ Gemini Image
→ local rendering
→ ReviewRequest
```

This describes the review architecture; it does not enable posting or change
production worker composition.

## Three repository concepts

| Concept | Location | What it contains | Git treatment |
| --- | --- | --- | --- |
| Offline deterministic tests | `tests/` | Fake/no-provider tests and deterministic contracts safe for normal CI | Tracked |
| Live acceptance definitions | [`acceptance/`](../../acceptance/README.md) | Reusable scenarios, fixtures, evaluators, runner/profile definitions and schemas | Tracked |
| Live execution artifacts | `data/acceptance/` | Per-run SQLite databases, JSON results, allowed prompts, raw images, final slides and galleries | Ignored |

Definitions are not results. A runtime artifact is evidence for one isolated
execution and is never production configuration. The current conclusions are
in [current status](current-status.md); historically accurate reports are in
[history](history/README.md).

## Golden scenarios and stable invariants

The permanent corpus uses **golden scenario + stable invariants**, never exact
golden LLM prose. A scenario records an input plus expected routing, preserved
concepts/evidence, contract invariants, semantic boundaries and output bounds.
Its generated hook, explanation or caption is intentionally not an exact-match
assertion.

For example, an English `break the ice` coworker scenario should retain English
routing, the expression and workplace context; produce six role-valid English
slides; create a ReviewRequest; and produce 1080×1350 final slides. It must not
require a particular hook sentence. A frozen AI/Tech announcement scenario
should retain the named plan, date and evidence reference, allow only supplied
capabilities as source-bound facts, and reject invented pricing, certification
or geography.

Existing scenarios use the `smoke`, `stage`, `regression`, `visual`, `journey`,
and `full` profiles. The curated corpus prioritizes clear and incomplete human
ideas, multi-domain eligibility, all three domains, frozen Detection, bounded
and hypothetical AI, short/long carousels and representative archetypes.
Retry/recovery joins this corpus after it exists in production; it is not
simulated as a completed feature.

### Metamorphic regression strategy

Metamorphic tests compare stable relationships rather than wording. Useful
future variants include:

- Input paraphrase: “Explain X” and “Teach people about X” should retain broadly
  stable routing and evidence boundaries, not identical prose.
- Evidence subtraction: removing pricing evidence means pricing can no longer
  appear as a fact.
- Context variation: workplace versus friends should retain an English
  expression while changing its examples/context.

## Deferred architecture decisions

The accepted review baseline is full-image Gemini rendering: Gemini supplies
composition, illustration and critical typography; local processing splits the
image and adds deterministic chrome. Gemini exact visual-text fidelity remains
known debt. A future experiment may reserve text-safe regions, use Gemini for
composition/illustration, and render critical text deterministically before the
existing overlays. It is not implemented: full-image Gemini rendering remains
the production review baseline until experimental validation accepts a hybrid
renderer.

Provider retry/resume is likewise deferred. The future design must be
persisted/resumable—not an inline API retry loop—and classify at least
`retryable_provider`, `uncertain_provider`, `nonretryable_request`,
`validation_failure` and `budget_deferred`. It should resume from the earliest
retryable incomplete persisted boundary, never restart a completed chain. For
example, a transient Generation failure after completed Intake, Determination
and Editorial Planning should retry Generation and continue downstream.
Transport uncertainty after a possibly accepted request remains more
conservative than a clear rate limit. Error normalization and latency
observability belong to that future reliability phase.

The historical Psychology hardening corpus is not an active regression profile
or a statement of future product policy. The future product policy permits plausible
interpretations, model-world-knowledge synthesis, possible explanations,
behavioral hypotheses and generated examples without frozen source evidence,
provided they are presented as interpretation/hypothesis rather than established
empirical fact. A future claim model may distinguish `source_bound_fact`,
`qualified_inference`, `interpretive_hypothesis` and `generated_example`.
Research findings, statistics, factual scientific claims and named-study
conclusions still need appropriate evidence handling. This does not weaken
AI/Tech’s source-bound behavior and is not a schema/prompt redesign in this
closeout.
