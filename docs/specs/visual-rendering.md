# Visual rendering

**Owner:** Account visual identity, curated archetypes, deterministic planning and
prompt compilation, and shared Gemini review rendering.

## Active boundary

```text
CanonicalContent + OutputRequest
→ VisualPlanRun → immutable VisualRecipe v5 + AdaptationRun
→ ContentPackage + RenderRun
→ deterministic PromptCompiler → Gemini storyboard → split + overlays → ReviewRequest
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
whitespace, polish and positive/negative art direction. Identities are
`o2english_visual_identity_v1`, `ai_tech_visual_identity_v1` and
`psychology_visual_identity_v1`. The planner checks the actual frozen account and
platform against its configured domain binding; profile IDs are design identities,
not substitute account names. Only English has the accepted `o2_english` footer.
Archetypes specify eligibility, semantic selection traits, art direction, negative
constraints and six ordered slide compositions, visual modes and copy capacities.
There is no theme/font/component combination registry.

Infrastructure is independently versioned: `gemini_storyboard_prompt_v2` identifies
the deterministic compiler, `image_storyboard_3x2_v1` identifies technical output
geometry, and overlay IDs identify local chrome. Archetype version is an integer.
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

`GeminiImageRenderer` generates one 5:4 storyboard image containing six clearly
separated portrait panels in a three-column by two-row order. It sends no reference
images. The renderer adaptively finds the border-connected background family,
trims its outer frame, and identifies two vertical and one horizontal
low-information gutter seams. It then crops the six panels left-to-right,
top-to-bottom and center-fits each once to 1080×1350. If confidence checks cannot
distinguish margins or gutters, it records an equal-grid fallback rather than
failing a valid storyboard. Gemini retains creative control within each panel.

The deterministic `gemini_prompt_compiler.py` is the only final prompt builder.
It loads account identity and the selected archetype's directions from
`active_visual_profiles.py` / `visual_art_direction.py`, validates copy capacity
and claim-referenced cues, and serializes geometry, account identity, archetype
and grammar, semantic cues, negative constraints and exact slide text in a stable
order. Exact text is last. The accepted English baseline deliberately retains its
original serialization and wording when cues are empty; its geometry and account
art direction are already in the accepted brief. Its frozen full-prompt hash and
six overlay pixel hashes remain unchanged. Every archetype also has an exact
prompt hash fixture including a semantic cue. AI/Tech and Psychology retain their
accepted account art direction and baseline slide directions.

The renderer contains no creative policy. It executes the compiled prompt with
one Gemini call, then processes the result. The compiler never calls a model.
No archetype-specific renderer implementation or HTML fallback exists.

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

The manifest records account profile, archetype ID/version, selector evidence, compiler version,
renderer contract, overlay profile, engine/model, storyboard grid,
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
