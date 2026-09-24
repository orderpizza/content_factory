# Live Gemini Text Acceptance Report

## Executive summary

This report supersedes Pass 2C. Pass 2D established an evidence-based
Generation allowance of 6,000 output tokens, completed the intended full
matrix, and found no untriaged semantic failure in usable bounded AI evidence,
English, or Psychology responses. Image calls were zero.

Text acceptance is **not closed** and Pass 3 should **not** begin yet. The
remaining gate is repeated full-chain availability: the bounded AI chain
produced 9 semantic/contract-valid completions under the final configuration,
not the required 10, and the high-risk English full chain produced only 1
completion in 10 independent attempts. These are provider/stage availability
failures rather than evidence that the completed content is unsafe, but the
requested stable full-chain evidence does not yet exist.

## Campaign boundaries and preflight

- Model: `gemini-3-flash-preview`; every live attempt used an isolated,
  current-schema SQLite workspace under `data/acceptance/`.
- Live execution required both opt-ins, finite USD/call limits, the production
  `ModelBudgetPolicy`, and the persisted invocation ledger. No worker retried
  an uncertain invocation.
- The final dry full matrix planned 30 cases, 140 calls, $0.686, and 0 image
  calls. Smoke, stage, and regression dry runs also completed. The CLI only
  accepts positive image ceilings, so the runs used a ceiling of 1 while every
  selected case declared 0; every recorded live run has **actual image calls
  = 0** and no image model.
- Final offline verification: **280 passed, 199 subtests passed**; documentation
  check passed (18 current documents, 65 schema tables). Normal CI remains
  offline and no credential or acceptance workspace is tracked.

## Generation token calibration

The original full chain reached 3,985 output tokens against the 4,000-token
limit and returned incomplete JSON. Calibration used the direct,
production-shaped bounded-evidence fixture so upstream availability could not
mask Generation behavior.

| Ceiling | Attempts | Usable / completion | Output tokens observed | Schema, canonical, semantic result | Estimated cost |
| --- | ---: | --- | --- | --- | ---: |
| 4K | 3 | 1 usable, 1 provider error, 1 pre-fix evaluator false positive | 1,154; 1,251 | usable response valid; the false positive was later removed | $0.009768 |
| 6K | 6 | 3 usable, 3 provider errors | 1,060–1,148 | all usable responses valid | $0.013880 |
| 8K | 3 | 3 usable | 1,119–1,536 | all valid | $0.015261 |
| Final 6K direct repeat | 10 | 10 usable | recorded in workspace | 8 PASS, 2 qualification-review WARN, 0 FAIL | $0.049083 |

The selected production allowance is **6,000 output tokens**. It is the
smallest tested allowance with comfortable room above the observed complete
responses; 8K was not selected merely for being larger. The actual production
default, reservation calculation, `.env.example`, configuration contract,
and budget tests were updated together.

## AI bounded-evidence chain

The final-policy full-chain run
`20260924T072547-824c7edc` made 15 explicitly accounted attempts: **9
semantic/contract-valid WARN completions and 6 provider errors**, with 47
calls and $0.353607. WARNs were conservative downstream evidence-reference or
qualification reviews; all nine completed Determination, Editorial, Canonical,
deterministic Visual Recipe, and Adaptation handoffs. A later independent
attempt reached the correct AI determination but failed at Editorial Planning
(`20260924T075929-6c6a4e76`).

Manual review of a completed canonical artifact confirmed:

- exact `fixture:acme:1` lineage;
- Enterprise-only October 2026 availability;
- only the announced administrative controls and Data Workspace integration;
- pricing, certifications, geography, benchmarks, rollout, deployment, and
  version comparison kept as unstated/unknown rather than asserted.

Thus content reliability is strong among the 9 usable full-chain results, but
the target of 10 valid completions within the 15-attempt cap was missed. The
direct final-policy bounded Generation repeat is 10/10 usable with no semantic
FAIL, but it does not substitute for the missing end-to-end completion.

## Incomplete Intake

Pass 2C already supplied 14 successful `incomplete_idea` attempts and one
60-second 504. Pass 2D's high-risk repeat added **8 PASS and 2 provider
errors**. Among 22 usable responses, no contract or semantic failure occurred.
The timeout remains finite and one-attempt: the observed intermittent 504s do
not justify silently increasing it.

## Full matrix coverage

The mandatory full run `20260924T074307-c08c6352` executed all 30 intended
cases once (30 calls, $0.034063, 0 images): 19 PASS, 4 WARN, 3 FAIL, and 4
provider errors. The three FAILs were safe `needs_clarification` results
against an overly narrow evaluator expectation for format/current-event/
experiment-like Intake. The fixture was corrected with regression coverage and
the affected neighborhood reran **3/3 PASS** in
`20260924T075539-1cfe100e`.

| Coverage group | Executed live coverage |
| --- | --- |
| Intake | Clear, terse, rambling, contradictory, missing, ambiguous, multi-domain, unsupported, audience/format, long, Unicode, quoted, injection-like, date-sensitive, evergreen, series, experiment, and clarification cases |
| Determination / frozen Detection | Human chains plus frozen minimal and bounded AI evidence; selected-route and evidence identity checks |
| Editorial | English evergreen/series planning, AI trend planning, and deterministic fixture planning |
| English | Intake and full English chain; workplace idiom/context preservation |
| AI/Tech | Scope, bounded launch/access limitation, date, provider unknowns, direct Generation, and frozen full chain |
| Psychology | Uncertainty/non-diagnosis canonical generation and adaptation compression |
| Adaptation | Psychology slide-bound/lineage checks plus all completed chain adaptations |

The four matrix errors were isolated provider-stage non-completions. The
matrix continued rather than terminating after any one error.

## High-risk repetitions

The final-config high-risk campaign
`20260924T080135-649be4bd` completed all 100 planned attempts (115 calls,
$0.306293, zero images). Its result counts were 49 PASS, 29 WARN, 20 ERROR,
and 2 pre-fix AI-scope evaluator FAIL.

| Case | Attempts | Usable results | Provider/stage errors | Semantic FAIL |
| --- | ---: | --- | ---: | ---: |
| Frozen Detection determination | 10 | 10 WARN | 0 | 0 |
| English Intake | 10 | 9 PASS | 1 | 0 |
| Incomplete Intake | 10 | 8 PASS | 2 | 0 |
| Clear Intake | 10 | 9 PASS | 1 | 0 |
| English Editorial | 10 | 10 PASS | 0 | 0 |
| Bounded AI Generation | 10 | 8 PASS, 2 WARN | 0 | 0 |
| AI scope Generation, pre-fix | 10 | 8 WARN | 0 | 2 evaluator false positives |
| Psychology Generation | 10 | 8 WARN | 2 | 0 |
| Psychology Adaptation | 10 | 4 PASS, 1 WARN | 5 | 0 |
| English full chain | 10 | 1 PASS | 9 | 0 |

The AI-scope literal guard was fixed after review. Its final-config focused
rerun `20260924T083654-fffdbca1` has 7 usable WARN and 3 provider errors,
with **0 FAIL**. It preserves the conservative human scope-review signal
without incorrectly requiring the literal word “availability.”

For usable results, contracts, schema validation, route/lane bounds,
conservation checks, and adaptation bounds were stable; WARN is intentionally
not converted into a semantic pass. Latency distributions are not reported:
the stored acceptance schema does not persist per-call monotonic latency, and
inventing derived timing would be misleading. Token usage and exact costs are
in the referenced workspaces.

## Provider reliability

Provider availability was materially intermittent:

- 38 completed live attempts were classified ERROR during Pass 2D; 11 carried
  explicit 504/deadline evidence and one bounded-chain attempt recorded 429
  alongside a deadline failure. Other errors are persisted stage/transport
  non-completions.
- One separately terminated repeat process
  (`20260924T075602-0119bb0b`) produced no completed evaluation artifact and
  is treated as an **uncertain invocation**, not a free retry or content result.
- Full-chain availability was especially poor late in the campaign: English
  chain 1/10 usable and bounded AI 9/15 usable. Single-stage bounded
  Generation was 10/10 usable; provider behavior therefore cannot be reported
  as a single content-quality percentage.

## Content/model reliability

Among usable outputs, there was no remaining semantic FAIL in the final
bounded-evidence AI direct Generation repeat, Psychology uncertainty samples,
or Intake samples. The two observed semantic FAILs were triaged as the
AI-scope literal evaluator defect, fixed, protected by an offline test, and
rerun with 0 FAIL. Completed AI chain outputs maintained evidence IDs and
unknowns; Psychology artifacts remained non-diagnostic and included
alternatives; English planning and Intake retained their requested context.

## Human review

Representative AI, Psychology, English planning, and adapted artifacts were
read directly. No hallucinated Acme capability, scope expansion, dropped
unknown, diagnostic claim, causal certainty, route/lane anomaly, or
adaptation density breach was found in the reviewed usable samples. The AI
CTA's invitation to monitor later disclosures was appropriate but remains
editorial language rather than evidence. The non-blocking WARNs correctly
identify places where lexical conservation cannot prove semantic equivalence.

## Defects and fixes

| Classification | Symptom and root cause | Fix and verification |
| --- | --- | --- |
| Budget/configuration | 4K Generation exhausted output allowance near the limit | Set production Generation default/reservation to 6K; updated config/docs/tests; calibrated direct 4K/6K/8K and repeated final 6K |
| Fixture/evaluator | Three Intake cases safely clarified but expected only completion | Allowed `needs_clarification`; regression test; affected 3-case live rerun passed |
| Fixture/evaluator | AI scope test required literal “availability” despite safe hypothetical/unavailable scope language | Removed brittle literal requirement while preserving scope review; regression test; final 10-attempt rerun had 0 FAIL |
| Provider/transport | 429/504/deadline and other stage non-completions | Preserved one-attempt worker behavior, isolated campaign attempts, and continued unrelated cases; no prompt/schema change justified |

## Cost

Pass 2D completed-accounting total is **222 text calls**, estimated
**$0.772785**, and **0 image calls**. That includes calibration, the 15-attempt
AI chain, complete matrix, focused Intake/chain checks, high-risk campaign,
and the final scope rerun. The interrupted uncertain run is excluded from this
completed-cost total. Calls were all to the configured text model; no image
model was selected.

## Remaining risks

- Repeated end-to-end provider availability is insufficient for the required
  ten-completion chains. Do not use the current evidence to claim operational
  throughput reliability.
- Several semantic conservations remain WARN by design because deterministic
  lexical checks cannot establish all semantic equivalences. Human review is
  still required at those gates.
- This is text-only acceptance. Image rendering, visual QA, board ratio,
  crops, overlays, review gallery, and vision judging remain explicitly
  deferred to Pass 3.

## Pass 3 readiness

**Recommendation: do not start Pass 3.** Conditions 1, 3–6, 8–10, 12–15 are
substantially evidenced: the 6K policy is production-real, the full matrix
executed, all domains and human/frozen paths have live coverage, material
semantic FAILs were fixed, offline CI is safe, and images remained zero.

Conditions 2, 7, and 11 are not yet satisfied at the required repeated
full-chain level. A later explicitly budgeted acceptance campaign should
obtain the missing bounded-AI tenth completion and ten usable English
full-chain/adaptation completions, while continuing to report 429/504 and
uncertain invocations separately. It must not treat those provider failures as
semantic model failures or perform blind worker retries.
