# Phase 1 Platform Output Contracts

**Document role:** Tier 2 target output-composition contract.
**Owner:** Platform-native text/metadata, static visual-unit composition, format
validation, and selection of renderer profiles. Provider API calls belong to
[Posting](posting.md) and its platform references.

## Shared output boundary

`CanonicalContent + OutputRequest → AdaptationRun → ContentPackage + RenderRun`.
The canonical object is the reusable intelligence result. A package is one
immutable platform/account/format variant, never an account-neutral publishable
object. The [production contract](content-production.md) owns retries, budgets,
and checkpoints; [Visual rendering](visual-rendering.md) owns pixels.

Each package contains frozen destination, format and contract versions, canonical
ID/hash, adapted copy and claim mappings, optional approved CTA, private tags,
public metadata, alt text, and an ordered visual specification. Preserve required
qualifications, disclosures, source links, and attribution in the actual public
text or assets. Provenance remains in SQLite whether or not citations are shown.
English internal teaching assertions are not automatically public citations.

The adapter must reject content that cannot fit safely; it cannot remove a
material caveat, invent a source, truncate after approval, or delegate copy
repair to posting. No AI images or video generation is required for Phase 1.

The current `--review-preview` path implements closed versions of the Instagram
carousel and X single-post shapes below and validates copy, tags, alt text, claim
mapping, and weighted X length. Synthetic bindings always write
`delivery_ready=false`. V4 production bindings use the same immutable package
shapes but require the approved delivery profile and become eligible only after
render/hash/readiness validation. Offline conformance is not a claim that live
provider limits or real accounts have been accepted.

## Instagram — `instagram_static_carousel_v2`

Primary output is a static, ordered carousel. The proposed internal format
contains 5–8 images, with an optional CTA only when useful. These are editorial
limits, not claims about the current provider maximum. The frozen provider
contract may impose stricter limits; readiness must validate both.

| Domain | Default semantic progression |
| --- | --- |
| English | Hook → meaning/context → explanation → natural examples/dialogue |
| AI / Tools | Hook → what happened → capabilities → why it matters → use cases/takeaway |
| Personal Finance | Hook → event → explanation → consumer impact → what to watch |
| Business / Side Hustles | Hook → trend/problem → opportunity → examples → risks/action/takeaway |
| Psychology / Behavior | Hook → observed behavior → possible mechanism → example → implication/response |

Composition may vary while retaining the canonical angle and required claims.
English's initial mapping keeps one hook, 1–2 explanation units, and 3–5 example
units subject to the overall 5–8 limit. Other domains are not forced into the
English grammar. The final unit must carry a takeaway or useful concluding
example; a promotional CTA is never mandatory.

The Instagram output owns caption generation and its deterministic serializer:
hook, blank line, summary, optional blank-line CTA, optional blank-line hashtag
list. Proposed local bounds are 1,500 Unicode code points for the final caption,
up to one 12-word CTA, 2–6 unique private tags, and 0–8 public hashtags. Hashtags
use lowercase ASCII `#[a-z0-9_]{1,48}` and sort lexicographically; tags use
NFKC/casefold/trimmed-whitespace normalization and sort by normalized value.
No invented affiliate links, high-pressure CTA, unsupported promise, or
disclosure hidden in private metadata. Platform validation includes any stricter
verified caption/hashtag constraints.

English copy retains the local limits of a 16-word hook, 34-word explanation,
22-word monologue, and at most two 14-word dialogue messages. The deterministic
word counter normalizes NFKC, whitespace, curly apostrophes and nonbreaking
hyphens, then matches `[\p{L}\p{N}]+(?:['-][\p{L}\p{N}]+)*`. Labels do not count
as dialogue copy but have their own profile capacity. Other domain unit limits
are owned by their selected versioned template bindings, not inferred from an
English schema.

Use a new static profile version for a proposed 1080×1350 Instagram canvas,
locally manifested preview HTML/PNG and final delivery JPEG. This resolves the
old 1080×1920 pipeline/profile versus 1080×1350 Meta staging conflict. Do not
resize old reviewed assets or silently mutate `editorial_clean_v1`; the new
profile requires exact geometry, fonts, runtime, byte limits, and regression
fixtures before activation. Dimensions are an internal design choice subject to
current provider verification, not a newly verified provider fact.

## X — `x_static_post_v1`

Default output is one static image plus X-native post text. Choose a strong
hook/summary card or adapt a suitable canonical point; do not forward an entire
Instagram carousel or copy its caption/hashtag block unchanged.

The package freezes one image specification, one complete post text, alt text,
private tags, and any approved public links/disclosures. Its text supplies useful
context independently of the image and preserves material caveats. The proposed
card canvas is 1200×675 under a separately versioned shared static profile.
Reuse typography/templates where compatible, but do not crop away approved copy.

Do not hard-code an assumed X character limit, URL length, media quota, image
encoding, or subscription entitlement. The versioned destination/provider
profile must define exact text-weight counting, link handling, MIME/dimensions/
byte limits, media attachment rules, and alt-text behavior from verified official
requirements. Missing rules block adaptation/readiness before model spending.

## Optional X threads — `x_static_thread_v1`

Image + thread is an optional X format, disabled by default. It is a mutually
exclusive choice with the single-post format for a domain/destination output,
not an extra automatic publication. Its proposed local bound is 2–5 ordered
posts, the first with the single image; all later posts are text-only replies.
Every post text, ordinal, reply relationship, source/disclosure placement, and
asset mapping must be frozen and reviewed as one package before authorization.

The provider contract and forward schema must support a persisted
`PublicationStep` for each publicly visible post. Each step gets its own fenced
pre-send marker and returned remote ID. Never resend a completed or uncertain
step. A failure after a confirmed prefix is partial publication, not unpublished
or a safe retry of the whole thread. Halt on uncertain outcomes, show the exact
published prefix, and require read-only reconciliation. No automatic restart,
deletion, or repost of that prefix is allowed.

Before any step is sent, normal cancellation may cancel the package. After the
first public step, Phase 1 has no generic cancel/restart control; partial or
uncertain results require reconciliation. A recovery design for continuing an
unpublished suffix, including new explicit authorization, must be specified and
tested before that feature is offered. Threads remain disabled until exact
per-step transitions, expiry/cadence accounting, and failure fixtures are ready.

## Review and platform isolation

Instagram and X get independent ContentPackages, RenderRuns, ReviewRequests,
PostRequests, and PostRecords. Approving Instagram does not approve X. Rejection,
expiry, adaptation failure, or delivery failure on one destination does not
erase sibling content or imply its rejection. Review displays the exact final
image(s), full caption/post/thread text, destination, sources, and hashes.

Posting never adds hashtags, changes alt text, shortens a post, creates a reply,
or converts assets. Any such change is output rework, followed by fresh review.
The [Posting specification](posting.md) owns authorization and delivery safety.

## Enablement gates

Implement and test output schemas, discriminated domain-to-unit mapping,
serializers, native text limits, canonical claim preservation, new static profile
geometry/goldens, and independent review bindings before output workers run.
Verify [Meta](../platforms/meta.md) and [X](../platforms/x.md) requirements before
enabling their destinations. An optional thread must pass additional partial-
publication tests; single-post X support does not prove thread safety.
