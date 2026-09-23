# Visual rendering

**Owner:** Active Gemini review rendering, fixed domain profiles and local
post-image processing.

## Active boundary

Adaptation freezes copy, claim mappings, ordered semantic units and bounded
`visual_intent`. VisualPlanRun selects an immutable VisualRecipe and atomically
creates RenderRun. The active `DispatchVisualRenderer` inspects persisted job
domain and recipe before any image call. Supported pairs are exclusively:

| Domain | Archetype | Prompt version |
| --- | --- | --- |
| `english` | `expression_breakdown_v1` | `gemini_carousel_storyboard_v1` |
| `ai_tech` | `ai_tech_explainer_v1` | `gemini_ai_tech_storyboard_v1` |
| `psychology` | `psychology_explainer_v1` | `gemini_psychology_storyboard_v1` |

All three domains use explicit deterministic domain/archetype compatibility,
recorded as `explicit_domain_archetype_v1` selection provenance. The active
profile contract exposes exactly one profile per domain; it has no selector,
generic registry archetypes or fallback rules. The narrow AI/Tech and Psychology
six-unit validators run during adaptation, planning and image prompt construction;
English retains its accepted six-slide expression validator. The [package contract](content-production.md#instagram-package-contract)
owns the role sequences, semantic purposes and copy bounds. The persisted recipe
envelope remains immutable for lineage, but records the fixed active profile rather
than a reusable visual-library recipe. No recipe or canonical schema changes.

Unsupported domain/archetype combinations end RenderRun in `blocked` with a
format-specific reason. Invalid supported-domain package shapes fail before an
image call. No HTML fallback, model invocation, asset or ReviewRequest is created
for an unsupported combination. Blocked runs are not polled again. Thread
cancellation and live claim fencing still apply. The dashboard shows status and
reason beside generation and adaptation progress.

`run_workflow.py --gemini --review-preview` composes only Gemini rendering.
The active strategy is Gemini images followed by small deterministic local
processing. Shared recipe validation and atomic asset lifecycle are retained to
protect all three paths without changing the accepted English mechanics.

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

AI/Tech has a dedicated clean, credible technology editorial brief: interface
cards, annotated diagrams, processes, practical examples and prominent limitations.
It avoids robot/hologram/cyberpunk clichés and automatic provider branding.
Psychology has a warm, calm, human-centered brief: relatable scenarios, possible
mechanisms and practical responses. It preserves observation/inference/alternative
explanation distinctions and final qualification, avoiding diagnostic or dark
psychology imagery. Neither profile asks the image model to research, verify or
improve claims. Supplied titles and bodies must be rendered exactly, with no
rewriting, omission, summary or invented text.

The accepted English prompt constants remain unchanged. A frozen SHA-256 test
protects the complete prompt for the known expression fixture. Separate overlay
pixel hashes with a fixed bundled font protect all six English slide overlays.

The isolated Vertex adapter makes one 5:4, 2K image request per supported carousel
by default, with SDK retries disabled. Its model and image size remain
environment-configurable, and the requested size must be supported by the selected
model. It sends only the storyboard prompt, with no image parts;
[the SDK documentation](https://googleapis.github.io/python-genai/) describes that
transport. Prompts forbid branding, counters, headers, footers and category or
semantic-role labels; the supplied title and body are the only model-rendered
text. Local processing owns all chrome and reserves the top 10%, bottom 14% and
generous side margins in every panel. Each storyboard output
must be a single PNG/JPEG, at least 600×480, at most 40 million pixels/40 MB and
within 0.04 of the 5:4 aspect ratio. Border-background and projection analysis
finds panel bounds without assuming an exact canvas color; an auditable equal-grid
fallback is used only when that analysis lacks confidence. Each crop is
Lanczos-resized exactly once to 1080×1350. These checks reject invalid image
data/geometry, not inaccurate words or poor visual design. Exact model-rendered
text and design quality require human review.

After splitting, Pillow applies deterministic transparent header/category and
page-counter text on a single subdued RGBA layer. English retains its
lower-left `o2_english` brand and existing expression labels; AI/Tech and Psychology
omit footer brand text and never display synthetic account IDs. Header and footer
use the same local font, size, color and opacity; there
are no bars, panels, strokes, outlines, shadows or glows. Slides 1–5 place their
CTA and matching arrow on the same footer baseline; a deterministic render-seeded
selection rotates five non-repeating phrases from the curated CTA set, while slide
6 receives no next-slide cue. English retains seed namespace
`expression-footer-cta-v1` and overlay version `expression_transparent_chrome_v2`.
The new domains use separate `ai-tech-footer-cta-v1` / `psychology-footer-cta-v1`
namespaces and `ai_tech_transparent_chrome_v1` / `psychology_transparent_chrome_v1`
overlay versions with the same font, geometry, color, opacity, CTA pool and arrow.

AI/Tech overlay labels are AI / TECH, WHAT CHANGED, WHY IT MATTERS, USE CASE,
LIMITS, TAKEAWAY. Psychology labels are PSYCHOLOGY, THE CONCEPT, WHY IT MAY HAPPEN,
EXAMPLE, WHAT HELPS, TAKEAWAY. These complement the exact supplied slide copy.

The six processed `preview_png` assets are the
exact dashboard review bytes. The raw storyboard is retained unchanged in its
provider PNG/JPEG format as a traceability/debug artifact only, not a review asset
or dashboard contact sheet. The image renderer creates review assets only.

The manifest records domain/archetype IDs, engine/model, prompt and overlay versions, storyboard grid,
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


## Archived deterministic visual library

The former generic HTML/Playwright library, gallery tooling, assets and historical
tests are retained only under `archive/deterministic_visual_library/`. It is not
on an active import path and has no operator command, selector, renderer or
fallback. Its archived material is reference-only future work; restoring it
requires a deliberate new contract and implementation.

The dashboard serves review assets only after path, length and hash validation.
R2 is downstream staging, never a renderer input or canonical asset store.
