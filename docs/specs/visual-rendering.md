# Visual Rendering Specification

**Document role:** Tier 2 current rendering contract.
**Owner:** Shared local profiles, HTML/CSS templates and exact asset manifests.

## Boundary

`src/workflow/static_renderer.py` claims RenderRuns for frozen ContentPackages.
Adaptation owns content, metadata and visual specification. The renderer produces
assets and a ReviewRequest; it never edits creative copy or calls a publisher.
Planning-only mode does not compose a renderer.

## Profiles and payload

The closed `static_social_visual_v1` payload names `html_playwright_v1`,
profile, dimensions, ordered units and review-only status. Each unit contains
role, title, body and claim IDs; roles are hook, explanation, example or takeaway.
Arbitrary model-authored HTML, CSS or remote asset URLs are not accepted.

| Profile | Dimensions | Units |
| --- | --- | --- |
| `static_instagram_review_v1` | 1080×1350 | 5–8 |
| `static_instagram_delivery_v1` | 1080×1350 | 5–8 |
| `static_x_review_v1` | 1200×675 | 1 |
| `static_x_delivery_v1` | 1200×675 | 1 |

One shared escaped HTML/CSS template supports the two canvases. Review mode uses
local system fonts and is not delivery-ready. Production mode loads the approved
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
overwritten. Stale claims cannot create reviews.

The dashboard serves stored assets only after path, length and hash validation.
Human approval refers to those bytes. R2 is delivery staging, not a renderer
input or canonical asset store. Posting cannot regenerate or modify any asset.

## Quality and reproducibility

Frozen package input and recorded runtime/font/template fingerprints make the
render auditable. Byte-for-byte reproduction across different browser or font
versions is not assumed. Human quality review remains required for typography,
claims, contrast and editorial usefulness. Offline tests cover both platform
geometries, malformed specs, overflow and immutable package preservation.

See [platform outputs](platform-outputs.md), [content production](content-production.md)
and [reliability](reliability.md). New visual families and quality evaluation
belong in [remaining work](../plans/target-implementation.md), not hidden
per-domain renderers.
