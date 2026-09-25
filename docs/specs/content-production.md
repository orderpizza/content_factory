# Content Production

**Owner:** Canonical generation, per-destination adaptation and semantic QA.
**Implementation:** `gemini_generation.py`, `content_contract.py`,
`gemini_adaptation.py`, and transactional finalization in `store.py`.
Default deterministic workers remain non-deliverable fixtures.

## Persisted flow

```text
Determination → EditorialPlanRun → immutable EditorialPlan + ContentJob + GenerationRun
→ CanonicalContent + OutputRequests + VisualPlanRuns
→ deterministic VisualPlanner → immutable VisualRecipe + AdaptationRun
→ resolved content contract → Adaptation + deterministic semantic QA
→ immutable ContentPackage + StoryboardPlanRun
→ deterministic render pagination → StoryboardPlan + RenderRun
→ PromptCompiler → Gemini boards → assets + ReviewRequest
```

Workers exchange SQLite records, never direct calls. Each handoff is atomic and
fenced. [Data model](data-model.md) owns lineage;
[visual rendering](visual-rendering.md) owns archetypes, boards and assets.

## Prompt composition and authority

`prompt_policy.py` composes a stage task, shared input-authority rules, only the
relevant domain policy, and a minimal immutable request. The canonical domain
remit owner is `catalog.py`. Intake needs no domain catalog; Determination uses
its frozen catalog. Planning receives one domain's strategy/qualification rules
and bounded treatment history. Generation receives only the selected treatment,
brief intent/constraints and evidence, not losing candidates, selection dimensions,
route rationale, history or output bindings. Adaptation receives canonical content,
one resolved content contract and its destination, not a serialized visual recipe.
The full decision history remains persisted for humans.

Human messages establish requested subjects and constraints. They do not establish
unstated facts about those subjects. System configuration supplies policy, not
factual evidence. Planning supplies strategic obligations, not factual answers.
No stage performs external research. Text prompts are instructions; schemas and
local validators are the enforcement boundary.

## Canonical generation

`workflow_gemini_generation_prompt_v6` returns `canonical_content_v3`. The job
recipe remains `content_job_recipe_v3`. The closed schema contains hook, context,
2–8 key points, 0–8 examples, takeaway, optional CTA, up to 30 claims, and one
matching domain payload. It contains no platform copy, hashtags or visual design.

Every non-null semantic string, including every domain-payload leaf, must exactly
match text in the claims registry. Repeated text may reuse a registry entry.
This deliberately avoids an unenforced parallel factual prose channel. The
validator rejects missing registration, foreign references and invalid classes.
It cannot determine whether a model assigned a truthful class or whether a
paraphrase in subsequent adaptation is semantically faithful.

| Claim kind | Authority and enforcement |
| --- | --- |
| `source_bound_fact` | Requires allowed evidence references and a literal excerpt present in a cited source record. A topic-only message cannot support an unrelated assertion. Quotation membership is not independent fact verification. |
| `model_general_knowledge` | Standard English teaching knowledge only; no evidence references. Unverified model knowledge, not a fact supplied by the human. Origin/cultural assertions still require evidence by domain policy. |
| `qualified_inference` | Cautious interpretation with an honest qualification; cited references must belong to supplied evidence. Uncertainty must remain visible in public prose. |
| `generated_example` | Invented illustration, no evidence references. Common `examples` entries require this class. |
| `editorial_framing` | Nonfactual invitation/question in hook or CTA only, no evidence references; rejected in other semantic fields. Factual assertions must not be mislabeled as framing. |

Evidence IDs come only from actual human message records, Detection observations
and supplied `reference_id` records containing text. Arbitrary job, thread or
candidate IDs do not establish evidence. Literal source text is not independently
verified, and quotation alone cannot establish the truth of a source's claim.
[Domain policy](../pipelines/domains.md) supplies epistemic review criteria.
AI/Tech cannot use model priors for current product facts. Psychology preserves
observations, qualified possibilities and alternatives; its mechanism remains
nullable when evidence establishes none.

Generation success commits canonical content and output/visual-planning work
atomically. Failure creates no partial fan-out. Human revisions create new jobs;
canonical reuse across revisions is not implemented.

## Resolved content capacity and English content pagination

`content_contract.py` owns `resolved_content_contract_v1`. Before Adaptation,
the caller resolves platform character bounds, the selected archetype's copy
capacities and English line grammar into one model-facing contract. It records
roles/purposes, title/body budgets, line bounds, target-expression positions and
dialogue requirements. Obsolete overlapping guidance is not sent alongside it.
Local validation enforces those same capacities without truncation.

English has three registered semantic sequences, applicable to all three English
archetypes. Count is deterministic from canonical content, never freely chosen by
Adaptation or the image model:

| Count | Sequence |
| --- | --- |
| 4 | Hero expression, meaning, short dialogue, takeaway |
| 5 | Hero expression, meaning, two examples, short dialogue, takeaway |
| 6 | Hero expression, meaning, use contexts, two examples, short dialogue, takeaway |

Three or more usage notes select six units; otherwise two or more canonical
examples select five; otherwise four. An explicit human `content_slide_count`
constraint (four/five/six slides) is preserved by Intake and stamped into canonical
metadata by the caller; it fixes the bounded count. Readability is enforced by
per-position capacity. If the selected count cannot preserve the content, adaptation
fails for narrower planning rather than silently padding, truncating or increasing
count. This is a conservative deterministic count heuristic, not semantic entailment.

The accepted six-position teaching grammar remains available: hook ≤5 title words
and ≤20 body words; meaning ≤60 body words over 1–5 lines (first ≤35 words,
subsequent ≤18); use contexts 3–4 lines of ≤14 words; examples two lines of ≤22;
dialogue 3–4 turns of ≤16; takeaway 2–3 lines of ≤16. Scene archetypes retain
stricter capacities. Titles have at most two lines; other English titles ≤12 words.
English titles/bodies are at most 120/600 characters. The resolved contract selects
the applicable positions; removing a use-context/example position also selects
the matching local overlay and visual direction, rather than shifting labels.

AI/Tech and Psychology remain bounded at 4–14 units, normally 4–8, with hook first,
takeaway last and at least one explanation and example inside. Their resolved
role capacities are titles ≤80 characters/10 words/two lines, bodies ≤280
characters/30 words/three lines/16 words per line. Qualifications cannot be removed
to fit. Existing substantive AI explanation and Psychology takeaway checks remain.

Content pagination freezes semantic units. The separate `render_text_policy.py`
then packs those units into image calls without changing any text, count or order.
Every final slide remains 1080×1350, 4:5. Render budgets are provisional calibration
values, not proven provider limits; their versions and thresholds are unchanged.

## Instagram package contract

`workflow_gemini_adaptation_prompt_v12` produces `output_adaptation_v4` for
`instagram_static_carousel_v2`. The caller stamps the archetype, resolved content
contract and semantic-QA result into the immutable package. Adaptation owns copy
and metadata; it cannot choose design, produce assets or authorize delivery.

Every canonical claim must map into caption and/or slide copy. Section labels
belong to deterministic chrome; new English slide titles must add lesson-specific
information. Known redundant labels fail validation. This reduces actual render
text naturally; measurements are never adjusted to simulate savings.

Caption summary ≤1100 characters; complete caption ≤1500. CTA is null or ≤12
words/120 characters. Private tags: 2–6 unique strings, ≤80 characters each.
Hashtags: at most eight unique lowercase ASCII tags. Alt text ≤1000 characters.
`visual_cues` remains a closed list: slide ordinal, mapped subject claim ID,
semantic emphasis and 0–4 participants. No free-form image/style prompts occur.

Preview mode fails invalid output without a repair call. Preserved inactive delivery
mode checkpoints valid body copy and permits one metadata-only repair. Its prompt
is `workflow_gemini_adaptation_metadata_retry_v2`; it receives only the checkpointed
body. Repair never rewrites body text or canonical content. Metadata failure does
not regenerate canonical content or sibling outputs.

## Pre-render semantic QA

`pre_render_semantic_qa_v1` reuses capacity/archetype validation, then checks planned
count/roles, target expression in hero and dialogue text, alternating distinct
speakers, claim coverage and directly detectable polarity reversals of mapped
claim text. The package carries the result. Finalization recomputes it from frozen
canonical content and the recipe; the renderer rechecks it before any image call.
A forged/stale result cannot authorize rendering.

These deterministic checks do not grade dialogue naturalness, arbitrary logical
contradictions, factual truth, or paraphrase entailment. No paid QA model, OCR grader
or research subsystem is added. Human review remains necessary. The controlled
acceptance corpus replays already-authored copy as `frozen_acceptance_package_v1`,
including its historical titles. This acceptance-only helper keeps core package,
claim, archetype-capacity and render checks and is absent from production workers;
it does not claim that old copy passed the new authoring QA.

## Spending, traces and recovery

[Configuration](configuration.md#model-admission) owns token assumptions and caps.
[Reliability](reliability.md#gemini-accounting) owns the single reservation ledger,
exact execution traces, settlement and uncertain outcomes. No second estimator is
introduced. Text output defaults remain unchanged; the 10,000-token ceiling remains.
A budget deferral makes no call. Failed or uncertain paid calls are not automatically
replayed. Review-only operation and per-destination Post now ownership are unchanged.
