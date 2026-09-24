# Pass 2 Artifact Review

## Executive Summary

This review inspected 14 usable local attempts and 4 failures from the live Pass 2C/2D acceptance workspaces. It made no Gemini, image, Vertex, or judge-model calls. The small, source-preserving bundle is under `PASS2_REVIEW_SAMPLES/`.

The strongest evidence is the bounded Acme AI material. Two completed final full chains and one direct final Generation sample faithfully preserve `fixture:acme:1`, Enterprise-only October 2026 availability, the two announced capabilities, and unstated procurement facts. English Intake, routing, planning, and the one complete final chain are also broadly usable.

The existing report is only partially supported as a conclusion about text quality. Its narrow bounded-AI conclusion and its provider-availability conclusion are supported. Its broader conclusion that the inspected Psychology artifacts have no remaining semantic problem is contradicted: repeated final canonicals introduce ungrounded, quasi-causal explanations for hesitation (for example, “social data collection,” minimizing social risk, and acquiring social capital), even while disclaiming diagnosis. These are not clinical diagnoses, but they exceed the fixture's cautious observation and “one possible explanation” framing. The deterministic evaluator reports WARN, not FAIL.

**Recommendation: do not begin Pass 3 visual acceptance yet.** The original repeated full-chain availability gate remains unmet. Independently, the repeated Psychology epistemic-overreach pattern should be corrected and re-reviewed before visual work amplifies it. Neither finding calls for a new paid call in this review; it is a conclusion from already persisted artifacts.

## Evidence Scope and Run Inventory

The report names these Pass 2D runs, all of which were located locally:

| Run ID | Profile / purpose | Attempts used here | Result described by run summary |
| --- | --- | --- | --- |
| `20260924T074307-c08c6352` | Full 30-case matrix, before evaluator fixture corrections | Intake multi-domain and series | 19 PASS, 4 WARN, 3 FAIL, 4 ERROR |
| `20260924T075539-1cfe100e` | Focused rerun of safe Intake clarification cases | Experiment-like clarification | 3 PASS |
| `20260924T072547-824c7edc` | Final-policy bounded-AI full-chain repeat | AI attempts 1, 2, 9 | 9 WARN completions, 6 ERROR |
| `20260924T080135-649be4bd` | Final-configuration high-risk repetitions | English, Intake, Determination, AI direct, Psychology, adaptation | 49 PASS, 29 WARN, 2 pre-fix FAIL, 20 ERROR |
| `20260924T083654-fffdbca1` | Post-fix AI-scope focused rerun | AI scope attempts 1 and 3 | 7 WARN, 3 ERROR |

Each bundled directory names its source run, case, attempt, stage files, and original acceptance status in `REVIEW.md`. It contains copied JSON handoffs and evaluations only; it omits SQLite databases, WAL/SHM files, image assets, environment files, and run-level provider/cost metadata. The copied stage JSON is substantively unchanged. The available sanitised evaluation files do not expose an HTTP status for individual provider errors, so the bundle does not claim a particular 429 or 504 for a selected error.

## Sample Selection

| # | Domain | Case | Stage range | Status | Configuration | Reason selected |
| --- | --- | --- | --- | --- | --- | --- |
| 1 | English | `chain_english_icebreaker` | Intake → Adaptation | PASS | Final | Only completed final high-risk English full chain |
| 2 | English | `stage_editorial_english` | Intake → Editorial | PASS | Final | Alternative scenario treatment |
| 3 | Intake | `intake_clear_complete` | Intake | PASS | Final | Clear constrained idea |
| 4 | Intake | `intake_multi_domain` | Intake | PASS | Final token / pre evaluator-only fixes | Adjacent-domain content preserved |
| 5 | Intake | `intake_series_like` | Intake | PASS | Final token / pre evaluator-only fixes | Series-shaped request |
| 6 | Intake | `intake_experiment_like` | Intake | PASS | Final | Clarification instead of invented experiment |
| 7 | Determination | `detection_frozen_minimal` | Determination | WARN | Final | Selected/skipped-route evidence |
| 8 | AI/Tech | `chain_frozen_ai_scope` | Determination → Adaptation | WARN | Final | Full chain, confirmed-feature treatment |
| 9 | AI/Tech | `chain_frozen_ai_scope` | Determination → Adaptation | WARN | Final | Full chain, unknowns-first treatment |
| 10 | AI/Tech | `stage_generation_ai_bounded` | Generation | PASS | Final | Direct bounded-evidence Generation |
| 11 | AI/Tech | `stage_generation_ai_scope` | Generation | WARN | Final | Hypothetical / availability-sensitive result |
| 12 | Psychology | `stage_generation_psychology_uncertainty` | Generation | WARN | Final | Uncertainty and non-diagnostic case |
| 13 | Psychology | `stage_generation_psychology_uncertainty` | Generation | WARN | Final | Repeat testing diagnostic/causal temptation |
| 14 | Psychology | `stage_adaptation_psychology` | Adaptation | PASS | Final | Carousel compression and qualification preservation |

The failure sample comprises English-chain Editorial failure, bounded-AI-chain Editorial failure, final AI-scope Generation failure, and the pre-fix AI-scope evaluator false positive. It is deliberately separate from usable-content quality.

The requested `trend` and `evergreen` treatments are represented by the AI full chains and English/Psychology material. The local acceptance artifacts do contain series-like and experiment-like **Intake** results, but none of the inspected live EditorialPlans reaches a `series` or `experiment` lane. This is a coverage limitation, not missing content manufactured by the review.

## English Findings

The full chain preserves the source's English-only constraint and its first meeting with coworkers. Determination correctly declines the tempting adjacent Psychology route, and the two plan candidates differ meaningfully (meaning and usage versus scenario teaching). The canonical meaning, register, examples, and avoidance of invented etymology are sound. The adaptation has a clear six-slide progression and reasonable metadata.

The quality ceiling is editorial rather than factual. It uses promotional social outcome language—“instantly warm up,” “reduce social awkwardness,” “better team dynamics”—that reaches beyond teaching a phrase. The joke in the dialogue is a narrow icebreaker choice, and a few instructions are awkward (“actual ice in a professional metaphor”). This still looks usable with human review, but it is not evidence that English copy is consistently polished: final full-chain availability was only one completion in ten attempts.

## AI/Tech Findings

The bounded Acme samples are the clearest positive result. In both completed full chains and the direct Generation result, the material:

- retains `fixture:acme:1` on factual claims;
- limits availability to Enterprise-plan customers beginning in October 2026;
- names only centralized administrative controls and Acme Data Workspace integration; and
- says pricing, certifications, geography, benchmarks, rollout, deployment, and comparisons are unstated rather than filling them in.

The unknowns-first full-chain sample is especially effective because it makes procurement restraint the editorial point. No fabricated Acme capability, date, or availability expansion was found in the reviewed outputs.

The post-fix hypothetical AI-scope result also correctly says it is hypothetical and has no commercial availability. Its weakness is different: it turns a sparse requested framework into generic assumptions about real-time transcription, workflow mechanics, and human-review checkpoints. They are plausible examples, not evidence-backed facts. The evaluator correctly stopped requiring a literal word, but does not judge whether this generic elaboration is useful or sufficiently anchored.

## Psychology Findings

The reviewed Generation artifacts visibly avoid a diagnosis, name alternative explanations, and include non-diagnostic qualifications. They do not identify a disorder or assert that hesitation proves anxiety.

That safety boundary is not enough. Attempts 1 and 4 repeatedly claim more than the supplied observation supports: reduced speech and scanning are described as frequent; silence is made into social data collection; an internal aim to minimize risk is proposed; and one repeat talks about acquiring social capital and norm alignment. These explanations are presented as likely mechanisms, even where a disclaimer is present. The fixture calls for an observation and one possible explanation, not a generalized account of internal motives. This is a semantic/content risk with direct implications for publication.

The adaptation sample retains “may,” optional participation, and a non-diagnostic caveat, and its six slides are compact. Its upstream canonical is a frozen fixture, however, so it cannot validate whether a live Psychology canonical remains cautious after compression. Its hook is generic and some slide language (“ambiguity often leads”) strengthens causality.

## Intake, Determination, and Editorial Findings

Clear Intake is appropriately compact. The multi-domain brief preserves both the AI and human-response aspects rather than deciding its own destination. Experiment-like Intake appropriately asks for clarification rather than inventing an experiment. The earlier FAIL on that behavior was demonstrably an evaluator-fixture issue, and the focused rerun's PASS is appropriate.

The live frozen-Detection decision provides useful evidence that all three domains are explicitly assessed and skipped routes are reasoned. It is not, however, evidence of a live multi-domain Determination outcome: the multi-domain acceptance case ended at Intake. Similarly, the series-shaped and experiment-shaped examples do not reach a live EditorialPlan. Editorial coverage is strongest for English evergreen and AI trend; it is not sufficient to claim verified live planning quality for every requested lane.

## Adaptation Findings

The English and bounded-AI full chains preserve their canonical core in carousel-sized units. The AI carousel successfully separates confirmed details from unknowns. English has workable progression but can be more promotional than the canonical lesson. The Psychology adaptation preserves visible qualification, but it uses frozen upstream text and therefore is only direct evidence about the adaptation stage.

Overall, the usable adaptations could enter the visual pipeline only under normal human content review. No density breach was observed in the samples, but semantic preservation is not uniformly demonstrated for live Psychology input.

## Evaluator Blind Spots

- Psychology outputs can be non-diagnostic and still make unsupported claims about motives, mechanisms, frequency, or causality.
- A hypothetical AI result can be structurally qualified yet filled with generic product-workflow assumptions that are neither requested nor sourced.
- English copy can remain semantically correct while overpromising social outcomes or relying on a narrow example.
- The evaluator can verify lexical evidence IDs and forbidden categories, but cannot establish that an editorial angle is specific, natural, or non-generic.
- A frozen-upstream adaptation PASS says little about live upstream Generation quality.

## Failure Sample Review

The three selected ERROR cases preserve partial handoffs and correctly stop before downstream stages. The English and bounded-AI full chains both reached a valid Determination before Editorial Planning failed; the final AI-scope error failed at Generation after frozen upstream handoffs. None has usable generated text at its failed stage, so none is counted as a bad content result.

The selected pre-fix AI-scope FAIL is a genuine evaluator false positive. Its canonical repeatedly says the workflow is hypothetical and declares no availability; the FAIL is only a missing literal canonical term. The final focused rerun has no equivalent FAIL. The reviewer agrees with that classification.

## Existing Report Verification

| Existing report claim | Independent verdict | Evidence |
| --- | --- | --- |
| 6,000 tokens is adequate for bounded direct Generation | Supported | Direct bounded sample is complete and concise; no truncation appears in selected final output. |
| Bounded Acme full-chain outputs preserve lineage, scope, and unknowns | Supported | Samples 8–10 preserve `fixture:acme:1`, plan scope, and unknowns with no invented capability. |
| AI-scope literal guard produced false positives and the fix worked | Supported | Pre-fix sample 18 is safe on scope despite its literal-missing FAIL; final sample 11 has no FAIL. |
| Provider/stage availability, not usable-content safety, prevents repeated full-chain closure | Supported | Selected ERRORs preserve partial handoffs; the cited campaigns still miss the completed-chain targets. |
| Psychology artifacts remained non-diagnostic and included alternatives | Supported, narrowly | Samples 12–13 visibly disclaim diagnosis and list alternatives. |
| No untriaged semantic failure remained in usable Psychology responses | Contradicted | Repeated final Psychology canonicals introduce unsupported causal/motivational explanations that the evaluator does not fail. |
| Human review found no adaptation quality problem worth recording | Partially supported | No severe density or scope loss was found, but English is overpromotional and Psychology adaptation is weak/generic and fixture-backed. |
| Pass 3 should not start | Supported, for stronger reasons | Repeated chain availability remains unmet; the Psychology pattern adds a substantive text-quality gate. |

## Remaining Text Risks

### Semantic/content risks

- Psychology canonical generation can convert cautious observations into confident accounts of internal mechanism or motive.
- Hypothetical AI content can add generic design assertions beyond its source.
- Adaptation may retain a formal caveat while strengthening causal language in a compressed slide.

### Editorial-quality risks

- English can use promotional outcomes, culturally narrow examples, and slightly unnatural instruction.
- Psychology hooks and takeaways can be generic even when structurally valid.
- Evidence-bound AI is safe but repetitive; human editing still matters.

### Provider availability risks

- Final high-risk campaigns did not meet the required repeated end-to-end completion targets: the English chain had one usable completion in ten, and bounded AI had nine in fifteen. Provider failures must remain separate from content failures.

### Workflow/recovery risks

- Partial handoffs are preserved correctly, but stage errors in the sanitised artifacts are generic and do not always retain a transport code for a compact external review.
- Existing acceptance coverage does not demonstrate live Editorial Planning in series or experiment lanes, nor a live multi-domain Determination result.

## Pass 3 Recommendation

Do **not** start Pass 3 visual acceptance. This is not a demand for text perfection. The bounded-AI material is a credible textual foundation and the English issues are reviewable editorial weaknesses. But a repeated Psychology pattern of motive/mechanism inflation is not a minor polish issue: visuals would make those claims more authoritative. Address it, then use a separately approved acceptance effort to verify the correction and the existing repeated full-chain availability gates. No new paid calls were made for this review.
