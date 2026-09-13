# Visual Rendering Specification

**Document role:** Tier 2 target design contract. It defines the shared visual
rendering boundary; verify implementation conformance from code and tests.
**Owner:** Renderer providers, visual profiles, template contracts, font and
asset handling, deterministic rendering, and render-quality requirements.
**Read this for:** Any visual profile, template, renderer tool/provider, font,
image asset, render validation, or output-format change. Read
[the system guide](../system.md) first, then the
[data model](data-model.md) and [reliability](reliability.md) contracts.

## Purpose and boundary

Visual Rendering is a shared local capability layer. It turns the immutable,
structured visual specification in a `ContentPackage` into reviewable and
delivery-ready visual assets for all Phase 1 domains through shared static
profiles. Domain meaning and platform composition remain upstream concerns.

```text
Output adapter (inside Adaptation Worker)
  → immutable ContentPackage + versioned visual specification
  → persisted RenderRun
  → Visual Renderer worker
  → verified RenderAsset manifest
  → human review
```

The domain pipeline owns canonical editorial meaning. The output adapter owns
platform composition, visual roles, structured bindings, and compatible profile
selection for its package. The
renderer owns the registered reusable profiles and their template
implementations, template execution, font/local-asset loading, pixel output,
and render validation. Neither component calls the other directly; `RenderRun`
and `RenderAsset` are the SQLite boundary.

The renderer never changes slide copy, captions, tags, hashtags, creative
meaning, destination, or package metadata. A visual/content change requires a
new brief revision and package; a safe technical render retry uses the same
frozen package specification.

## First renderer decision

The first supported renderer is `html_playwright_v1`:

- versioned local HTML/CSS templates receive only structured, escaped package
  content;
- local Playwright Chromium renders the template at the declared output
  dimensions; and
- it produces preview and final raster assets without an LLM, cloud rendering
  service, or third-party account.

This is an intentional continuation of the existing O2 HTML/CSS + Playwright
approach, elevated from hard-coded functions into a shared renderer boundary.
It is the default for typography-heavy static social slides because it supports
precise browser layout, colors, shapes, images, and local web fonts.

Pillow is an allowed supporting utility for deterministic image operations—for
example format conversion, resize/crop, compositing, thumbnails, and manifest
inspection. It is not the primary rich-layout/template engine.

No additional renderer provider is selected yet. A future provider (for
example, an SVG/vector or custom illustration renderer) must be
registered behind the same persisted specification and output-manifest boundary
only after its purpose, local runtime dependency, licensing, reproducibility,
and validation rules are approved. Adding one must not change the pipeline or
Posting Agent contract.

The current `--review-preview` implementation is an acceptance slice of
`html_playwright_v1`. It renders escaped fixed templates to
1080×1350 Instagram or 1200×675 X HTML/PNG/JPEG sets, verifies dimensions and
overflow, promotes a run-specific directory without overwrite, and records
browser/Pillow versions and asset hashes. Synthetic `static_*_review_v1`
profiles use system Arial and remain non-deliverable. V4 production profiles
require a regular absolute font file no larger than 20 MB, freeze its SHA-256,
verify the hash again at render, embed it in CSS, fsync promoted assets, and
quarantine failed promoted directories. The configuration command also requires
an explicit owner assertion that the current static profiles were visually
reviewed. Golden baselines and broad visual-quality acceptance remain human work.

## Core concepts

| Term | Meaning |
| --- | --- |
| **Visual profile** | A renderer-owned, pipeline-neutral, versioned visual capability: its reusable layout/design rules, palette, local fonts, spacing, safe areas, allowable assets, template family, and output defaults. A profile must be usable by any compatible pipeline; it is not defined by one pipeline. |
| **Template** | A versioned implementation within a renderer profile for one visual role. It renders structured content; it is not arbitrary model-generated HTML. |
| **Profile selection** | The output adapter's frozen mapping of its visual units to compatible registered visual profiles/templates. It may select more than one profile in one package. |
| **Visual specification** | The immutable package input naming the selected profile/template for every ordered visual unit, structured content bindings, local asset references, and required output(s). |
| **Renderer provider** | A local implementation identified by a stable versioned ID, initially `html_playwright_v1`. It executes a visual specification and returns assets/validation data. |
| **Render run** | One auditable, claimable execution record for a frozen package specification. A safe retry reuses that record and its frozen input; a separately authorized terminal rerender/recovery creates another run. Neither overwrites a prior successful run. |
| **Render manifest** | The verified ordered list of output assets and the renderer/template/font/input versions and hashes needed to identify exactly what the human reviewed. |

Every static visual unit has explicit output roles. For the initial Instagram
contract, the canonical roles are `preview_html`, `preview_png`, and
delivery-ready `delivery_jpeg`; each role has a stable ordinal. The locally
generated JPEG bytes—not a later R2 copy or adapter conversion—are the public
delivery input bound to human review.

`visual_spec_json` is fully frozen at package creation. Its generic field
grammar lives here; profile-specific tokens, template geometry, font assets,
and regression fixtures live in the versioned profile contract. The first such
legacy reference is [Editorial Clean](../profiles/editorial-clean-v1.md);
Phase 1 requires new compatible output versions before activation.

## Phase 1 static profile contract

The shared renderer remains `html_playwright_v1`: local versioned HTML/CSS +
Playwright, pinned local fonts/assets, escaped structured input, deterministic
preview and final-image output. It serves Instagram and X through distinct
compatible profile/canvas bindings, not separate domain renderers.

Each visual unit freezes ordinal, semantic role, profile/template/theme versions,
typed bindings, output dimensions/roles, and validation policy. Bindings contain
no arbitrary HTML/CSS, colors, filesystem paths, font names, or remote URLs.
The output adapter must use the exact field grammar of the selected template;
similar names such as `hook`/`hook_text` are not implicit aliases.

The previous `visual_spec_v1` and
[Editorial Clean v1](../profiles/editorial-clean-v1.md) are legacy/draft references,
not compatible new Phase 1 output contracts. Preserve their versions; define
new static profile and visual-spec versions with exact geometry, font/runtime
fingerprints, JPEG/PNG encoding, native platform byte limits, and golden fixtures
before activation. The proposed Instagram and X dimensions are owned by
[Platform outputs](platform-outputs.md); never infer platform compatibility from
the old 1080×1920 viewport.

Missing font/template/theme/asset, overflow, or incompatible output dimensions
fails the RenderRun. Substitution, shrink-to-fit, copy truncation, delivery-time
conversion, and hidden cropping are forbidden. Review receives the exact final
delivery-format bytes, plus a complete ordered manifest.

## Shared profile registry

The Visual Rendering Layer consumes the enabled, versioned profile registry
materialized from the activated configuration release.
Profiles are generic building blocks—not `o2_*` or another pipeline's private
implementation. An output binding declares the profiles it can use and its role/selection
constraints; it does not create, fork, or own a profile.

The retained reusable profile families for static educational/social content are
listed below. Their v1 IDs describe legacy capacities, not approved Phase 1
platform compatibility; select a new compatible version through the registry:

| Profile ID | Reusable purpose | Suitable visual units |
| --- | --- | --- |
| `hook_emphasis_v1` | A concise, high-emphasis text introduction with a strong visual hierarchy. | Hook, title, announcement, CTA |
| `concise_explainer_v1` | Clear teaching/explanation layout for a title plus concise supporting copy. | Definition, explanation, instruction |
| `monologue_card_v1` | A single-speaker example or quotation presented as a readable card. | Example, quote, testimonial |
| `chat_dialogue_v1` | A short two-party conversation with distinct message treatment. | Dialogue, comparison, Q&A |

These profile IDs establish reusable capabilities. Their versioned profile
contracts own palette tokens, font set, template grammar, content limits,
supported dimensions, and quality fixtures. New profiles are added to this
registry only when they represent a
reusable visual need across more than one plausible pipeline or format.

For every package, the output adapter selects only profiles registered as
compatible with its output contract/binding and records the result in the immutable visual
specification. Package creation atomically creates the first pending RenderRun
with the resolved selection. A selection change is creative/format change and
therefore requires a new package; the renderer may only retry the frozen
selection.

## Determinism, fonts, and local assets

- Templates, stylesheets, font files, and bundled visual assets are versioned
  local inputs. A production render must not depend on Google Fonts, a remote
  stylesheet, a remote image URL, or other unpinned network content.
- A specification resolves explicit profile, template, renderer, and output
  versions before a `RenderRun` is claimed. The run records their identifiers
  and hashes with the package/content hash.
- Renderer output is deterministic for the same frozen inputs and approved
  local runtime version. A renderer or template upgrade creates a new version;
  it does not silently alter historical packages or approved output.
- Any visual asset used by a template is a validated local input or a persisted
  content asset with an immutable hash. Delivery staging in R2 is not a visual
  source or canonical asset store.

## Required renderer behavior

For every claimed `RenderRun`, the renderer must:

1. load the frozen visual specification and resolve only registered local
   profile/template/provider inputs;
2. render every required ordered visual unit at its declared dimensions and
   MIME/output format;
3. create the final delivery-format derivative locally with a versioned
   deterministic converter/encoder, then validate the complete output before
   it can be exposed for review;
4. write into a run-specific temporary directory on the canonical artifact
   filesystem, verify every role/ordinal/hash, and atomically rename it to an
   immutable final directory;
5. in one SQLite transaction, persist the succeeded run, complete manifest,
   `RenderAsset` records, and exact-hash-bound `ReviewRequest`; or persist a
   safe, diagnosable failure without partial review availability; and
6. leave the `ContentPackage` unchanged.

Startup recovery follows the filesystem/SQLite protocol in
[Reliability and safety](reliability.md): abandoned temporary output is removed
only after ownership checks, while promoted output without a matching committed
run is quarantined and reconciled by run ID and hash. Existing final output is
never overwritten or accepted merely because a path exists.

The renderer validates dimensions and format, required-font availability,
complete ordered asset count, local-path/output readability, hashes, JPEG
encoder/version, and blocking layout defects. Profile contracts define the
exact validation categories and regression fixtures. The dashboard displays the
canonical final delivery assets and their stored manifest/hash validation, not a
fresh renderer preview.

## Output adapters as profile consumers

The Instagram carousel adapter maps each domain's semantic progression to
registered shared templates. The X adapter maps canonical content to one native
hook/summary card; it may reuse a suitable semantic unit without copying an
Instagram carousel wholesale. Both select and freeze profiles before rendering.

The hook, explanation, example, and dialogue families above remain reusable
design candidates; their old field/geometry versions must not be assumed to
support every new domain. A new business-risk card or finance explanation should
extend a shared typed template only when its required layout is materially new.
Do not fork a renderer per pipeline/account.

The [Platform outputs contract](platform-outputs.md) owns platform-specific
sequence and copy limits; [Domain pipelines](../pipelines/domains.md) owns
editorial meaning. Neither owns shared template implementation.

## Acceptance direction

Before a renderer/profile is enabled for public delivery, boundary tests must
show that a frozen visual specification resolves the intended local template,
produces all declared assets at the expected dimensions/format, records exact
versions and hashes, rejects blocking output defects, passes its profile's
visual-regression protocol, and leaves package creative/metadata unchanged.

## Related contracts

- [System guide](../system.md)
- [Data model](data-model.md)
- [Reliability and safety](reliability.md)
- [Worker runtime](runtime.md)
- [Platform outputs](platform-outputs.md)
- [Content production](content-production.md)
