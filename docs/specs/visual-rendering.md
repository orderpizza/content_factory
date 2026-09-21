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
tone, density, emphasis targets and image need. `visual_recipe_v1` is planner-
owned and resolves those requirements to registered family, composition, theme,
typography, density, semantic component variants, decorations, image treatment
and per-unit layout variants. Recipes also record their registry release and
fingerprint, source (`preset`, `dynamic` or `fallback`) and resolved choices.
They contain no arbitrary HTML, CSS, JavaScript, SVG, pixels, colors, fonts,
font paths or remote URLs.

The version-controlled registry implements eight reusable families: editorial,
dialogue, comparison, cards, process, scenario, data and quote. It currently
contains 18 HTML/Playwright compositions, seven themes, four typography systems,
semantic component variants, four decorations, image-treatment extension points,
and curated presets. Definitions declare engine, platform, density, lifecycle,
feature and fallback compatibility; this is a graph of supported capabilities,
not a Cartesian product or a domain-owned template directory.

The deterministic planner filters by platform, unit count, density, image need,
renderer and lifecycle eligibility. It then scores semantic fit, domain affinity,
curation quality and soft recent-use penalties scoped to platform/account.
Semantic suitability remains stronger than diversity. Production selects only
curated definitions; experimental definitions are unavailable there, and
deprecated definitions are excluded from new selection while old immutable
recipes remain inspectable.

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
composition primitives; the renderer does not accept low-level adaptation
instructions. Future SVG/chart engines can register an engine without changing
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
registered composition fallback chain (for example dialogue bubbles → stacked
transcript → editorial title/body) and commits a new immutable fallback recipe
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
claims, contrast and editorial usefulness. Offline tests cover both platform
geometries, malformed specs, overflow and immutable package preservation.

See [platform outputs](platform-outputs.md), [content production](content-production.md)
and [reliability](reliability.md). Visual admin tooling, LLM candidate selection,
image acquisition/generation, chart/SVG engines and qualitative design evaluation
remain future work; new capabilities should be registered rather than added as
hidden per-domain renderers.
