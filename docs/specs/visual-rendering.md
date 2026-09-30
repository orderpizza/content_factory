# Visual rendering

**Owner:** Account visual identity, curated archetypes, deterministic planning and
prompt compilation, and shared Gemini review rendering.

## Active boundary

```text
CanonicalContent + OutputRequest
→ VisualPlanRun → immutable VisualRecipe v5 + AdaptationRun
→ ContentPackage + StoryboardPlanRun
→ deterministic StoryboardPlanner → immutable StoryboardPlan + RenderRun
→ deterministic PromptCompiler → Gemini boards → split + overlays → ReviewRequest
```

Archetype is the only layer referred to as a curated visual template.
Each active Instagram account/domain has exactly three curated archetypes:

| Domain | Baseline | Specialized archetypes |
| --- | --- | --- |
| `english` | `expression_breakdown_v1` | `expression_story_scene_v1`, `expression_cards_v1` |
| `ai_tech` | `ai_tech_explainer_v1` | `ai_tech_product_ui_v1`, `ai_tech_system_diagram_v1` |
| `psychology` | `psychology_explainer_v1` | `psychology_human_scenario_v1`, `psychology_concept_cards_v1` |

`active_visual_profiles.py` owns closed frozen account and archetype definitions.
Account identity specifies personality, color behavior, illustration, typography,
whitespace, polish and positive/negative art direction. `AccountVisualIdentity`
contains only reusable brand/account art direction plus its ID and domain. It
never contains renderer geometry, slide sequencing, compiler instructions or
full prompt fragments. Identities are
`o2english_visual_identity_v1`, `ai_tech_visual_identity_v1` and
`psychology_visual_identity_v1`. The planner checks the actual frozen account and
platform against its configured domain binding; profile IDs are design identities,
not substitute account names. Only English has the accepted `o2_english` footer.
Archetypes specify eligibility, semantic selection traits, art direction, negative
constraints, role-specific compositions, visual modes and copy capacities. English keeps
six teaching positions with registered four-, five- and six-unit subsequences; other domains use these compositions by role.
There is no theme/font/component combination registry.

The current registry `ACCOUNT_PROFILES` is keyed by domain because the active
catalog has one Instagram destination per domain. The frozen recipe also records
the actual account, and recent-use history is account-scoped. This does not support
independent visual identities for several accounts in one domain, or a single
cross-domain account identity. The preserved inactive delivery catalog is not an
account-first visual registry. Generalizing ownership requires explicit
account-to-profile configuration and persisted eligibility; that work is deferred
until multiple-account visual operation is needed. No account key is invented
from a domain ID. `DEFAULT_ARCHETYPE_BY_DOMAIN` names only the safe fallback,
not the complete three-archetype set.

Infrastructure is independently versioned: `gemini_storyboard_prompt_v7` identifies
the deterministic compiler, `image_storyboard_paginated_v4` identifies technical output
geometry, and overlay IDs identify local chrome. Neither
`gemini_storyboard_prompt_v7` nor `image_storyboard_paginated_v4` is a visual template.
The former is compiler infrastructure; the latter is the technical renderer
contract. Archetype version is an integer.
The closed `visual_recipe_v5` stores account, account profile, archetype ID/version,
profile fingerprint, compiler version, renderer contract, overlay profile and
selection. The fingerprint covers all account/art-direction/archetype/overlay
configuration. Unsupported versions, mismatched identities or extra keys fail
validation. SQL freezes each recipe and binds adaptation, package and rendering
to that exact selection. Old recipes are never interpreted as v5.

## Deterministic selection

`archetype_selection.py` owns `deterministic_archetype_selector_v1`. It reads only
canonical domain fields, examples and key points; adaptation has not run yet.
Field-aware lexical signals and bounded list counts score three registered
candidates. Each signal counts once (weights 4/3/3); baseline fit is 5 and a
specialized candidate is eligible only at fit 6 or above. No recognized specialized
fit means baseline fallback. The explicit rules cover human/dialogue/context vs
usage distinctions/abstraction; product capabilities/use cases vs mechanisms and
component flows; social reactions/scenarios vs cognition and alternative explanations.
These are deterministic heuristics, not a model's semantic judgement; unfamiliar
wording may fall back to the baseline.

The planner reads the latest eight committed selections for the same Instagram
account, newest recipe ID first. Each prior use costs 0.25, capped at 1.0 per
candidate. Selection maximizes fit minus penalty; ties prefer the safe baseline,
then lexical archetype ID. Thus close fits can alternate, while a fit advantage
greater than one always wins. History counts committed plans, including plans whose
adaptation or rendering later fails; it does not claim publication occurred.
History read, selection, immutable recipe insertion and adaptation handoff share
one SQLite write transaction, so concurrent planners observe committed predecessors.

Provenance preserves the canonical hash, output/binding/account/domain, selector
version, every candidate's eligibility, fit, penalty, adjusted score and reason
codes, plus exact history recipe IDs/archetypes. Selection never invokes an LLM.
Claim expiry and thread cancellation fence the whole handoff; failure creates no
partial adaptation. Retry uses the committed selection rather than selecting again.

Unsupported domain/account/format planning fails before adaptation. Unsupported
render pairs are blocked before an image call. Invalid copy or cues fail before
paid image generation. No automatic visual fallback exists.

## Gemini designer review rendering

`storyboard_plan_v4` is an immutable persisted boundary after adaptation. A
StoryboardPlanRun claims a ContentPackage; its fenced transaction commits the plan
and one RenderRun. The plan freezes package/output/recipe lineage, total slide count,
planner version and ordered boards. No provider chooses pagination. Each board
contains index, rows, columns, capacity, inclusive slide range, explicit slide
indices, `provider_aspect_ratio`, `slide_aspect_ratio`, `final_width`,
`final_height` and split strategy. There is no ambiguous `aspect_ratio` field.

Content pagination is resolved before adaptation: English has 4–6 ordered units;
AI/Tech and Psychology have 4–14 (normally 4–8). Copy capacities and role grammar
belong to [content production](content-production.md). Render pagination groups
those immutable units into calls; it never changes the ContentPackage, claims,
slide count or order. Six English slides can use 6, 4+2, 2+4, 2+2+2 or singleton
boards. Gemini selects neither capacities, grids, ratios nor split strategy.

`render_text_policy.py` owns `rendered_text_load_v2` and the separate
`render_text_calibration_v2` policy. Measurement counts exact final title/body
Unicode code points including whitespace, whitespace-separated words, nonempty
logical lines and nonempty title/body regions. It performs no normalization or
layout inference. It excludes locally rendered overlays, caption, cues and art
direction. Each slide records title/body characters and words, title/body lines,
total characters/words/lines/regions, and longest-line characters/words. Each
candidate board aggregates title/body, total characters/words/lines/regions and
longest-line metrics, plus corresponding per-slide maxima. Logical lines are not
predicted visual wraps.

The provisional calibration defaults are centralized in that module:

| Board capacity | Board words / characters / lines | Per-slide words / characters / lines |
| --- | --- | --- |
| 1 | 80 / 720 / 7 | 80 / 720 / 7 |
| 2 | 110 / 1000 / 14 | 80 / 720 / 7 |
| 4 | 100 / 720 / 22 | 40 / 360 / 6 |
| 6 | 110 / 800 / 26 | 35 / 240 / 5 |

Each slide allows two text regions; board regions are twice capacity. These are
**calibration defaults, not proven Gemini limits**. Sparse accepted fixtures have
roughly 80–110 total words; the retained denser English sample has 160 words,
including a 33-word dialogue slide. The policy keeps sparse six-panel calls
possible while exercising splitting for denser copy. Larger per-slide allowances
on two-panel/singleton calls preserve legitimate dialogue, examples and
qualification without deleting words. They do not relax adaptation copy policy.

`text_load_contiguous_v2` exhaustively searches the small contiguous partition
space (at most 14 slides) using capacities 6, 4, 2, 1. It rejects candidates that
exceed any per-slide or aggregate budget, minimizes call count, then minimizes
the maximum board density. Density is the maximum of aggregate word/character
utilization, title and longest-line utilization, and each slide's equivalent
metrics. Fractions compare exactly; ties prefer lexicographically larger capacity
sequences. Line and region counts are hard gates, not density terms. No remaining-slide greedy exception or
special eight-slide rule exists. If even singleton boards cannot fit, planning
fails before image calls; copy is never truncated or silently reauthored.

Each selected board persists measurements, measurement/policy versions, exact
budget snapshot, rational density and planning mode inside immutable `boards_json`.
The complete plan is also in `render_manifest_v2` and acceptance artifacts.
Changing measurement or thresholds requires a new version; old evidence is not
reinterpreted. Explicit acceptance-only forced partitions persist
`forced_fidelity_experiment_v1` and every budget violation. They can compare an
over-budget strategy but do not bypass adaptation, geometry, ledger or review
gates. Normal workers always use automatic packing.

Provider board shape and final slide shape are separate contracts. The planner
uses this closed mapping (columns × rows), never a ratio derived from final cells:

| Capacity | Grid | `provider_aspect_ratio` |
| --- | --- | --- |
| 1 | 1×1 | 4:5 |
| 2 | 2×1 | 3:2 |
| 4 | 2×2 | 4:5 |
| 6 | 3×2 | 5:4 |

The shared Gemini adapter owns the supported subset (4:5, 3:2, 5:4); planner,
plan validation and transport reject unsupported values before any paid call.
Every board freezes the same Instagram carousel output profile:
`slide_aspect_ratio="4:5"`, `final_width=1080`, `final_height=1350`. All final
slides in a carousel have identical dimensions, even when its raw boards use
different provider ratios. Packing and global slide ordering are unchanged.

The compiler validates the board spec against the deterministic plan and enumerates
only that board's exact text, global slide ordinals and local row-major panel order.
It supplies the exact provider ratio, rows/columns, equal panels, edge-to-edge
contact, no margins/gutters/borders/overlap or additional text. It calls a generic
board a contact sheet of final slide designs, not a storyboard: every final cell has
zero internal subdivisions and is one continuous composition. It explicitly forbids
independent framed scenes, split screens, mini-storyboards, before/after canvases,
comic panels and nested slide frames while allowing several elements in one coherent
composition. Curated archetypes use the same distinction; their composition prose no
longer implies paired independent cuts. It distinguishes
raw panels from final slides and keeps titles, bodies, faces, diagrams and meaningful
visuals away from extreme panel edges to allow center-fit cropping. Exact supplied
text is serialized last; the model must not omit, summarize or paraphrase it.

The image adapter requests the planned provider ratio and configured image size
(default 2K), one provider call per board attempt with SDK retries disabled and no references.
The shared extraction path accepts one PNG/JPEG, at most 40 MB / 40 million
pixels, and at least 200×250 pixels per extracted cell. The returned width/height
ratio may differ by at most **2% relative** from the requested provider ratio.
Pixel rounding need not be divisible by the grid. Invalid encodings and unsafe
image sizes are terminal; insufficient cell dimensions and materially wrong
provider ratios are structurally unusable outputs.

`expected_grid_v2` validates whether the planner's exact cells can be extracted.
It never infers another grid or counts arbitrary lines across the artwork. Each
expected internal boundary has a search window of ±12% of one ideal cell's
width/height. Within it, near-full-span transitions or narrow border-connected
background gutters can adjust the split. Unrelated decorative lines outside those
windows do not participate. Small reliable outer margins (at most 6% per edge)
can be removed. Weak evidence uses rounded deterministic expected geometry;
ambiguous artwork is not grounds for inventing extra rows/columns. Singletons
bypass seam detection entirely. Evidence records windows, selected seams,
extraction rectangles and the expected layout. This is not semantic validation or
OCR: text quality and content near crop edges still require human review.

`equal_grid_then_fit_4x5_v1` consumes those same validated rectangles in planned
row-major order. Every extracted cell uses `ImageOps.fit`, Lanczos and center
`(0.5, 0.5)` to produce **1080×1350**, preserving proportion rather than stretching.
The immutable split-strategy identifier continues to designate planner-owned
cell extraction and final normalization; the manifest's extraction evidence
identifies the deterministic seam implementation.

English uses the same persisted multi-board execution and manifest as other
domains. A selected six-panel English board alone retains `english_accepted_v1`:
5:4 request, accepted adaptive margin/gutter detection and recorded equal-grid
fallback. `expression_breakdown_v1` still uses
`_build_accepted_expression_breakdown_prompt` and
`EXPRESSION_BREAKDOWN_ACCEPTED_PROMPT_PREFIX_V1` for that board; its accepted
single-board prompt and overlay pixel hashes are unchanged. Other English board
capacities use the shared equal-grid/center-fit contract. Compatibility is in
prompt compilation and splitting, not a second planner or renderer.

All boards of a multi-board carousel receive the same frozen account identity,
art direction, negative constraints and carousel visual contract. Generic compiler
branches now share one geometry/identity path for every capacity. Only assigned
slides and translated semantic cues (emphasis/participant count) appear, with exact
copy last. Internal claim IDs, capacity serialization, account IDs and profile
fingerprints are excluded. The accepted six-panel breakdown branch retains its
exact historical prompt bytes, including its optional cue representation. No reference-image chaining is implemented.

Pillow adds transparent local chrome after splitting. English retains labels,
`o2_english` branding and seeded CTA rotation. Four/five-slide content selects the
matching semantic header positions; six-slide overlay pixels remain unchanged. Dynamic domains use the
actual unit role for header labels (domain hook, EXPLAINED, EXAMPLE, TAKEAWAY),
no footer brand, and global slide counters. The curated eight-phrase CTA pool is
sampled without replacement initially; longer carousels may reuse phrases without
adjacent repetition. The final slide has no next-slide cue. Font, geometry and
opacity remain shared. Dynamic overlay versions are
`ai_tech_transparent_chrome_v2` and `psychology_transparent_chrome_v2`.

A RenderRun coordinates existing `render_board_units`, `render_board_attempts`
and `render_units`. The initial request uses the planned composite. A genuine
structural failure creates one child with `lineage_kind=structural_retry`, the
same frozen geometry and reinforced prompt. If that request also produces an
unusable composite, only its slide range becomes singleton fallback children.
The parent is `split` (superseded by execution children); the immutable plan is
unchanged. A singleton may receive one reinforced structural request but cannot
split further. No invalid composite loops indefinitely.

Each logical request (initial, reinforced or fallback) independently allows three
**total provider attempts**, including the initial call. Provider retries retain
identical prompt/geometry and never consume the structural transition. The
[shared retry policy](reliability.md#gemini-accounting) owns error classes and
backoff. A pending board's latest attempt diagnostic records its UTC retry time.
The coordinator continues other eligible boards before releasing its claim to
`retry_wait`; terminal or ambiguous boards likewise do not abort siblings.
Actual budget admission remains mandatory for every new provider attempt.

Attempts progress from `started` (requested) through `result_json.stage` values
`generated`, `validated`, `extracted`, then `succeeded`. Raw checkpoints carry
hash/media/usage evidence before local extraction. Final slide checkpoints commit
per successful board immediately, independently of final review promotion.
Completed slides are never regenerated. After an expired coordinator lease,
verified generated bytes can resume local processing under the same attempt and
invocation without another reservation or paid call. Interrupted calls without a
durable generated result become `ambiguous`; only their own range requires
operator attention while pending siblings continue. Checkpoint hashes must match.

Daily budget refusals defer pending work even after other slides completed;
job-cap exhaustion remains terminal. Neither refusal is a paid attempt. Provider
retry exhaustion, non-retryable provider errors and local processing failures
retain their evidence and stop only the affected board. All final slides must
complete before assets are promoted and one ReviewRequest commits. The dashboard
reads completed slide counts, never mere provider activity, to describe partial
progress. Normal production remains cost-aware composite generation, not per-slide
calls; singletons are exceptional fallback or explicitly planned small remainders.

The renderer reads the committed plan before calling the compiler. Raw PNG/JPEG
boards retain their provider bytes and file types. Manifest provenance links every
final ordinal to its board, cell, source rectangle, invocation, filename and hash;
board records include grid/capacity, provider ratio, final slide ratio/dimensions,
split strategy, text-load/policy evidence, structural evidence, prompt hash, raw
hash/size/media, raw dimensions, source rectangles and provider-call latency in milliseconds.
Split metadata names `ImageOps.fit`, Lanczos, center `(0.5, 0.5)` and final dimensions;
source rectangles describe the recovered planned cells before normalization. The
manifest also freezes StoryboardPlan ID/content, recipe/profile identity, compiler,
renderer, selection and overlay provenance. All assets and one ReviewRequest commit
only after the full ordered set succeeds. The atomic-promotion temporary directory is
removed on failure, while durable raw/slide checkpoints remain as local QA and
recovery evidence; model accounting remains. Prompts are hashed, never written to
diagnostic logs.

The dashboard exposes plan/failure progress, current render-board states and recent
safe attempt diagnostics, alongside expandable slide count, board count, layouts and
ranges, and all ordered final review slides. It reads persisted evidence
only. Model-rendered spelling, meaning, caveat quality and aesthetics still require
human review; capacity and reference checks do not prove semantic fidelity.
Local font selection and the preserved delivery approval contract belong to
[configuration](configuration.md#preserved-production-configuration).


## Archived deterministic visual library

The former generic HTML/Playwright library, gallery tooling, assets and historical
tests are retained only under `archive/deterministic_visual_library/`. It is not
on an active import path and has no operator command, selector, renderer or
fallback. Its archived material is reference-only future work; restoring it
requires a deliberate new contract and implementation.

The dashboard serves review assets only after path, length and hash validation.
R2 is downstream staging, never a renderer input or canonical asset store.
