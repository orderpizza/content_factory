# Content Production Specification

**Document role:** Tier 2 target design contract. It defines the generic
Pipeline Runner, canonical-content, and platform-adaptation boundary; verify
implementation conformance from code and tests.
**Owner:** `ContentJob`, domain generation, `CanonicalContent`, `OutputRequest`,
`AdaptationRun`, and immutable platform-specific `ContentPackage` contracts.
**Read this for:** Pipeline Runner, domain strategy, canonical-content,
platform-adaptation, metadata-generation, output-binding, or package changes.
Read [the system guide](../system.md) first and [the data model](data-model.md)
for persisted fields and constraints.

## Purpose and boundary

Content Production has two Gemini-owned stages. The Pipeline Runner claims a
domain `ContentJob` and produces immutable, platform-neutral
`CanonicalContent`. It then creates one `OutputRequest` for every eligible
platform/account/format binding in the job's frozen output plan. The Adaptation
Worker claims each request and creates one immutable, platform-specific
`ContentPackage`.

`ContentJob` is a domain recipe, not a platform command. `CanonicalContent`
contains the reusable editorial envelope and domain extension but no captions,
hashtags, platform copy, slide layout, or pixel dimensions. An `OutputRequest`
identifies the exact platform/account/format, output-contract version, and
renderer compatibility. The output adapter resolves those details in the
package; the Visual Renderer remains deterministic and renders only the frozen
visual specification.

The workers communicate only through SQLite. Domain strategies and output
adapters are in-process dispatch inside their respective workers, not separate
scheduled services. Neither worker invokes the renderer, dashboard, or posting
adapter directly.

## Domain generation

Before a domain-generation call, the Pipeline Runner records a `GenerationRun`
and model-invocation ledger entry. It validates and commits `CanonicalContent`
with its canonical identity and hash before it creates any `OutputRequest`.
The canonical record includes a common envelope—hook, context, key points,
examples, conclusion/takeaway, claim IDs, and source/reference IDs—plus the
versioned domain extension.

One canonical record may support multiple output bindings. Failure or
unavailability of one binding does not discard the canonical content or affect
independent bindings.

## Output adaptation — `output_adaptation_v1`

The Adaptation Worker uses a separate Gemini call from domain generation. It
converts the already committed canonical content into the exact platform output:
caption or ordered X post text, tags, hashtags, alt text, claim mappings, and
the resolved `visual_spec_json` slide/card bindings. It records an
`AdaptationRun` and model invocation for every bounded attempt, then commits an
immutable `ContentPackage` only after output validation succeeds.

A metadata validation or generation failure does not discard or regenerate the
canonical content. The adaptation run may retry its own bounded metadata
attempts using the already-checkpointed adapted body. Canonical content is
committed before any adaptation begins.

## Related contracts

- [System guide](../system.md)
- [Data model](data-model.md)
- [Idea Intake and Determination](idea-intake-and-determination.md)
- [Visual Rendering](visual-rendering.md)
- [Reliability and safety](reliability.md)
