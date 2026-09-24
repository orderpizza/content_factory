# Live Gemini Text Acceptance Report

## Executive summary

Pass 2B exercised Vertex Gemini text workers live, but the text pipeline is **not ready for Pass 3**. English full-chain execution was stable in three repeated regression attempts. AI/Tech scope behavior improved after a targeted generation-prompt fix, and the independently tested Psychology adaptation passed after copy-capacity hardening. However, the frozen AI/Tech chain failed in all three regression attempts and incomplete Intake was intermittent. The full/edge matrix was therefore not run; treating this as complete validation would hide material failures.

## Environment

- Revisions tested: `1fc4e90`, `a60b67c`, `643f485`, `8bd8740`, `bc07910`, `8dd1cff`, `50e3ccf`.
- Text model: `gemini-3-flash-preview`; isolated current-schema SQLite database per attempt.
- Profiles: smoke; stage (three executions, including independent Editorial, Generation and Adaptation fixtures); regression repeated three times.
- The final repeated regression ran 15 attempts / 30 provider calls with an estimated $0.135368 spend. Earlier smoke/stage investigations added bounded live evidence; every run recorded `image calls: 0`.
- No credentials, prompts, or provider responses were copied into this report.

## Coverage and stability

- Intake: live smoke, stage, and regression coverage. `incomplete_idea` was successful once and errored twice in the repeated regression run.
- Determination: current frozen Detection fixture was stable three of three; English full-chain routing was stable three of three.
- Editorial Planning: independent English stage passed; English chain lane was stable three of three.
- Canonical Generation: independent AI/Tech and Psychology stages completed with review warnings; English full chain was stable three of three.
- Adaptation: independent Psychology stage passed after hardening; English chain slide count was stable three of three.
- Human origin: English chain passed three of three. Frozen Detection origin: minimal Determination passed three of three, but the full AI chain failed three of three.
- Image calls: 0 in every run.

## Findings

- **Acceptance evaluator weakness (fixed):** legacy Intake artifact collection queried a removed column, converting a completed paid call into an error. The query and regression test were corrected.
- **Fixture weakness (fixed):** `detection_frozen_minimal` was an obsolete v1 partial handoff. It now supplies the current frozen brief/evidence shape.
- **Production prompt/model weakness (partly fixed):** AI canonical generation initially invented concrete capabilities and weakened a hypothetical/no-availability scope. AI guidance now treats message references as request intent rather than product evidence and requires hypothetical scope to remain visible. The rerun completed with a scope-review warning, not a contract failure.
- **Production prompt/model weakness (fixed in stage rerun):** Adaptation produced unreadably dense Psychology copy and invalid hashtag syntax. Tighter copy and metadata instructions produced a passing independent adaptation rerun.
- **Production prompt/model weakness (fixed in stage rerun):** Determination selected Psychology despite explicit English-only scope. A generic binding-scope instruction made the English chain route correctly.
- **Acceptance evaluator weakness (fixed):** Psychology `non-diagnostic` wording was falsely failed for not containing the exact word `diagnosis`; it is now human-review conservation evidence. English chain wording variation for `coworkers` was similarly removed as a hard lexical failure.
- **Unresolved production/fixture failure:** `chain_frozen_ai_scope` errored in all three regression attempts. This is the most important remaining blocker and requires artifact-level diagnosis and a focused rerun before image acceptance.
- **Unresolved provider/transient behavior:** `incomplete_idea` errored in two of three repeated regression attempts. The 60-second one-attempt client timeout preserves uncertainty safely, but the intermittent behavior needs focused classification.

## Fixes made

- Acceptance-only fixture and stage coverage: `acceptance/framework.py`, `acceptance/adapters/pipeline.py`, `acceptance/cases/pass2_text_matrix.json`, `acceptance/runners/matrix.py`, and acceptance tests.
- Production hardening: `src/common/gemini.py` uses a bounded one-attempt 60-second request deadline; `src/workflow/gemini_generation.py`, `gemini_determination.py`, and `gemini_adaptation.py` were tightened at their owning prompt boundaries.
- Each change was followed by the offline suite and documentation checks; the latest run recorded 275 tests plus 199 subtests passing.

## Remaining concerns and Pass 3 recommendation

Do not begin paid image/storyboard acceptance yet. Resolve and repeatedly rerun the frozen AI chain and intermittent incomplete Intake case first, then run the full edge matrix and required Determination/Editorial/AI/Psychology repetitions. Continue watching AI hypothetical-scope preservation, Psychology qualification preservation, and adaptation compression. Only proceed when those failures are triaged or corrected with stable live evidence.
