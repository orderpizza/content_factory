# English pilot execution and review

English content-quality/design refinement and paid Gemini calibration are deferred
to the final [roadmap](../docs/roadmap.md) phase. The procedure below is retained
for that later, separately authorized experiment; its historical Phase 2B label
does not make it the next task. Publishing infrastructure uses offline synthetic
fixtures first. No pilot quality or outcome measurement is established here.


Phase 2A prepares evidence collection only. Audience and learning requirements
are owned by [product](../docs/product.md#english-learning-pilot-brief); scoring
and provisional targets by [testing](../docs/testing.md#english-pilot-human-review).
[Runner operation](README.md) owns authorization, schemas, profiles and artifacts.
No Instagram account is required. No paid run or publishing is authorized here.

## Frozen sample plan

Select `--cases acceptance/scenarios/english_pilot`; discovery is nonrecursive.
All six files use the existing v2 validator and production adapters. `journey`
selects five positives, `stage` selects the control, and `full` selects all six.
Two repetitions produce 10 carousel attempts and two controls, **not 12 approved
posts**. Repetitions measure variability, not independent topics or market fit.

| Case file | Level / family | Target and human inspection focus | Slides | Image recovery envelope |
| --- | --- | --- | --- | --- |
| [a1_vocabulary.json](scenarios/english_pilot/a1_vocabulary.json) | A1 / vocabulary | umbrella: picture identifies the object, learner can borrow one; no forced idiom lesson | 4 | 54 |
| [a1_daily_phrase.json](scenarios/english_pilot/a1_daily_phrase.json) | A1 / expression | Excuse me: getting attention, not a universal apology | 4 | 54 |
| [a2_dialogue.json](scenarios/english_pilot/a2_dialogue.json) | A2 / daily conversation | Could you say that again?: plausible repetition and clarification | 5 | 54 |
| [a2_common_mistake.json](scenarios/english_pilot/a2_common_mistake.json) | A2 / common mistakes | I agree: error visibly labeled; no learner shaming | 5 | 54 |
| [b1_pragmatic_nuance.json](scenarios/english_pilot/b1_pragmatic_nuance.json) | B1 / nuance | I'll think about it: multiple readings, context/tone and neutral follow-up | 6 | 54 |
| [ambiguous_input.json](scenarios/english_pilot/ambiguous_input.json) | Unspecified / control | Ask a useful clarification; do not invent target, learner or goal | N/A | 0 |

Positive cases require English-only routing, exact requested slide count, retained
critical target and canonical English knowledge/example claim classes. They do not
freeze stochastic prose or force an archetype. The control requires
`needs_clarification` and ends at Intake. Inspect its question and absence of a
brief/downstream content manually as well. The old sparse-expression and fixed
fidelity scenarios remain intact. Full journeys have fresh per-attempt databases,
so this sample does not test history-based variety across a real account.

### Why recovery budgets exceed slide counts

The acceptance runner now checks every runtime-controlled provider attempt through
a shared acceptance-only guard at the persisted pre-dispatch trace boundary. Case
phase allowances, run combined/image caps and the planned run text cap apply across
retries and recovery; `--repeat` does not reset the run counters when it opens a new
isolated database. See [exact safety semantics](README.md#safety-and-budgets).
The production renderer can reinforce an invalid composite, then split into
singletons; each singleton can be reinforced. Each logical request has at most three
provider attempts. All these attempts consume the same acceptance allowance.
A nominal board allowance may stop recovery before completion.
For N slides, B composite boards and S initially singleton slides, the maximum
logical requests are `2B + 2(N-S) + 2S = 2B + 2N`. Since `B <= N/2`, a conservative
lifetime bound is `3 * (2B + 2N) <= 9N` image calls. The new positive cases each
reserve **54** image calls (9 × the supported
maximum of six slides), including recovery, without changing renderer behavior.
The requested count is evaluated after execution; an upstream model could lose
the count constraint. Reserving only 9 × the requested four/five slides would
underbudget that failure path. Human/automatic review still rejects a wrong count.
Text stages have hard one-attempt allowances (five per positive, one per control);
provider retries or adaptation metadata repair cannot exceed those allowances.
The guide forbids manual worker resumes or automatic fresh-case reruns. A smaller initial
plan normally uses far fewer calls. This is a defensive envelope, not expected
spend, a recommendation to exhaust it, or a quality result. Revisit the bound if
recovery topology changes; offline recovery tests remain authoritative.

The full two-repeat plan therefore reserves at most 52 text + 540 image = **592
provider calls**, across 12 attempts and 48 intended final positive slides. This
large reservation can cause `SKIP_BUDGET` even when nominal boards would be cheap.
Keep the USD ceiling; reduce the sample or seek a new explicit budget rather than
quietly enlarging it. The count caps are enforced before dispatch; the USD amounts
remain reservation-based admission estimates, not guaranteed invoice ceilings.

## Offline procedure — safe now

From repository root, use the existing `.venv`. Run real validation, dry-run and
regression checks without credentials or provider construction:

```sh
.venv/bin/python scripts/check_docs.py
.venv/bin/python -m pytest -q tests/test_english_pilot_offline.py tests/test_acceptance_harness_offline.py
.venv/bin/python scripts/run_tests.py
```

For reproducible **synthetic pricing only**, this command overrides price/limit
settings needed by the planner. Values below are test inputs, not current Gemini
prices or an authorization. `--dry-run` wins even if local opt-in is configured.

```sh
GEMINI_INPUT_COST_PER_MILLION_USD=1.25 \
GEMINI_OUTPUT_COST_PER_MILLION_USD=5 \
GEMINI_IMAGE_INPUT_COST_PER_MILLION_USD=2 \
GEMINI_IMAGE_OUTPUT_COST_PER_MILLION_USD=8 \
GEMINI_DAILY_WARNING_USD=5 GEMINI_DAILY_HARD_LIMIT_USD=20 \
GEMINI_JOB_HARD_LIMIT_USD=5 \
LIVE_TEST_MAX_USD=20 LIVE_TEST_MAX_CALLS=592 \
LIVE_TEST_MAX_IMAGE_CALLS=540 LIVE_TEST_MAX_CASES=12 \
.venv/bin/python -m acceptance.runners.matrix \
  --cases acceptance/scenarios/english_pilot --profile full --repeat 2 \
  --dry-run --max-cases 12 --max-calls 592 --max-image-calls 540 --max-usd 20
```

`plan.json` should list 12 attempts with the bounds above. `run.json` must report
`mode: dry_run`, zero actual calls/images and zero spend. A planned attempt is
`SKIP` with code `dry_run`, not PASS; `SKIP_BUDGET` means the full reservation did
not fit. With these synthetic prices and current output caps, the total planned
reservation is USD 45.14: six attempts fit and six are `SKIP_BUDGET` under USD
20. This is expected admission behavior, not spend or a model-quality result.
The offline test also exercises all 12 admissions with a synthetic USD-50 test
ceiling; it does not change the proposed live campaign ceiling. No output images
or quality scores are produced. Tests validate every
case, expand repeats through the real runner and prohibit provider entrypoints.

## Separately authorized Phase 2B experiment

Proposed campaign ceiling: **12 attempts, 592 total calls, 540 image calls, USD
20**, including failures and any approved revisions. These are adjustable
proposals, not granted authority. Revisions consume remaining campaign capacity;
never add them for free outside the denominator. Before any live work:

1. Obtain owner authorization for the exact cases, model IDs, region, rates, sample
   size and cumulative caps. Record that decision in the campaign report. Confirm
   current operator-supplied prices and production daily/job limits; do not carry
   synthetic prices from the offline example into live execution. Confirm that
   reservations fit; otherwise propose a smaller first batch. Do not increase caps
   automatically to avoid skips.
2. Freeze Git revision, case hashes, rubric revision, model/SDK/endpoint, pricing
   fingerprint, compiler and policy versions. Store a copy of the six case JSON
   files and non-secret settings in ignored `data/acceptance/<campaign>/`. Do not
   copy `.env`, credentials, access tokens or entire process environments.
3. Run the same dry-run using real pricing and the approved remaining limits.
   Inspect `plan.json`, then run **one case attempt at a time** and review before
   admitting the next. Start with the clarification control and one A1 positive;
   stop early on the conditions below. Do not start with unattended `--repeat 2`.
4. Continue to the frozen two-attempt-per-case plan only while quality, evidence
   and cumulative budget permit. Keep all original attempts, even failed ones.
   Do not poll/resume acceptance databases with normal production workers.

To select one case without changing framework profiles, copy just that file into
a new ignored batch directory (choose a new name for every batch):

```sh
mkdir -p data/acceptance/english-pilot-campaign/batch-01
cp acceptance/scenarios/english_pilot/ambiguous_input.json \
  data/acceptance/english-pilot-campaign/batch-01/
.venv/bin/python -m acceptance.runners.matrix \
  --cases data/acceptance/english-pilot-campaign/batch-01 --profile full \
  --repeat 1 --dry-run --max-cases 1 --max-calls 1 --max-usd 0.50
```

Only after authorization, run this control with both live opt-ins:

```sh
CONTENT_FACTORY_ENABLE_LIVE_GEMINI_TESTS=1 \
.venv/bin/python -m acceptance.runners.matrix \
  --cases data/acceptance/english-pilot-campaign/batch-01 --profile full \
  --repeat 1 --live-gemini --max-cases 1 --max-calls 1 --max-usd 0.50
```

For each positive, copy its one file to a fresh batch directory and use its
`5 + image envelope` call cap and image envelope from the table (all positives: 59 calls,
54 image calls). Choose a per-batch USD cap from the **remaining** approved USD
20, no higher than USD 5 as an initial per-positive proposal; inspect real-price
admission first. Controls propose USD 0.50 each. Ten USD-5 batches are **not**
authorized by a USD-20 campaign. The runner has no cross-run campaign ledger:
the operator must subtract actual settled spend plus active/uncertain holds and
used calls/images/cases before each batch. Environment limits can only tighten
CLI limits. This manual checkpoint is required even though each run has a fresh
isolated database.

For example, after the control passes and at least USD 5 remains authorized,
prepare A1 vocabulary and inspect its admission (replace `--dry-run` with
`--live-gemini` and set the opt-in environment variable only after that review):

```sh
mkdir -p data/acceptance/english-pilot-campaign/batch-02
cp acceptance/scenarios/english_pilot/a1_vocabulary.json \
  data/acceptance/english-pilot-campaign/batch-02/
.venv/bin/python -m acceptance.runners.matrix \
  --cases data/acceptance/english-pilot-campaign/batch-02 --profile full \
  --repeat 1 --dry-run --max-cases 1 --max-calls 59 --max-image-calls 54 --max-usd 5
```

The USD gate uses input-token reservations, not guaranteed maximum billable input.
Actual usage can exceed the reservation; there is no provider-compatible local
tokenizer. Keep headroom below the owner ceiling and stop if observed usage exceeds
estimates. Neither the proposed USD amount nor the CLI is a guaranteed invoice
ceiling. Unresolved accounting blocks a subsequent batch; never assume a failed
call was free. See [accounting](../docs/specs/reliability.md#gemini-accounting).

Stop before the next batch for any critical teaching/target-text error, missing
or corrupt evidence, unexpected route/count, unsafe clarification behavior,
provider/contract error, uncertain billing, budget refusal/overrun, or failure to
complete all slides. Also stop if two positive samples need edit/reject for the
same major defect. Preserve partial artifacts and review the failure; do not
blindly rerun paid stages or repair prompts mid-baseline. The current runner does
not automatically stop a multi-case matrix after a quality failure, hence the
one-attempt batching. A changed model, prompt or correction becomes a new,
explicitly recorded comparison condition.

## Evidence collection and economics

Each CLI invocation prints its actual run path under ignored `data/acceptance/`.
Use it, not “latest” guessing. `run.json`, `plan.json`, `costs.json`, `stability.json`
and `summary.md` index the run. Attempts are
`cases/<case-id>/attempt-01/` for single batches; campaign report run IDs distinguish
repetitions. Copy [the blank review report](templates/english-pilot-review.md) into
each attempt and a campaign roll-up at campaign root.

Inspect `canonical.json`, `adaptation.json`, `visual_recipe.json`,
`storyboard_plan.json`, `render-manifest.json`, `board-validation.json`, compiled
prompts, raw boards and final slides via `gallery.html`. Some artifacts exist only
for completed stages. Record absent artifacts as missing, not passed. Failed
render attempts can retain raw checkpoints without a final gallery; inspect their
SQLite/retained paths. The immutable exact package/assets reviewed must be linked
in the report, including subsequent revisions.

`accounting.json` is automatically exported for **each** live attempt, including
adapter exceptions before return. It projects existing `model_invocations` and
`gemini_budget_reservations` without changing production schema. `costs.json` and
`run.json` roll up the same evidence. Inspect per-invocation input/output tokens,
phase/model, priced `actual_micro_usd`, historical `reservation_micro_usd`,
`active_reservation_micro_usd`, `uncertain_micro_usd` and
`actual_minus_reservation_micro_usd`. USD = micro-USD / 1,000,000.

Keep priced settlement separate from active/uncertain holds. Historical reservations
are not additional charges. Blocked invocations are not calls; explicit rejections
released by production can settle to zero while consuming an attempt. Missing usage
and lost responses retain uncertain holds; missing/partial database evidence yields
null totals and `accounting_incomplete`, not zero. The pre-dispatch admitted count
may conservatively include local transport setup failure or a crash before send;
it is not a provider billing receipt. SDK retries are configured to one attempt for
both transports; the caps cannot govern external behavior outside this client.

Errors retain safe type diagnostics and partial handoffs/checkpoints. Inspect
`evaluation.json`, `accounting.json` and the attempt SQLite database even if the
adapter did not return. Unresolved accounting makes the result ERROR and stops
subsequent cases in the same matrix with `SKIP_BUDGET`. There is no automatic
resolution command. A new CLI invocation does not resolve uncertainty: the operator
must reconcile it and explicitly authorize remaining campaign capacity first.
The runner can allow further attempts inside the current case under the unchanged
production recovery policy, but each consumes count and reservation capacity.

Response usage above its reserve is settled in full; later admissions use that
larger amount. Even the pre-attempt USD checks cannot guarantee the bill for an
already sent request. Keep headroom and inspect over-reservation deltas. An
unexplained mismatch stops expansion, and uncertain holds are not proof of a charge
or of no charge.
Provider billing reconciliation may still be needed; these are priced usage and
holds, not invoices. Follow the rubric's denominators for cost/tokens/images per
approved lesson, operator time, controls, skips and revisions. Publication metrics
are N/A until a separately authorized Phase 3B/4 publication and measurement experiment.

## Technical findings and next experiments

These are code-inspection findings, not claims about live Gemini quality.

| Existing machinery | Reuse and limits relevant to this pilot |
| --- | --- |
| `gemini_generation.py`, `content_contract.py`, `gemini_adaptation.py` | Claim registry, exact target provenance, English-only model knowledge and generated-example classes, public claim coverage, bounded 4–6 slide sequences and pre-render semantic QA already exist. Lexical checks cannot establish CEFR suitability, truth or natural dialogue. Requirements in inputs may be lost; compare frozen brief through final copy. |
| `expression_breakdown_v1` | General expression explanation with illustrations, examples and dialogue. Retain accepted baseline prompt, overlay and fingerprint; vocabulary may feel padded by expression-first grammar. |
| `expression_story_scene_v1` | Everyday interactions with clear speakers; stricter copy capacity. Useful for dialogue, but scene clarity and cross-board character continuity need human evidence. |
| `expression_cards_v1` | Typography-led usage distinctions and compact grouping. Useful for nuance/errors; text accuracy and contrast remain provider-dependent. |
| `archetype_selection.py`, `visual_planner.py` | Deterministic fit/history selection, not a teaching-quality judge. Record selected archetypes; do not claim three-archetype live coverage if only one is selected. Fresh case databases omit account-history diversity. |
| `storyboard_planner.py`, `render_text_policy.py` | Frozen content is packed contiguously into 6/4/2/1 panels. Minimize board count, then density under provisional budgets; never drop copy. Dense boards can reduce source pixels per slide or harm typography; final 1080×1350 normalization cannot restore detail. |
| `gemini_prompt_compiler.py`, `gemini_image_renderer.py` | Deterministic prompts, local split/normalization/overlays, structural validation, raw checkpoints and recovery protect mechanics. Gemini still draws teaching text; spelling, invented text, meaning and board seams need visual review. Recovery affects actual call count and cost. |
| Acceptance artifacts and `model_trace.py` | Already expose usage, costs/holds, model/version traces, latency, text-load metrics, partitions, panel resolution, structural outcomes, hashes and final ReviewRequests. Complete invocation ledger is needed for recovery totals. |
| Human report template | Supplies missing learner-level/family labels, subjective scores, error/typo counts via findings, review/edit time, reviewer agreement and final human decisions. No new DB schema. Automated OCR, learner comprehension and published outcomes remain absent. |

Recommended order for ChatGPT's architectural review:

1. **Measured live acceptance first**, after owner authorization: run the control
   and one A1 lesson, then up to this bounded plan. Diagnose whether losses begin
   in the brief, canonical teaching, adaptation or rendered words. Human review
   by level/family precedes expansion; no renderer rewrite is justified yet.
2. **Conditional controlled board experiment** if text fidelity/readability is the
   dominant failure: reuse `render_fidelity.json` and the unchanged
   `english_fidelity_6_v1.json`, identical package/model/prices, comparing 6,
   4+2, 2+2+2 and singletons. The guide's 12-image comparison now enforces 12
   runtime-controlled attempts, including recovery. Variants may stop at their
   case limits; any larger recovery envelope needs separate authorization. Compare exact-text error locations,
   readable slides, board seams, latency and all-in cost; retain failed variants.
3. **Learner comprehension/localization probe** only on human-passed assets: recruit
   consenting A1/A2/B1 learners across first languages, ask the stated practical
   task before/after viewing, and compare English-first versus a separately
   prepared localized explanation. This requires separate coordination and is
   not evidence already collected. Consider a small manual posting pilot only
   after quality/cost review and exact-asset publication authorization.

If conservative envelopes or unresolved accounting block (1), inspect the evidence
and reduce the proposed batch or seek an explicitly revised budget before a live run. Do not start posting integration or account-model redesign to solve
an unmeasured teaching or rendering problem.
