# O2 English — Compatibility Routing Note

**Document role:** Tier 2 superseded-contract navigation.
**Owner:** Documentation routing. This path is retained for old links; it is
not an active platform-specific pipeline specification.

The old `o2_english_instagram` pipeline combines responsibilities that Phase 1
now separates. Do not register it alongside the five domain pipelines or use
its old draft schema to implement new generation.

| Previous responsibility | Current canonical owner |
| --- | --- |
| English teaching scope, sense, approved assertions, natural examples | [Domain pipelines — English](domains.md#english--english) |
| Generation attempts, canonical content, adaptation checkpoints/cost | [Content production](../specs/content-production.md) |
| Carousel sequence, caption/tags/hashtags, word limits, visual-unit mapping | [Platform outputs](../specs/platform-outputs.md) |
| Profiles, local fonts, HTML/CSS + Playwright, exact asset manifests | [Visual rendering](../specs/visual-rendering.md) |
| Review and immutable delivery authorization | [Dashboard](../specs/dashboard.md), [Posting](../specs/posting.md) |
| Instagram account, token, API, and temporary R2 staging | [Meta reference](../platforms/meta.md) |

The new domain ID is `english`; `o2_english` remains the primary Instagram
account key. Vocabulary, phrases, and cultural usage join idiomatic expressions.
The same canonical teaching content may also be adapted for a configured X
destination, independently reviewed and approved.

The prior slide-coupled `o2_creative_v1`, `recipe_v1`, and
`determination_result_v1` drafts are superseded. The old vertical
`editorial_clean_v1` profile is retained as a versioned legacy reference, not
silently resized for new platform outputs. See
[contract maturity](../contracts/maturity.md) before implementation.
