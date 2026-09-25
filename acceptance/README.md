# Live acceptance runner

This directory holds opt-in live acceptance tooling, versioned reusable scenarios and
stage/chain/full-journey evaluators. It is separate from production worker
composition. Normal tests use fake providers and remain offline. The permanent
architecture, regression philosophy and historical status are owned by
[`docs/acceptance/`](../docs/acceptance/README.md); this document owns runner
operation, profiles, authorization, budgets and artifacts.

Reusable definitions are in `scenarios/`. Historical campaign
evidence is deliberately outside this directory under
[`docs/acceptance/history/`](../docs/acceptance/history/README.md).

Offline tests answer whether deterministic contracts are enforced. Live tests
answer whether the real Gemini-backed stage produces an inspectable result for
a realistic input. A case is a golden input and a set of stable constraints;
Gemini output is not a golden snapshot. Generated hooks, captions, and other
stochastic text must not be checked by exact equality. The harness evaluates
deterministic contracts, conservative conservation checks, and human-review
findings; it does not claim semantic quality. There is no Gemini judge.

The harness is designed for three scopes:

1. **Stage:** frozen upstream input, one live stage, stage-specific evaluation.
2. **Chain:** several live stages using each prior result as frozen input.
3. **Full journey:** Human or Detection through review-ready assets.

The runner invokes production Intake, Determination, Editorial Planning,
Canonical Generation and Adaptation workers; chains also run the deterministic
VisualPlanner between generation and adaptation. Full journeys can continue
through StoryboardPlan, production PromptCompiler, Vertex image rendering,
deterministic split/overlay processing and the final ReviewRequest. It retains
original raw boards and writes an independent `gallery.html` for human review;
it does not add a model-based visual judge.

For independent post-Determination diagnosis, a v2 case may use the
`stage_fixture` source kind. It selects one named, frozen local fixture and
starts at Editorial Planning, Canonical Generation, or Adaptation. Fixture
setup uses the production persistence handoffs with local fixed responses and
never constructs a provider client or consumes the run's live-call budget.
Only the declared target stage is a live Gemini invocation. This avoids
mistaking full-chain coverage for a direct stage test while retaining an
inspectable, current-schema upstream lineage.

## Safety and budgets

A provider call requires both `CONTENT_FACTORY_ENABLE_LIVE_GEMINI_TESTS=1` in
the process environment and `--live-gemini`. Credentials, project/model IDs,
and production pricing do not enable the harness. `--dry-run` never checks or
creates a provider client and does not require opt-in.

Live execution also requires a finite positive ceiling supplied by either
`LIVE_TEST_MAX_USD` or `--max-usd`. When both an environment value and CLI
override are present, the smaller applies. `LIVE_TEST_MAX_CALLS`,
`LIVE_TEST_MAX_IMAGE_CALLS`, and `LIVE_TEST_MAX_CASES` can constrain the run;
the corresponding CLI values can only make those limits stricter. A case is
admitted only if its whole declared call/image/cost envelope fits before it
starts. Cost envelopes use configured current Gemini prices, input-token reservation
assumptions and provider output caps. Input reservations are not enforced token
maxima; reported actual cost can exceed the estimate. The production `ModelBudgetPolicy` and SQLite invocation/reservation
ledger still gate and account for each actual call. Acceptance totals retain an
uncertain invocation’s full reserved amount when usage is absent; they must not
report that call as zero cost.

Configure local Vertex ADC, `GOOGLE_CLOUD_PROJECT`, `GOOGLE_CLOUD_LOCATION`,
text/image model IDs, and the same current `GEMINI_*_COST_PER_MILLION_USD`,
daily hard/warning, and job hard limit settings used by production. Prices are
operator supplied; this repository does not embed current rates. Disable live
acceptance by omitting either opt-in. The harness never prints credentials or
environment contents. Output cost is an estimate or conservative production
reservation, not an invoice.

## Run it

Plan selected cases without a provider call:

```sh
.venv/bin/python -m acceptance.runners.matrix --profile smoke --dry-run --max-usd 0.20
```

Run the live smoke case:

```sh
CONTENT_FACTORY_ENABLE_LIVE_GEMINI_TESTS=1 \
.venv/bin/python -m acceptance.runners.matrix --live-gemini --profile smoke --max-usd 0.20
```

Repeat attempts independently while retaining their parent case ID:

```sh
CONTENT_FACTORY_ENABLE_LIVE_GEMINI_TESTS=1 \
.venv/bin/python -m acceptance.runners.matrix --live-gemini --profile smoke --repeat 3 --max-usd 0.50
```

Plan the visual profile without a provider call:

```sh
.venv/bin/python -m acceptance.runners.matrix --profile visual --dry-run --max-usd 5.00
```

Run it only after configuring the image model/pricing and deliberately choosing
an image-call ceiling. The profile reserves its maximum dynamic-board envelope
before starting each case; a completed case can consume fewer boards.

```sh
CONTENT_FACTORY_ENABLE_LIVE_GEMINI_TESTS=1 \
LIVE_TEST_MAX_IMAGE_CALLS=40 \
.venv/bin/python -m acceptance.runners.matrix --live-gemini --profile visual --max-usd 5.00
```

`visual` covers automatic text-aware board planning, English adaptive splitting
and complete ReviewRequest journeys. Its current sparse fixed fixtures select
6, 1+4 and 4+4+6; partitions are text-dependent. The `fidelity` profile below
also exercises 2×1 boards and singleton sequencing. `journey` selects complete Human/Frozen-Detection integrations, including sparse
English expression and natural explicit-six-slide cases.

## Controlled text-fidelity experiment

`render_fidelity.json` defines the same frozen six-slide English sample under
four forced strategies: `6`, `4+2`, `2+2+2`, `1+1+1+1+1+1`. Copy is frozen in
`fixtures/english_fidelity_6_v1.json` (the retained Pass 2 English slide text,
with fixture-local claim IDs); fixture setup and archetype selection are identical
for every variant. No text-stage call is made. The ordinary automatic policy
splits this 160-word sample; forcing the dense six-panel variant is deliberate
calibration evidence, not production admission. Plans record forced mode,
policy versions, limits, metrics and violations. Adaptation and model budget
gates still apply. Normal workflow entrypoints cannot select a forced strategy.

Recommended first comparison: one attempt of all four variants, exactly 12 image
calls, same configured model, 2K size and prices. First inspect a free dry-run:

```sh
.venv/bin/python -m acceptance.runners.matrix --profile fidelity --dry-run --max-usd 5.00
```

Only after explicit live authorization and choosing a USD ceiling sufficient for
the displayed reservations, use this opt-in command (the 5 USD ceiling is an
operator example, not a price claim):

```sh
CONTENT_FACTORY_ENABLE_LIVE_GEMINI_TESTS=1 \
.venv/bin/python -m acceptance.runners.matrix --profile fidelity --live-gemini \
  --repeat 1 --max-image-calls 12 --max-calls 12 --max-usd 5.00
```

Inspect all final slides and raw boards side by side. `fidelity-review.json`
contains the identical package hash, expected titles/bodies and blank human
assessment fields for exact text, altered/missing words, invented text, visual
quality, cropping/resolution and cross-board consistency. Fill these after review;
null means unassessed, never pass. `board-validation.json` provides raw dimensions,
source resolution per panel, text-load evidence and provider latency. Manifests
link cells to invocations; per-attempt SQLite preserves token/cost ledgers and
`costs.json` summarizes call counts/cost. Compare the package hashes before
interpreting results. No OCR or LLM judge is claimed, no reference-image chaining
is used, and posting remains disabled. Repeat the identical comparison later to
assess variability before recalibrating the centralized policy and its version.

Profiles use scenario metadata: `smoke` is the cheapest sanity path, `stage`
selects isolated stages, `regression` selects representative text chains,
`visual` selects review-render regression, `fidelity` selects the controlled copy
comparison, `journey` selects full integrations,
and `full` is the broad/expensive matrix. The committed scenarios include clear,
incomplete, and ambiguous Intake inputs; Determination; Editorial Planning;
English and frozen Detection chains; bounded AI evidence; and source-scope
preservation. Operators choose profiles and explicit ceilings deliberately.

Every run writes under `data/acceptance/<run-id>/` by default. It includes
`run.json`, `plan.json`, `summary.md`, `costs.json`, `stability.json`, and one
`input.json` plus `evaluation.json` per case attempt. Live attempts use a new
current-schema SQLite database per attempt. Chain attempts retain every
completed handoff (`intake.json`, `determination.json`, `editorial_plan.json`,
`canonical.json`, `visual_recipe.json`, and `adaptation.json`) before a later
failure. The database preserves production model invocations/reservations; it
is never the normal development database. Credentials, tokens, and full auth
configuration are never copied into artifacts.

For a completed image case, the attempt directory also contains the immutable
`storyboard_plan.json`, one compiled `prompt-board-*.txt` per board,
`render-manifest.json`, and `board-validation.json`. The production renderer
keeps raw PNG/JPEG provider bytes and final PNG review slides in its atomic
`render-*/` directory. The run-root `gallery.html` links raw boards and shows
the ordered final slides. These artifacts make geometry, overlay, source-rectangle
and visual-quality review inspectable without re-calling a provider.

The result JSON is authoritative. Summary Markdown is a concise index. PASS,
WARN, FAIL, ERROR, and SKIP are result statuses; `SKIP_BUDGET` is a distinct
skip reason used when the complete case envelope cannot fit. Repetition keeps
each attempt separate; later stability analysis must not average individual
failures away.

## Scenarios and evaluators

Cases use closed JSON schemas. Version 1 remains readable for legacy fixtures.
Version 2 explicitly adds `start_stage`, `end_stage`, stage expectations and
conservation expectations; it does not overload the v1 `stage` field. A JSON
file may contain one case or a `{ "cases": [...] }` matrix. Unknown versions,
fields, malformed expectations, duplicate IDs, and invalid budgets fail before
a provider call.

Hard contract findings can fail: closed schemas, route disposition, editorial
candidate/lane bounds, visual recipe lineage and slide bounds. Declared exact
identifiers and normalized phrases can fail when visibly absent. Scope,
qualification, epistemic strength, evidence-reference and claim-lineage checks
are WARN/human-review where lexical matching cannot establish semantic
equivalence. `stability.json` reports per-case schema success,
route/outcome/lane/slide-count stability and conservation success without
hiding individual failures.

Normal pytest does not discover or import the CLI as a test, and the live
provider factory is reachable only after the central opt-in gate in the live
runner. Fake-Gemini production workflow tests remain a separate offline suite.
