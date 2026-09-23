# Content Production

**Owner:** Canonical generation and per-destination adaptation.
**Implementation:** `src/workflow/gemini_generation.py`,
`src/workflow/gemini_adaptation.py`, and finalization in `src/workflow/store.py`.
This document describes the Gemini workers. Default deterministic workers produce
non-deliverable fixtures; [runtime](runtime.md#workflow-composition) selects the mode.

## Persisted flow

```text
Determination → EditorialPlanRun → immutable EditorialPlan + ContentJob + GenerationRun
  → CanonicalContent + frozen OutputRequests + VisualPlanRuns
  → deterministic VisualPlanner → immutable VisualRecipe + AdaptationRun
  → one ContentPackage + RenderRun per successful output
  → deterministic PromptCompiler → renderer → assets + ReviewRequest
```

Each handoff is an atomic, fenced SQLite transaction. Workers never invoke the
next worker. Canonical content, job recipes, output plans and packages are
immutable. The [data model](data-model.md) owns identities and constraints;
[visual rendering](visual-rendering.md) owns asset production.

## Canonical generation

A job references its immutable EditorialPlan and freezes the brief, selected
domain/angle, source context and at most one
Instagram binding. Generation makes one Gemini drafting call for
the claimed run. The plan is a writing constraint: preserve its selected angle,
reader promise, must-cover points and qualifications; do not select a new strategy.
The request recipe is `content_job_recipe_v3`; the generation prompt is
`workflow_gemini_generation_prompt_v2`. Its closed `canonical_content_v1` schema contains:

- hook, context, 2–8 key points, 0–8 examples, takeaway and optional CTA;
- up to 30 claims, each with a unique ID, text, kind, evidence reference IDs
  and qualification;
- the matching domain payload defined by `DOMAIN_FIELDS`.

Claim kinds are `source_bound_fact`, `qualified_inference` and
`generated_example`. References must belong to the frozen job; a source-bound
fact requires at least one. Canonical content contains no account-specific
caption, layout, renderer selection or hashtags.

Validation enforces structure, cardinality and reference membership. It does
**not** prove that evidence supports a claim, that an example is natural, or
that a domain's editorial rules are satisfied. There is no approved teaching
reference catalog, autonomous research or second semantic-validation model call.
[Domain policy](../pipelines/domains.md) guides prompts and human review.

Successful generation commits one canonical result per job, all frozen
OutputRequests and their initial pending VisualPlanRuns together. Failure does
not create partial fan-out. There is no capacity-slot allocator or
cross-revision canonical reuse.

## Output adaptation — `output_adaptation_v2`

An adaptation reads one canonical object, frozen destination and committed visual
recipe. It receives the selected archetype's complete slide grammar, composition
and capacities. The selection is immutable; adaptation writes exact copy and
metadata for that grammar, preserving every claim and qualification. It cannot
select an archetype, theme, font or color, fetch evidence, change the angle or emit
image-generation instructions. The caller stamps the selected archetype into the
package; it is not a model-generated field.

The first model call returns body and metadata together:

- In preview mode, invalid output fails the run without a metadata repair call.
- In the preserved inactive delivery mode, a valid adapted body is checkpointed with its hash.
  If only metadata validation fails, one metadata-only repair call is permitted
  for that claim. A persisted body can be used on an explicitly recoverable run;
  it is not redrafted. Invocation identity and cost-uncertainty guards still apply.
- Invalid body, failed repair, or unsafe replay fails visibly. There is no
  unbounded drafting/repair loop.

A metadata failure does not discard or regenerate canonical content. Canonical
content commits before adaptation begins. Failure on one output does not rerun
generation.

Success atomically persists one ContentPackage per OutputRequest, completes the
adaptation and creates RenderRun referencing the already selected recipe. SQL
lineage constraints prevent borrowing another output's recipe. Synthetic packages
remain non-deliverable. All supported domain formats use
[Gemini rendering](visual-rendering.md#gemini-designer-review-rendering).

## Instagram package contract

The only active platform is Instagram, using `instagram_static_carousel_v2`.
Every current domain has one destination binding. Adaptation consumes immutable
canonical content for that frozen destination, preserving angle, claims,
qualifications and meaning. It never writes assets or posting authorization.

`workflow.gemini_adaptation.adaptation_schema` owns exact fields. A package has
exactly six ordered visual units beginning with hook and ending with takeaway, caption,
optional CTA, private tags, hashtags, alt text, claim mappings and bounded semantic
visual cues. Every English archetype requires six units with roles
hook, explanation, explanation, example, example, takeaway.

Local limits: title 120 characters, body 600, caption summary 1100, total caption
1500; CTA at most 12 words/120 characters or null; 2–6 unique private tags, at most
8 unique lowercase ASCII hashtags, alt text at most 1000 characters. Every
canonical claim must be mapped into copy or units. The active Gemini review
workflow additionally applies the English expression archetype's position-specific
title, word-count and line-count limits during adaptation, plus the selected
archetype capacities. Scene/product/process archetypes use tighter copy limits.

`output_adaptation_v2` is closed and requires six units. Domain-aware validation
(including body checkpoints) requires AI/Tech and Psychology roles `hook,
explanation, explanation, example, explanation, takeaway`. Adaptation prompt
`workflow_gemini_adaptation_prompt_v6` assigns these semantic positions; the
selected archetype further controls composition and capacity:

| Slide | AI/Tech | Psychology |
| --- | --- | --- |
| 1 | Hook | Hook / observed pattern |
| 2 | What changed / what it is | Concept / meaning |
| 3 | Why it matters / how it works | Possible mechanism |
| 4 | Practical use / example | Everyday example / scenario |
| 5 | Limitations / caveats | Practical implication / response |
| 6 | Takeaway | Takeaway + qualification |

`visual_explainers.py` owns these narrow validators. Titles are at most 80
characters/12 words; bodies at most 360 characters/60 words; each field has at
most five nonempty lines. AI/Tech slide 5 and Psychology slide 6 require at least
20 body characters to reject empty placeholders. These are capacity checks, not
semantic verification. Human review determines whether a caveat is meaningful,
qualification is retained and claims are correct. Every canonical claim still
requires a valid mapping; none may be dropped to satisfy capacity limits.

AI/Tech adaptation uses the canonical feature/change, scope, capabilities, use
cases and limitations. Psychology uses observed behavior, concept, possible
mechanism, alternative explanations, scenario, practical implications and
qualification. Prompts distinguish observation from inference, retain uncertainty
and prohibit diagnostic language; no new canonical schema or research call exists.


## Post-specific visual cues

`visual_cues` replaces generic presentation intent. It is a closed list of zero
to six entries, at most one per slide. Each entry contains `slide` (1–6),
`subject_claim_id` (an existing canonical claim mapped to that slide),
`semantic_emphasis` (situation, contrast, sequence, qualification or takeaway),
and `participants_count` (0–4). There are no free-text subject/prompt/style fields.
Use an empty list when a cue adds no value. The compiler uses these bounded
references alongside exact slide copy; account/archetype configuration owns all
art direction. Package and body checkpoint validation preserve all claim mappings.

## Spending and recovery

[Configuration](configuration.md#model-admission) owns model settings and phase
allowances. [Reliability](reliability.md#gemini-accounting) owns reservation,
settlement and uncertain-call behavior. Intake/Determination use the daily budget;
generation and every adaptation/repair also share the original job's USD cap.

A daily-budget deferral makes no provider call. A failed or uncertain invocation
is not automatically rerun just because the worker polls again. Pending runs
are claimed sequentially; schema states such as `waiting_capacity` are not
evidence of an implemented capacity scheduler.

## Revisions and limitations

Human refinement creates a new immutable brief and decision. Scoped review
feedback retains its output/domain scope and excludes unchanged sibling routes.
It does not implement canonical reuse: a newly selected route creates a new job.
Existing approved or in-flight siblings are not silently cancelled.

Checks fence closed/cancelled threads at handoff boundaries, but the dashboard
does not expose a general cancel-thread command. Exact delivery cancellation
belongs to [posting](posting.md).
