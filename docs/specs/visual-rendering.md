# Visual rendering

**Owner:** Active Gemini review rendering, frozen recipes and the preserved
inactive deterministic visual library.

## Active boundary

Adaptation freezes copy, claim mappings, ordered semantic units and bounded
`visual_intent`. VisualPlanRun selects an immutable VisualRecipe and atomically
creates RenderRun. The active `DispatchVisualRenderer` inspects persisted job
domain and recipe before any image call. Only English `expression_breakdown_v1`
is supported. Its six roles and layout sequence are preserved.

AI/Tech and Psychology complete adaptation, then VisualPlanRun
ends in `blocked` before consulting inactive HTML library capabilities, with `failure_reason` containing
“Gemini visual renderer not implemented for this domain.” This column is reused
as the safe explanatory reason; `blocked` is a capability stop, not `failed`.
Unsupported English formats similarly stop with a format-specific reason.
No model invocation, HTML fallback, asset or ReviewRequest is created for a
blocked run. Existing RenderRuns are also fenced by a domain check and become
blocked if claimed directly. Blocked runs are not polled again. Thread cancellation and live
claim fencing still apply. The dashboard shows status and reason on job/thread
pages beside generation and adaptation progress.

`run_workflow.py --gemini --review-preview` composes only Gemini rendering.
The active strategy is Gemini images followed by small deterministic local
processing. Shared recipe validation and atomic asset lifecycle are retained to
protect the accepted English path.

## Gemini designer review rendering

`GeminiImageRenderer` generates one 5:4 storyboard image containing six clearly
separated portrait panels in a three-column by two-row order. It sends no reference
images. The renderer adaptively finds the border-connected background family,
trims its outer frame, and identifies two vertical and one horizontal
low-information gutter seams. It then crops the six panels left-to-right,
top-to-bottom and center-fits each once to 1080×1350. If confidence checks cannot
distinguish margins or gutters, it records an equal-grid fallback rather than
failing a valid storyboard. Gemini retains creative control within each panel.

Renderer-owned prompts interpret `expression_breakdown_v1` as hook,
meaning/definition, use cases, examples, short dialogue and takeaway. The one
storyboard prompt includes every exact title/body, semantic role and role-sensitive
direction. It prioritizes instructional clarity over visual delight: each panel has
one obvious reading order, clear title/explanation/visual separation, readable body
text and supporting visuals that do not compete with teaching. It rejects poster
collages, decorative text overlap, excessive accents, cramped layouts and visual
noise. Recipe composition, theme, typography tokens and component coordinates never
enter the prompt. Existing package/recipe validity gates still apply; adaptation
does not author image prompts.

The isolated Vertex adapter makes one 5:4, 2K image request per supported carousel
by default, with SDK retries disabled. Its model and image size remain
environment-configurable, and the requested size must be supported by the selected
model. It sends only the storyboard prompt, with no image parts;
[the SDK documentation](https://googleapis.github.io/python-genai/) describes that
transport. Prompts forbid branding, counters and footer CTAs and reserve the top
10%, bottom 14% and generous side margins in every panel. Each storyboard output
must be a single PNG/JPEG, at least 600×480, at most 40 million pixels/40 MB and
within 0.04 of the 5:4 aspect ratio. Border-background and projection analysis
finds panel bounds without assuming an exact canvas color; an auditable equal-grid
fallback is used only when that analysis lacks confidence. Each crop is
Lanczos-resized exactly once to 1080×1350. These checks reject invalid image
data/geometry, not inaccurate words or poor visual design. Exact model-rendered
text and design quality require human review.

After splitting, Pillow applies deterministic transparent header/category and
page-counter text plus a lower-left `o2_english` brand on a single subdued RGBA
layer. Header and footer use the same local font, size, color and opacity; there
are no bars, panels, strokes, outlines, shadows or glows. Slides 1–5 place their
CTA and matching arrow on the same footer baseline; a deterministic render-seeded
selection rotates five non-repeating phrases from the curated CTA set, while slide
6 receives no next-slide cue. The six processed `preview_png` assets are the
exact dashboard review bytes. The raw storyboard is retained unchanged in its
provider PNG/JPEG format as a traceability/debug artifact only, not a review asset
or dashboard contact sheet. The image renderer creates review assets only.

The manifest records engine/model, prompt and overlay versions, storyboard grid,
prompt hash, one invocation ID, raw storyboard filename/MIME/extension/bytes/hash,
raw dimensions, detected outer crop, gutter seams, source rectangles, fallback
status, final filename/hash, transparent-overlay version and deterministic footer
CTA choices. Package/recipe lineage and Pillow identity remain intact. The one
invocation request hash contains the prompt only. No raw prompts enter diagnostic
logs or model ledgers. All six final assets commit with one ReviewRequest only
after complete success. Failed temporary output is removed; paid-call evidence
remains in the invocation ledger.

The one storyboard call has one admission and accounting record against the shared
daily/job limits, using image prices. A current live claim is required for the
bounded call; an expired claim cannot be revived. An interrupted carousel is never
resumed automatically. Generation, normalization or overlay failures fail the
whole render without a partial review, per-cell repair or automatic HTML fallback.
A low-confidence split alone uses the recorded equal-grid fallback. Only a daily
budget refusal before the storyboard call may defer without a provider call. Manual
refinement/review-feedback creates fresh work for a complete rerun; no in-place
render retry command is provided.


## Preserved inactive visual library

`static_renderer.py`, `visual_primitives.py`, `visual_expression.py`, the visual
registry/archetypes, local icons/avatars and useful tests remain intact as a
preserved inactive subsystem. HTML/Playwright is available to gallery/development
tooling, not as an operator workflow switch or automatic fallback.

The registry separates primitives, families, archetypes and presets. Recipes
freeze registered IDs, safe resolved variants, per-unit layouts, selection
provenance and registry fingerprints. Deterministic selection scores semantic
fit and domain affinity with bounded recent-use penalties. Library lifecycle
labels govern gallery/HTML eligibility independently of acceptance of the Gemini
English storyboard. The English archetype retains its fixed six-role grammar,
copy capacities and local avatar handling. No expansion or redesign is part of
this baseline.

The inactive HTML renderer keeps 1080×1350 Instagram profiles, overflow checks,
local fonts/assets, hashing, atomic promotion, quarantine and fallback-recipe
tests. The gallery creates no review or delivery records:

```sh
.venv/bin/python scripts/render_visual_gallery.py --archetype expression_breakdown_v1
```

Default gallery output is ignored `data/artifacts/visual-gallery`. Local avatar
instructions are in `assets/visual/avatars/manifest.json`.

The dashboard serves assets only after path, length and hash validation. Human
review refers to those exact bytes. R2 remains downstream staging, never a
renderer input or canonical asset store. [Platform outputs](platform-outputs.md)
owns adaptation; [reliability](reliability.md) owns shared budget/storage rules.
