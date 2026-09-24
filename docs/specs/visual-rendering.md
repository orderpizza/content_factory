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
six ordered positions; dynamic domains use these compositions by role.
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

Infrastructure is independently versioned: `gemini_storyboard_prompt_v4` identifies
the deterministic compiler, `image_storyboard_paginated_v2` identifies technical output
geometry, and overlay IDs identify local chrome. Neither
`gemini_storyboard_prompt_v4` nor `image_storyboard_paginated_v2` is a visual template.
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

`storyboard_plan_v2` is an immutable persisted boundary after adaptation. A
StoryboardPlanRun claims a ContentPackage; its fenced transaction commits the plan
and one RenderRun. The plan freezes package/output/recipe lineage, total slide count,
planner version and ordered boards. No provider chooses pagination. Each board
contains index, rows, columns, capacity, inclusive slide range, explicit slide
indices, `provider_aspect_ratio`, `slide_aspect_ratio`, `final_width`,
`final_height` and split strategy. There is no ambiguous `aspect_ratio` field.

All three English archetypes remain exactly six slides on one 3×2 board. All
six AI/Tech and Psychology archetypes allow 4–14 slides (normally 4–8); adaptation
capacity and role grammar are owned by [content production](content-production.md).
The finite board family is 3×2, 2×2, 2×1, 1×1 (columns × rows), capacities
6, 4, 2, 1. `balanced_eight_largest_first_v1` minimizes board count, then uses
larger capacities first, except total eight uses the explicit balanced 4+4 rule.
Examples: 4→4, 6→6, 8→4+4, 10→6+4, 12→6+6, 14→6+6+2. Slide order never changes.

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
contact, no margins/gutters/borders/overlap or additional text. It distinguishes
raw panels from final slides and keeps titles, bodies, faces, diagrams and meaningful
visuals away from extreme panel edges to allow center-fit cropping. Exact supplied
text is serialized last; the model must not omit, summarize or paraphrase it.

The image adapter requests the planned provider ratio and configured image size
(default 2K), one call per board with SDK retries disabled and no references.
The dynamic path accepts one PNG/JPEG, at most 40 MB / 40 million pixels, at least
200×250 pixels per raw cell, and dimensions exactly divisible by columns/rows.
The returned width/height ratio may differ by at most **2% relative** from the
requested provider ratio to accommodate pixel rounding. Materially wrong ratios,
non-divisible grids, small cells and invalid images fail visibly.

`equal_grid_then_fit_4x5_v1` first crops exactly the planned number of equal cells
in row-major order. Each raw cell then uses `ImageOps.fit` with Lanczos resampling
and centering `(0.5, 0.5)` to produce **1080×1350**. It crops proportionally instead
of stretching a non-4:5 cell. There is no margin inference or fallback. Raw cells
are not required to be 4:5; only final slides are. Content near edges can be cropped,
so model composition and final visual/text quality still require human review.

English is an explicit preservation exception: all three English archetypes retain
their existing 5:4 raw-board request and adaptive margin/gutter processing, with the
recorded equal-grid fallback. Their persisted plan records the 3×2 grid, provider ratio 5:4 and final slide
ratio 4:5 / 1080×1350. `english_accepted_v1` retains the accepted transport and
splitting. In particular `expression_breakdown_v1` uses
`_build_accepted_expression_breakdown_prompt` and
`EXPRESSION_BREAKDOWN_ACCEPTED_PROMPT_PREFIX_V1`; its full prompt and overlay pixel
hashes remain unchanged. This exception preserves the accepted English baseline.

Pillow adds transparent local chrome after splitting. English retains labels,
`o2_english` branding and seeded five-phrase CTA rotation. Dynamic domains use the
actual unit role for header labels (domain hook, EXPLAINED, EXAMPLE, TAKEAWAY),
no footer brand, and global slide counters. The curated eight-phrase CTA pool is
sampled without replacement initially; longer carousels may reuse phrases without
adjacent repetition. The final slide has no next-slide cue. Font, geometry and
opacity remain shared. Dynamic overlay versions are
`ai_tech_transparent_chrome_v2` and `psychology_transparent_chrome_v2`.

One RenderRun renders every board sequentially under a thirty-minute lease. Every
board has separate admission/accounting against the same daily/job limits, a unique
invocation ordinal and persisted claim version. A board starts only after all prior
boards succeeded under that same live claim. Transport uncertainty, lease loss,
invalid geometry, overlay failure or later-board budget refusal stops the whole
render with no partial ReviewRequest or automatic paid replay. Daily budget refusal
before any paid board can defer. There is no per-board resume or repair command.

The renderer reads the committed plan before calling the compiler. Raw PNG/JPEG
boards retain their provider bytes and file types. Manifest provenance links every
final ordinal to its board, cell, source rectangle, invocation, filename and hash;
board records include grid/capacity, provider ratio, final slide ratio/dimensions,
split strategy, prompt hash, raw hash/size/media, raw dimensions and source rectangles.
Split metadata names `ImageOps.fit`, Lanczos, center `(0.5, 0.5)` and final dimensions;
source rectangles describe the equal-grid cells before normalization. The
manifest also freezes StoryboardPlan ID/content, recipe/profile identity, compiler,
renderer, selection and overlay provenance. All assets and one ReviewRequest commit
only after the full ordered set succeeds. Temporary failed output is removed;
model accounting remains. Prompts are hashed, never written to diagnostic logs.

The dashboard exposes plan/failure progress, expandable slide count, board count,
layouts and ranges, and all ordered final review slides. It reads persisted evidence
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
