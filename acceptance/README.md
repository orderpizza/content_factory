# Gemini acceptance framework

This directory holds opt-in live acceptance tooling, versioned input cases,
future stage evaluators, and run reports. It is separate from production worker
composition. Normal tests use fake providers and remain offline.

Offline tests answer whether deterministic contracts are enforced. Live tests
answer whether the real Gemini-backed stage produces an inspectable result for
a realistic input. A case is a golden input and a set of stable constraints;
Gemini output is not a golden snapshot. Generated hooks, captions, and other
stochastic text must not be checked by exact equality. Pass 1 evaluates only
basic deterministic execution/artifact invariants and does not claim semantic
quality. There is no Gemini judge.

The harness is designed for three scopes:

1. **Stage:** frozen upstream input, one live stage, stage-specific evaluation.
2. **Chain:** several live stages using each prior result as frozen input.
3. **Full journey:** Human or Detection through review-ready assets.

Pass 1 establishes the versioned case and result models, central double opt-in,
budget admission, isolated workspaces, repeat/profile support, and artifacts.
Pass 2 will add the broad text and semantic stage matrix. Pass 3 will add image,
visual, and full-journey acceptance. The current live adapter executes human
Intake. Other source/stage combinations are representable and dry-runnable, but
are reported as unsupported in live mode until their later stage adapters land.

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
starts. Cost envelopes use configured current Gemini prices and phase token
ceilings. The production `ModelBudgetPolicy` and SQLite invocation/reservation
ledger still gate and account for each actual call.

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

Run the live smoke Intake case:

```sh
CONTENT_FACTORY_ENABLE_LIVE_GEMINI_TESTS=1 \
.venv/bin/python -m acceptance.runners.matrix --live-gemini --profile smoke --max-usd 0.20
```

Repeat attempts independently while retaining their parent case ID:

```sh
CONTENT_FACTORY_ENABLE_LIVE_GEMINI_TESTS=1 \
.venv/bin/python -m acceptance.runners.matrix --live-gemini --profile smoke --repeat 3 --max-usd 0.50
```

Profiles use case metadata: `smoke` is the cheapest sanity path, `stage` selects
individual stage examples, `regression` is a curated representative set, and
`full` is reserved for a broad/expensive matrix. Pass 1 intentionally includes
only three small framework-validation fixtures.

Every run writes under `data/acceptance/<run-id>/` by default. It includes
`run.json`, `plan.json`, `summary.md`, `costs.json`, and one `input.json` plus
`evaluation.json` per case attempt. Live Intake uses a new current-schema
SQLite database per attempt. The database preserves production model
invocations/reservations; it is never the normal development database. Case
outputs contain test content and generated output for inspection. Credentials,
tokens, and full auth configuration are never copied into artifacts.

The result JSON is authoritative. Summary Markdown is a concise index. PASS,
WARN, FAIL, ERROR, and SKIP are result statuses; `SKIP_BUDGET` is a distinct
skip reason used when the complete case envelope cannot fit. Repetition keeps
each attempt separate; later stability analysis must not average individual
failures away.

## Cases and evaluators

Cases use closed JSON schema version 1. Unknown versions, fields, malformed
expectations, duplicate IDs, and invalid budgets fail before a provider call.
Expectations are structured and versioned so future stage-specific checks can
be added deliberately. The intended checks include required/forbidden selected
routes, preserved canonical facts, and slide-count bounds; they do not require
an exact stochastic response string. Evaluators separate hard deterministic
invariants from future semantic, editorial, and visual review.

Normal pytest does not discover or import the CLI as a test, and the live
provider factory is reachable only after the central opt-in gate in the live
runner. Fake-Gemini production workflow tests remain a separate offline suite.
