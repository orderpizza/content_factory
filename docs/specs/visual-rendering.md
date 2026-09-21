# Visual Rendering Specification

**Document role:** Tier 2 current rendering contract.
**Owner:** Shared visual registry, deterministic planning, local rendering and exact asset manifests.

## Boundary

Platform adaptation freezes content, metadata, ordered visual units and bounded
semantic `visual_intent`. `src/workflow/visual_planner.py` claims VisualPlanRuns
and selects one immutable VisualRecipe from `visual_registry.py`; its successful
transaction creates the next RenderRun. `src/workflow/static_renderer.py` then
claims RenderRuns for the frozen ContentPackage and VisualRecipe. The renderer
produces assets and a ReviewRequest; it never edits creative copy or calls a
publisher. Planning-only mode composes neither visual planning nor rendering.

## Visual planning and recipes

`visual_intent_v1` is adaptation-owned and contains only primary structure,
tone, density, emphasis targets and image need. `visual_recipe_v4` is planner-
owned and records the selected `archetype_id`, optional exact `preset_id`, and
the fully resolved family, composition, theme, typography, density, semantic
component variants, decorations, image treatment and per-unit layout variants.
It also records registry release/fingerprint and source (`curated_preset`,
`curated_archetype`, `experimental_dynamic` or `fallback`). Recipes contain no
arbitrary HTML, CSS, JavaScript, SVG, pixels, colors, fonts, font paths or
remote URLs.

The version-controlled registry has four distinct layers. A **primitive** is a
reusable token or renderer part (theme, typography, component, decoration or
image treatment). A **family** classifies a semantic layout capability. An
**archetype** is the curated coherent grammar that relates one family to a small
set of compositions and explicitly permitted variants. A **preset** is one exact
known-good resolution of an archetype. The VisualRecipe is the immutable result
of choosing one of those systems for one ContentPackage.

The registry implements eight reusable families—editorial, dialogue, comparison,
cards, process, scenario, data and quote—alongside four intentional typography
systems, original solid/gradient/geometric backgrounds and semantic components.
The first reference-inspired shared visual library is
`vocab_card_minimal_v1`, `editorial_bold_cover_v1`,
`comparison_cover_bold_v1`, `phrase_sheet_v1`,
`question_pattern_sheet_v1`, `vocab_serif_elegant_v1`,
`dialogue_modern_v1`, `scenario_explainer_v1` and `process_steps_v1`.
`expression_breakdown_v1` is a shared, English-pilot Instagram capability with
a deliberately fixed six-slide grammar: `hook_hero`, `meaning_definition`,
`use_case_checklist`, `example_cards`, `dialogue_bubbles` and
`takeaway_summary`. It is registered as **tested**, not curated, until human
inspection accepts its gallery output.
English is the pilot affinity, not an owner: every archetype remains selectable
by compatible non-English domains. Granular primitives remain authoring/building
blocks; production planning does not treat them as a Cartesian product.

The deterministic planner first filters compatible archetypes by platform, unit
count, density, image need, brand and lifecycle policy. It scores semantic fit,
domain affinity, archetype maturity and soft recent
archetype/preset/theme/composition penalties scoped to platform/account. It
selects an archetype or exact preset, then resolves only that archetype's
approved knobs. Semantic suitability and maturity remain stronger than diversity;
no random selection is used.

Production admits a complete resolved recipe only when its archetype,
composition, theme, typography, selected component variants, decorations and
image treatment are all curated. `experimental_dynamic` is preview/authoring
only. The first-wave archetypes above, except `expression_breakdown_v1`, are
curated: each has a distinct renderer layout and representative gallery fixture.
`category_badge_minimal_v1` is an
experimental preview-only scaffold. Image-led cards remain deferred because the
renderer has no licensed/local image-asset strategy. Deprecated definitions are
excluded from new selection while immutable historical recipes remain inspectable.

Unit layouts are recipe-owned and role-aware. The planner maps each frozen
`hook`, `explanation`, `example` or `takeaway` unit to an archetype-registered
variant. The renderer checks that mapping before rendering; adaptation cannot
select a layout, CSS or HTML.

`expression_breakdown_v1` additionally enforces the ordered role sequence
`hook`, `explanation`, `explanation`, `example`, `example`, `takeaway` and
bounded copy capacities. These bounds are intentional readability gates rather
than a request to progressively shrink type: headlines select one of the fixed
`headline_xl`, `headline_l` or `headline_m` scales from word/character counts.
The archetype uses a controlled six-palette sequence, not random per-slide
colors, and fixed spacing tokens in its renderer primitives.

## Local visual assets

The expression dialogue uses only local approved avatars described by
`assets/visual/avatars/manifest.json`. User-provided `speaker_01.png` through
`speaker_06.png` may be dropped into that directory without code changes; each
must be a transparent, square-ish PNG with no baked halo, label or logo. The
renderer supplies the color-controlled halo. Development and gallery renders
use deterministic initial placeholders when the two required dialogue avatars
are absent. Production rejects a required missing, symlinked, non-PNG or
out-of-root avatar. When real avatars affect bytes, the render manifest records
asset ID, repository-relative path and SHA-256.

The source-controlled local SVG icon set covers lightbulb, check, target, pin
and arrow-right. Marker highlights, underline swashes, accent rays, badges,
cards, bubbles and halos are code-rendered original primitives; no third-party
screenshots, templates, logos or remote assets are included.

Domain policy is preference only: English may rank dialogue highly, while finance
may rank comparison/data highly; neither owns a family. Platform policy is
independent, so sibling Instagram and X packages can select different recipes.
Source-controlled brand/account policies are an additional eligibility layer:
they can constrain the shared pool's themes, typography, decorations and footer
treatment without duplicating a visual family. The current default policy is
intentionally neutral, ready for account-specific policies when brands exist.
Explicit user preferences are not currently modeled as a separate brief field;
when they become a bounded downstream input they must outrank diversity but not
compatibility or production lifecycle gates.

## Profiles and renderer dispatch

| Profile | Dimensions | Units |
| --- | --- | --- |
| `static_instagram_review_v1` | 1080×1350 | 5–8 |
| `static_instagram_delivery_v1` | 1080×1350 | 5–8 |
| `static_x_review_v1` | 1200×675 | 1 |
| `static_x_delivery_v1` | 1200×675 | 1 |

The initial dispatcher supports the registered `html_playwright_v1` engine.
It resolves recipe IDs to deterministic design tokens and applies reusable
title, eyebrow, definition-card, highlight-strip, phrase-group, speech-bubble,
comparison-column, scenario-panel, step and footer primitives; the renderer does
not accept low-level adaptation instructions. Future SVG/chart engines can register an engine without changing
the ContentPackage → VisualPlanRun → VisualRecipe → RenderRun boundary.

Review mode uses local system fonts and is not delivery-ready. Production mode loads the approved
local font, verifies its exact hash and embeds its bytes; it records profile,
template, font, Playwright/browser and Pillow identities in the manifest.

## Execution and assets

Playwright Chromium loads local generated HTML, waits for fonts, verifies
bounded layout and produces PNG previews. Pillow converts exact local JPEG
delivery bytes. The renderer validates geometry, encoding, byte limits, ordered
counts and hashes. A layout overflow fails the run rather than truncating copy
or shrinking it to fit.

Each unit yields `preview_html`, `preview_png` and `delivery_jpeg`. Output is
written into a run-specific temporary directory, fsynced and promoted; successful
finalization atomically persists manifest, asset rows and an exact review request.
Uncommitted promoted output is quarantined and audited, not silently reused or
overwritten. Stale claims cannot create reviews. Manifests retain the recipe hash
and registry release beside profile/template/font/browser identities.

## Explicit fallback

If actual layout overflow occurs before review, the failed RenderRun can create a
new pending VisualPlanRun linked to the failed recipe. The planner follows the
registered archetype fallback chain (for example dialogue modern → editorial
clean) and commits a new immutable fallback recipe
and RenderRun. It never mutates the original recipe. No fallback may run after a
ReviewRequest exists; any post-review redesign needs a new recipe, render and
review request.

The dashboard serves stored assets only after path, length and hash validation.
Human approval refers to those bytes. R2 is delivery staging, not a renderer
input or canonical asset store. Posting cannot regenerate or modify any asset.

## Quality and reproducibility

Frozen package and recipe input, registry fingerprint, and recorded
runtime/font/template fingerprints make the
render auditable. Byte-for-byte reproduction across different browser or font
versions is not assumed. Human quality review remains required for typography,
claims, contrast and editorial usefulness. The first-wave layouts are text-led;
image, licensed-asset, chart and SVG rendering remain deferred. Offline tests
cover both platform geometries, malformed specs, overflow and immutable package
preservation.

See [platform outputs](platform-outputs.md), [content production](content-production.md)
and [reliability](reliability.md). Visual admin tooling, LLM candidate selection,
image acquisition/generation, chart/SVG engines and qualitative design evaluation
remain future work; new capabilities should be registered rather than added as
hidden per-domain renderers.

## Visual-library growth

The intended authoring flow is: analyze a visually appealing reference,
decompose it into reusable primitives, implement any missing renderer primitive,
create or extend an archetype, render representative examples, obtain human
review, mark it tested, and mark it curated only after acceptance. Contributors
should decide whether a reference is a new archetype or a variation of one, and
whether it truly needs a new composition, component, theme, typography treatment
or decoration. A reference is not automatically a new renderer/template.

## Offline gallery

`scripts/render_visual_gallery.py` renders original representative fixture copy
through the renderer HTML path without a database, Gemini, credentials or network
access. Its default ignored output root is `data/artifacts/visual-gallery`; each
archetype directory includes named HTML and PNG units. Gallery output is design
verification only, never review or production persistence. Human visual
inspection of this gallery is required before carrying the pilot language to
other domains.

Render just the expression pilot with:

```text
.venv/bin/python scripts/render_visual_gallery.py --archetype expression_breakdown_v1
```

It writes `slide-01-hook_hero.png` through `slide-06-takeaway_summary.png`
under `data/artifacts/visual-gallery/expression_breakdown_v1/`.
