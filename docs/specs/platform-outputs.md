# Platform Output Contracts

**Owner:** Adapted copy, metadata, claim mappings and visual-unit composition.
**Implementation:** `src/workflow/gemini_adaptation.py`.
These are enforced local limits, not claims about providers' current maximums.

## Shared package

Each `output_adaptation_v1` package freezes platform, account, format, public
text, private tags, hashtags, alt text, claim mappings, ordered visual units,
closed semantic `visual_intent` and delivery-ready flag. Production selects a delivery profile; preview selects a
non-deliverable review profile. A delivery-ready package alone does not authorize
a public post.

Every canonical claim ID must appear in public-text or visual-unit mappings.
Unknown/duplicate IDs are rejected. ID coverage does not verify that the public
wording faithfully expresses the claim; human review remains necessary.

| Field | Local validation |
| --- | --- |
| Private tags | 2–6 unique NFKC/casefold/whitespace-normalized strings, sorted |
| Hashtags | Unique lowercase ASCII `#[a-z0-9_]{1,48}`, sorted |
| Alt text | 1–1,000 code points |
| Visual unit | Closed role/title/body/claim_ids shape |
| Unit role | hook, explanation, example or takeaway |
| Unit title/body | 1–120 / 1–600 code points after normalization |

`visual_intent_v1` has bounded primary structure, tone, density, emphasis targets
and image need. It contains no template ID, color, font, geometry, CSS, HTML,
SVG, JavaScript or remote asset URL. The shared Visual Planner owns registered
recipe selection. The renderer accepts structured units, never model-authored
HTML/CSS. The planner maps each frozen unit role to a registered,
archetype-bound per-unit layout variant in the immutable VisualRecipe; adaptation
does not name layouts. [Visual rendering](visual-rendering.md#visual-planning-and-recipes) owns exact profiles,
geometry and assets. [Content production](content-production.md) owns checkpoints
and sibling isolation.

## Instagram — `instagram_static_carousel_v2`

One package has 5–8 ordered units, beginning with a hook and ending with a
takeaway. These constraints apply to every domain; there is no separate
English slide grammar or word-count validator.

The caption serializer joins the canonical hook, generated summary, optional
CTA and optional hashtag block with blank lines.

| Field | Local bound |
| --- | --- |
| Summary | 1–1,100 code points |
| Optional CTA | At most 12 whitespace-separated words and 120 code points |
| Final caption | At most 1,500 code points |
| Hashtags | 0–8 |

Canonical meaning, qualifications and source attribution must remain visible
where needed. Private metadata is not a substitute for public disclosure.
The [Meta adapter](../platforms/meta.md) delivers reviewed JPEGs and exact caption;
it never generates copy.

## X — `x_static_post_v1`

One image accompanies native post text. The card role is hook, explanation or
takeaway. It is not an Instagram carousel forwarded to X.

| Field | Preview | Production |
| --- | --- | --- |
| Post text before hashtags | 1–800 code points | 1–800 code points |
| Final text including hashtag block | At most 900 code points | At most 280 locally weighted characters |
| Hashtags | 0–2 | 0–2 |

The production counter accounts for URL weighting, combining marks and wide
characters; it is not a complete `twitter-text` implementation. Preview success
therefore does not establish X delivery conformance. The [X reference](../platforms/x.md)
describes the adapter and live acceptance limits.

X threads are not supported by the schemas, renderer or delivery worker.
Their required per-post safety design belongs in [the roadmap](../plans/target-implementation.md).

## Independent review

Each destination has its own package, render, review and delivery authorization.
Review concerns the exact images, full public text, destination and hashes.
Approving one destination never approves another. Posting cannot shorten text,
append hashtags, convert assets or repair a package; changes need fresh work and
review. [Posting](posting.md) owns that authorization boundary.
