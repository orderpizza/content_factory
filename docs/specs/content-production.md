# Content Production

**Owner:** Canonical generation and per-destination adaptation.
**Implementation:** `src/workflow/gemini_generation.py`,
`src/workflow/gemini_adaptation.py`, and finalization in `src/workflow/store.py`.
This document describes the Gemini workers. Default deterministic workers produce
non-deliverable fixtures; [runtime](runtime.md#workflow-composition) selects the mode.

## Persisted flow

```text
ContentJob + GenerationRun
  → CanonicalContent + frozen OutputRequests + AdaptationRuns
  → one ContentPackage + VisualPlanRun per successful output
  → immutable VisualRecipe + RenderRun → renderer → assets + ReviewRequest
```

Each handoff is an atomic, fenced SQLite transaction. Workers never invoke the
next worker. Canonical content, job recipes, output plans and packages are
immutable. The [data model](data-model.md) owns identities and constraints;
[visual rendering](visual-rendering.md) owns asset production.

## Canonical generation

A job freezes the brief, selected domain/angle, source context and at most one
Instagram binding. Generation makes one Gemini drafting call for
the claimed run. Its closed `canonical_content_v1` schema contains:

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
OutputRequests and their initial pending AdaptationRuns together. Failure does
not create partial fan-out. There is no capacity-slot allocator or
cross-revision canonical reuse.

## Output adaptation — `output_adaptation_v1`

An adaptation reads one canonical object and one frozen destination. It selects
and arranges supported content, creates platform copy/metadata and emits a
closed semantic `visual_intent`. It does not fetch evidence or change the approved
angle. Closed schemas, claim-ID mappings and local limits are defined in
[Instagram package contract](#instagram-package-contract); semantic fidelity still needs review.

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
adaptation and creates its first pending VisualPlanRun. The shared deterministic
planner selects a compatible curated visual archetype/preset, then resolves only
its approved variants and commits a separate immutable VisualRecipe before
creating its RenderRun. RenderRuns reference the exact package and recipe.
Synthetic packages remain non-deliverable. English expression-breakdown review packages
use the Gemini rendering path; other domains stop as described in
[visual rendering](visual-rendering.md#gemini-designer-review-rendering).
Adaptation owns exact semantic copy and visual intent, never final image prompts;
the renderer interprets `expression_breakdown_v1` as six semantic slide roles
rather than its deterministic CSS/layout choices. The HTML library is preserved inactive.

## Instagram package contract

The only active platform is Instagram, using `instagram_static_carousel_v2`.
Every current domain has one destination binding. Adaptation consumes immutable
canonical content for that frozen destination, preserving angle, claims,
qualifications and meaning. It never writes assets or posting authorization.

`workflow.gemini_adaptation.adaptation_schema` owns exact fields. A package has
5–8 ordered visual units beginning with hook and ending with takeaway, caption,
optional CTA, private tags, hashtags, alt text, claim mappings and semantic
visual intent. English `expression_breakdown_v1` requires six units with roles
hook, explanation, explanation, example, example, takeaway.

Local limits: title 120 characters, body 600, caption summary 1100, total caption
1500; CTA at most 12 words/120 characters or null; 2–6 unique private tags, at most
8 unique lowercase ASCII hashtags, alt text at most 1000 characters. Every
canonical claim must be mapped into copy or units.


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