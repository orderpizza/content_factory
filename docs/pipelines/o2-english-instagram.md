# o2 English Instagram Pipeline

**Document role:** Tier 2 target pipeline contract. It defines required
behavior; verify implementation from code and tests after development begins.

## Purpose and Identity

This document defines the active O2 English implementation of the Content
Factory contracts. Read the [system guide](../system.md) for the generic
component/input/output map, lifecycle rules, and local operation guidance.

| Field | Value |
| --- | --- |
| `pipeline_id` | `o2_english_instagram` |
| `target_platform` | `instagram` |
| `target_account` | `o2_english` |
| `content_format` | Idiom teaching carousel |
| `allowed_visual_profiles` | `hook_emphasis_v1`, `concise_explainer_v1`, `monologue_card_v1`, `chat_dialogue_v1` |

The pipeline turns an accepted O2 English `ContentJob` into one validated,
immutable Instagram `ContentPackage` through a durable `GenerationRun`. It
creates and validates creative content, metadata, and the visual specification.
The package has no rendering/posting status: a `RenderRun` creates verified
preview and delivery assets, a `ReviewRequest` owns human approval, and delivery
begins only from that approval. Visual rendering and posting are separate
system components described in the system guide.

## Capability Contract

Determination may select this capability only when all of these are true:

- The teaching target is one English idiom or idiomatic expression that can be
  normalized to a stable canonical target.
- The requested value is useful to English learners and can be taught through
  a hook, concise explanation, and natural usage examples.
- The brief provides or permits an audience, tone, and teaching objective that
  fit the O2 account.
- The request does not depend on unsupported real-time facts, an unverified
  factual claim, or a visual/content format outside this carousel contract.
- The O2 content, rendering, review, and Instagram delivery prerequisites are
  enabled for the frozen capability version.

The versioned capability snapshot records `pipeline_id`, destination account,
format, allowed renderer-profile set and selection policy, content-contract
version, estimated model stages/cost class, and prerequisite availability.
Intake may clarify a weak brief, but Determination owns the authoritative
accepted/not-recommended/blocked decision.

The route-neutral coverage identity is the normalized teaching target. Content
identity adds the immutable revision ID, pipeline, account, format, and
content-contract version. A new worker attempt does not create a new identity;
an explicit human revision does.

## Content Contract

### Slide sequence

Each package contains 5–8 ordered slides:

1. The first slide is a `hook`.
2. It has 1–2 `explanation` slides.
3. It has 3–5 use-case slides, each either `use_case_monologue` or `use_case_dialogue`.

| Type | Purpose | Limit |
| --- | --- | --- |
| `hook` | Introduce the idiom and capture attention | 16 words |
| `explanation` | Explain meaning, nuance, and/or usage | 34 words |
| `use_case_monologue` | Show one natural first-person use | 22 words |
| `use_case_dialogue` | Show a short conversational use | At most two messages; 14 words per message |

The pipeline validates ordering, count, type-specific structure, and the word limits above before a `ContentPackage` may be persisted.

### Metadata contract

Package metadata is created only after the slides are accepted. It requires:

- A non-empty caption.
- 2–6 unique tags.
- 3–8 unique hashtags.
- Every hashtag begins with `#` and contains no whitespace.

Tags are private editorial/search labels stored with the package; hashtags are
the public tokens serialized into the immutable Instagram caption according to
the versioned platform policy. Caption and hashtag validation applies to the
final serialized value, including platform length/character constraints in
that policy.

Package provenance distinguishes trend/opportunity evidence, factual or
teaching references, human-supplied context, and generated examples. A trend
URL is not represented as a factual citation unless it supports the teaching
claim.

The posting agent treats all metadata and rendered assets as immutable input. It must never write or revise captions, tags, hashtags, slide copy, or visual content.

## Generation Boundary

Gemini is used by this pipeline in two separate calls:

1. Generate the slide content using a temperature of `0.65`.
2. Once slide validation succeeds, generate caption, tags, and hashtags using a temperature of `0.45`.

If metadata generation fails validation, the pipeline retries metadata without regenerating the accepted slides. A failed slide-generation attempt does not create a package. The detector remains deterministic and LLM-free; determination uses the system-level LLM decision boundary before this pipeline begins.

In the target model, a durable `GenerationRun` persists the validated slide
snapshot/hash before metadata begins. Bounded metadata retries reference that
same snapshot even after process restart. Every Gemini attempt receives a
`ModelInvocation` row before the call and a terminal provider/validation
outcome afterward. A technical retry may try another draft only before a
package exists; once a package is persisted, creative change requires a new
BriefRevision and ContentJob.

Unavailable or invalid Gemini metadata fails visibly. The pipeline must not
silently replace it with hardcoded tags or hashtags.

## Shared Profile Selection and Visual Rendering

| Slide type | Selected shared profile |
| --- | --- |
| `hook` | `hook_emphasis_v1` |
| `explanation` | `concise_explainer_v1` |
| `use_case_monologue` | `monologue_card_v1` |
| `use_case_dialogue` | `chat_dialogue_v1` |

O2 uses these renderer-owned, generic profiles with a compatible neutral visual
treatment for vertical 1080×1920 slides. The pipeline may select one or more
of them for a package only according to this role mapping; the exact selected
profile/template/version is frozen in that package's visual specification. It
uses the shared `html_playwright_v1` provider: versioned local HTML/CSS
templates render structured package content through local Playwright Chromium.
The separate Visual Renderer produces reviewable HTML/PNG previews and final
delivery-ready JPEG assets. Rendering and the versioned PNG-to-JPEG conversion
are deterministic and do not use an LLM. The reusable renderer, local-font,
asset, and quality boundary is defined in the
[Visual Rendering specification](../specs/visual-rendering.md).

O2 owns its format-specific role mapping and selection constraints. The Visual
Rendering Layer owns the selected shared profile/template implementation and
execution of the frozen specification; O2 never calls a renderer directly.

The target manifest binds package/content hash, template and renderer version,
conversion-contract version, ordered slide role, canonical asset key, MIME
type, pixel dimensions, byte size, and SHA-256. Human review displays the exact
delivery JPEGs. The Posting Agent later stages those same verified bytes; it
does not convert or repair them.

## Instagram Delivery

### Delivery path

After migration, the adapter receives a claimable `PostRecord` created from a
human-approved `PostRequest` and an exact final-delivery manifest:

1. Reverify the approved package hash, manifest hash, JPEG checksums,
   destination, and policy-compliant schedule.
2. Upload the already-reviewed JPEG bytes to temporary public R2 objects.
3. Create and audit carousel child/parent resources without changing creative.
4. Persist the final-publication-request marker immediately before
   `media_publish`.
5. Publish at most once automatically. Any timeout, lost response, or local
   failure after that marker becomes terminal `publication_unknown`.
6. Queue R2 cleanup independently of publication outcome.

Target delivery uses `PostRequest`, `PostRecord`, `PostAttempt`,
`PublicationResource`, `DeliveryCleanupTask`, and the persisted reconciliation
records. A read-only reconciliation worker may investigate
`publication_unknown`; neither it nor the dashboard can retry or call
Instagram directly. The dashboard’s explicit **Post now** command atomically
creates the immutable `PostRequest` and initial immediate `PostRecord`; the
Posting Agent claims that record.

### Required delivery configuration

The local `.env` file provides:

```text
INSTAGRAM_USER_ID
INSTAGRAM_ACCESS_TOKEN
INSTAGRAM_GRAPH_API_VERSION
R2_ACCOUNT_ID
R2_ACCESS_KEY_ID
R2_SECRET_ACCESS_KEY
R2_BUCKET_NAME
R2_PUBLIC_DOMAIN
```

See [the root `.env.example`](../../.env.example) for the complete
configuration reference. Never commit populated secrets or access tokens.

The token must authorize the Meta account relationship that owns the target
professional account. `INSTAGRAM_USER_ID` identifies that account for
container creation and publication. See the [Meta platform reference](../platforms/meta.md)
for the Facebook-profile/Page/Instagram-account relationship, required
permissions, and token lifecycle.

R2 is a transient public-media relay, not the canonical content library. Its
S3 credentials and enabled public development URL are local-only configuration.

## Acceptance Criteria and Boundary Tests

The implementation is acceptable when:

- Generated packages satisfy the slide contract, ordering rules, word limits, and metadata validation.
- A durable GenerationRun retains accepted slides across metadata retry and
  process restart; every Gemini attempt is auditable.
- Renderer output is 1080×1920, maps every slide type to the shared profile
  selection above without changing package content, and manifests final JPEG
  hashes before review.
- Approval binds the exact package and final-delivery manifest shown to the
  human; missing, expired, or hash-mismatched assets cannot be approved.
- The target adapter stages the approved JPEG bytes, creates ordered child
  containers, waits for readiness, publishes at most once, records remote IDs,
  and queues cleanup after success or failure.
- Posting rejects malformed delivery input, never mutates/converts the package
  or assets, and moves every ambiguous final request to
  `publication_unknown` without automatic retry.

Boundary tests cover capability eligibility, generation checkpoints,
generation/metadata validation, template resolution, final asset manifests,
review/hash binding, posting-request construction, fenced claims,
unknown-publication behavior, Graph API delivery steps, reconciliation, and
cleanup. Any live smoke test must exercise the same approval and immutable-asset
boundary with explicit credentials and authorization; it is not a substitute
for human approval.

## Related Documents

- [System guide](../system.md)
- [Visual Rendering specification](../specs/visual-rendering.md)
- [Posting Agent specification](../specs/posting.md)
- [Meta platform reference](../platforms/meta.md)
