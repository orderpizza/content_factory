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
delivery-ready visual assets. It supports many future pipelines without making
their creative layouts a generic system concern.

```text
Pipeline
  → immutable ContentPackage + versioned visual specification
  → persisted RenderRun
  → Visual Renderer worker
  → verified RenderAsset manifest
  → human review
```

The pipeline owns editorial meaning, visual roles, structured content, and the
selection of one or more compatible profiles for a particular package. The
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
example, an SVG/vector, custom illustration, or motion renderer) must be
registered behind the same persisted specification and output-manifest boundary
only after its purpose, local runtime dependency, licensing, reproducibility,
and validation rules are approved. Adding one must not change the pipeline or
Posting Agent contract.

## Core concepts

| Term | Meaning |
| --- | --- |
| **Visual profile** | A renderer-owned, pipeline-neutral, versioned visual capability: its reusable layout/design rules, palette, local fonts, spacing, safe areas, allowable assets, template family, and output defaults. A profile must be usable by any compatible pipeline; it is not defined by one pipeline. |
| **Template** | A versioned implementation within a renderer profile for one visual role. It renders structured content; it is not arbitrary model-generated HTML. |
| **Profile selection** | The pipeline's frozen mapping of its visual units to compatible registered visual profiles/templates. It may select more than one profile in one package. |
| **Visual specification** | The immutable package input naming the selected profile/template for every ordered visual unit, structured content bindings, local asset references, and required output(s). |
| **Renderer provider** | A local implementation identified by a stable versioned ID, initially `html_playwright_v1`. It executes a visual specification and returns assets/validation data. |
| **Render run** | One auditable attempt to render a frozen package specification. A retry creates another run; it never overwrites a prior successful run. |
| **Render manifest** | The verified ordered list of output assets and the renderer/template/font/input versions and hashes needed to identify exactly what the human reviewed. |

Every static visual unit has explicit output roles. For the initial Instagram
contract, the canonical roles are `preview_html`, `preview_png`, and
delivery-ready `delivery_jpeg`; each role has a stable ordinal. The locally
generated JPEG bytes—not a later R2 copy or adapter conversion—are the public
delivery input bound to human review.

Detailed `visual_spec_json` fields, individual template grammar, profile tokens,
selection rules, and quality thresholds are deliberately deferred to the
visual-rendering design deep dive. They will be added here and mirrored in the
data-model contract when they become stable.

## Shared profile registry

The Visual Rendering Layer maintains the enabled, versioned profile registry.
Profiles are generic building blocks—not `o2_*` or another pipeline's private
implementation. A pipeline capability declares the profiles it can use and its
role/selection constraints; it does not create, fork, or own a profile.

The initial planned registry for static educational/social content is:

| Profile ID | Reusable purpose | Suitable visual units |
| --- | --- | --- |
| `hook_emphasis_v1` | A concise, high-emphasis text introduction with a strong visual hierarchy. | Hook, title, announcement, CTA |
| `concise_explainer_v1` | Clear teaching/explanation layout for a title plus concise supporting copy. | Definition, explanation, instruction |
| `monologue_card_v1` | A single-speaker example or quotation presented as a readable card. | Example, quote, testimonial |
| `chat_dialogue_v1` | A short two-party conversation with distinct message treatment. | Dialogue, comparison, Q&A |

These profile IDs establish intended reusable capabilities, not final visual
design. Their palette tokens, font set, template grammar, content limits,
supported dimensions, and quality fixtures will be defined in the follow-up
deep dive. New profiles are added to this registry only when they represent a
reusable visual need across more than one plausible pipeline or format.

For every package, the pipeline selects only profiles registered as compatible
with its capability and records the result in the immutable visual
specification. A selection change is creative/format change and therefore
requires a new package; the renderer may only retry the frozen selection.

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

The deep-dive contract will define the complete validation suite. At minimum,
the target design requires dimensions and format verification, required-font
availability, complete ordered asset count, local-path/output readability,
hashes, JPEG encoder/version verification where required, and detection of
blocking layout defects such as overflow, clipping, or missing required
content. The dashboard displays the canonical final delivery assets and their
stored manifest/hash validation, not a fresh renderer preview.

## O2 English as the first profile consumer

O2 English Instagram is the first pipeline to consume the shared profile
registry. It uses the local `html_playwright_v1` provider for 1080×1920
vertical static slides and selects these generic profiles:

| Slide role | Selected shared profile |
| --- | --- |
| `hook` | `hook_emphasis_v1` |
| `explanation` | `concise_explainer_v1` |
| `use_case_monologue` | `monologue_card_v1` |
| `use_case_dialogue` | `chat_dialogue_v1` |

O2-specific copy limits, sequence, delivery format, and visual requirements
remain in the [O2 English Instagram pipeline contract](../pipelines/o2-english-instagram.md).
O2 may specify a compatible neutral theme/brand treatment as an input to a
selected shared profile, but it does not own or duplicate the profile. This
document owns the reusable renderer boundary and profile registry, not O2's
editorial format.

## Acceptance direction

Before a renderer/profile is enabled for public delivery, boundary tests must
show that a frozen visual specification resolves the intended local template,
produces all declared assets at the expected dimensions/format, records exact
versions and hashes, rejects blocking output defects, and leaves package
creative/metadata unchanged. Detailed acceptance fixtures and visual-regression
rules will be defined in the follow-up design.

## Related contracts

- [System guide](../system.md)
- [Data model](data-model.md)
- [Reliability and safety](reliability.md)
- [Worker runtime](runtime.md)
- [O2 English Instagram pipeline](../pipelines/o2-english-instagram.md)
