# Decisions

Record meaningful architectural decisions here. Keep entries short, dated, and
oriented around choices that affect component boundaries or future work.
Entries are immutable historical records. When a decision changes, add a new
entry that supersedes it rather than rewriting the original.

## 001 - Local-First Runtime

Date: 2026-08-15

Decision: The Mac Mini is the primary runtime for the POC.

Reason: The POC should stay local-first and avoid unnecessary cloud
infrastructure.

Consequence: Collection, scheduling, rendering, posting orchestration, and
SQLite storage should run locally unless explicitly changed later.

## 002 - Gemini API For LLM Tasks

Date: 2026-08-15

Decision: Use Gemini API for determination and generation tasks where an LLM is
useful.

Reason: GCP credits are intended primarily for Vertex AI Gemini calls.

Consequence: Gemini access must be isolated behind a small client/service. Do
not scatter provider calls throughout unrelated modules.

## 003 - SQLite For POC State

Date: 2026-08-15

Decision: Use SQLite as the POC database.

Reason: It is local, simple, inspectable, and sufficient for proving the loop.

Consequence: Do not introduce cloud databases or distributed state during the
POC.

## 004 - Determination Produces ContentJob

Date: 2026-08-15

Decision: The determination layer produces a standardized `ContentJob`.

Reason: This keeps the decision layer separate from production workflows.

Consequence: Determination must not directly call pipeline-specific functions.

## 005 - One Predefined POC Pipeline

Date: 2026-08-15

Decision: Implement only one real content pipeline for the POC:
`o2_english_instagram`.

Reason: The POC proves the loop, not a generalized pipeline platform.

Consequence: Keep `pipeline_id` in the interface, but do not build future
pipelines until requested.

## 006 - Deterministic Visual Rendering

Date: 2026-08-15

Decision: Use HTML/CSS and Playwright for the initial visual renderer.

Reason: The first visual system should prove consistent template rendering
without relying on AI image generation.

Consequence: Centralize theme, typography, spacing, and dimensions.

## 007 - Posting Agent Separate From Pipelines

Date: 2026-08-15

Decision: Posting is handled by a separate posting agent.

Reason: Content creation and distribution scheduling have different
responsibilities.

Consequence: Pipelines produce finished content packages; the posting agent owns
queueing, scheduling, duplicate protection, platform calls, and publication
records.

## 008 - Deterministic Detection Before LLM Determination

Date: 2026-08-15

Decision: Complete and observe the trend detection layer independently before
implementing the Gemini determination workflow.

Reason: Detection requires continuous historical measurement and tuning. Using
LLMs during collection would add cost and make it harder to distinguish source
signals from model interpretation.

Consequence: The Scout produces explainable `TrendCandidate` records in SQLite.
Determination consumes eligible candidates only after the detector contract and
scoring behavior are stable.

## 009 - Multi-Source Deterministic Scout

Date: 2026-08-15

Decision: Use source adapters for free Hacker News, RSS/Atom, and Wikimedia
signals, with retries and persisted source health.

Reason: No single source represents broad public attention, and the POC must
remain free and local-first.

Consequence: Source activity must be normalized before comparison. Additional
sources can be added without changing downstream interfaces.

## 010 - Candidates Are Observable State

Date: 2026-08-15

Decision: Persist ranked candidates, lifecycle, score breakdown, evidence, and
cooldown state in SQLite. Provide a read-only live dashboard.

Reason: The detector needs to be monitored and tuned over time, and downstream
consumption must be separate from dashboard presentation.

Consequence: The dashboard never controls the workflow. Determination reads
structured candidate state directly from SQLite.

## 011 - Monetization Is Downstream Opportunity Evaluation

Date: 2026-08-15

Decision: Keep raw trend measurement separate from monetization evaluation.

Reason: A topic can be highly popular but commercially unsuitable, while a
smaller trend may have a strong audience or product opportunity.

Consequence: Detection reports attention and evidence. Determination later
evaluates audience, angle, pipeline, and monetization path.

## 012 - Staged Trend Source Expansion

Date: 2026-08-16

Decision: Maintain a staged source roadmap rather than enabling every possible
platform immediately.

Reason: Sources differ in access approval, cost, rate limits, discovery quality,
and commercial-use restrictions. The detector must remain reliable and free at
the current POC stage.

Consequence: Wikimedia, Hacker News, and configured RSS feeds are the current
core sources. Reddit and YouTube are high-priority optional sources with
adapters ready but disabled. Google Trends is very high priority but remains
disabled until an approved access path is available. X and other platform
sources are deferred.

## 013 - Detection Shortlist Boundary

Date: 2026-08-16

Decision: Preserve the complete scored candidate history in SQLite for
observability, but pass only a configurable top-N shortlist that meets a
minimum score threshold to determination. Selected candidates are marked
`pending_determination`.

Rationale: Gemini should evaluate a bounded set of promising candidates rather
than every detected item as source coverage grows. The shortlist policy can be
tuned without changing the TrendCandidate interface.

## 014 - System-Level Read-Only Dashboard

Date: 2026-08-16

Decision: The dashboard is the system-level observability surface for the full
Content Factory loop. The current trend dashboard becomes the `Trend Detection`
view within it.

Reason: The system needs one place to understand detection, determination,
production, rendering, posting, and health as the POC grows.

Consequence: Modules own their reporting data and status semantics. The
dashboard composes read-only reports and must not absorb workflow logic or
control execution during the POC.

## 015 - Fixed Determination Handoff

Decision: Detection hands determination a persisted `DeterminationRequest`, not
a bare candidate or raw observation stream. The request freezes candidate
metadata, source evidence, trend history, and the producing detection run ID.

Reason: Gemini needs auditable context, and the input contract must remain
stable while source adapters and scoring evolve.

## 016 - Handoff Lifecycle and Duplicate Suppression

Decision: Track handoff delivery state separately from candidate lifecycle.
Suppress new active handoffs when the same candidate already has a pending or
claimed request; permit a later request only after resolution and cooldown.

Reason: A candidate can remain popular across many 30-minute Scout runs. That
should update trend evidence without repeatedly submitting the same work to
Gemini.

## 017 - Determination Selects a Platform-Specific Pipeline Recipe

Date: 2026-08-16

Decision: Determination evaluates a candidate against the available pipeline
catalog and either rejects it or writes an explicit `ContentJob` recipe. The
recipe selects pipeline, platform/account, format, audience, angle, objective,
and source context.

Reason: Determination owns the decision of whether and how a trend is consumed;
the pipeline should receive an executable instruction rather than infer the
channel or creative strategy.

Consequence: One accepted trend creates at most one job in the POC. A future
determination may create multiple jobs for one trend without moving content
creation into determination.

## 018 - Content Packages Are Platform-Specific and Pipeline-Owned

Date: 2026-08-16

Decision: A `ContentPackage` is the platform-specific result of its selected
pipeline, including native content, asset or visual specifications, caption,
and publishing metadata. Required visual rendering adds final assets before the
package becomes ready for posting. It is not a platform-neutral intermediary.

Reason: Format and platform constraints fundamentally shape creative quality.

Consequence: Pipelines may use Gemini for generation and context-sensitive tags
and hashtags, then deterministically validate metadata against platform policy.
The Posting Agent does not alter creative content.

## 019 - Shared Deterministic Posting Agent With Per-Channel Cadence

Date: 2026-08-16

Decision: Build one system-level Posting Agent that schedules and publishes
ready packages according to persisted policy keyed by pipeline, platform, and
account. It will not call an LLM.

Reason: Scheduling, rate limits, duplicate prevention, retries, and publication
history are operational responsibilities shared across content pipelines, while
each channel needs its own frequency rules. The correct platform integration is
still under design.

Consequence: The current end-to-end target is one o2 English Instagram post.
Human approval remains a future dashboard capability; the POC dashboard stays
read-only. Other pipelines, including Bluesky, will use the same system-level
posting boundary later.

## 020 - Posting Is a Dashboard-Observable Module

Date: 2026-08-16

Decision: When posting is implemented, persist queue state, cadence-derived
schedules, attempts, failures, and publication records in SQLite and report
them in the system dashboard.

Reason: The dashboard must observe the complete responsibility chain without
controlling it.

## 021 - Gemini Visual-Profile Selection and Pipeline-Owned Metadata

Date: 2026-08-17

Decision: Determination Gemini selects a high-level visual profile alongside
the pipeline and content format. The selected pipeline's Gemini generation may
refine that choice only from the pipeline's registered allowed profiles. The
pipeline also generates platform-native captions, tags, and hashtags.

Reason: Visual direction and metadata materially affect how a trend is consumed
on a channel, but sending the full visual-template hierarchy to determination
would overburden it and blur renderer responsibility.

Consequence: The visual system resolves the concrete template and renderer
settings deterministically. A future Posting Agent will use persisted captions
and hashtags without changing them.

## 022 - First Extracted Pipeline: O2 English Idiom Carousel

Date: 2026-08-17

Decision: Use the extracted visual and structured-content concepts in the
`o2_english_instagram` Content Factory pipeline. Its first format is the fixed
`instagram_idiom_carousel` profile `o2_english_idiom_carousel_v1`.

Reason: A fixed idiom carousel provides a proven visual format, while the
current system preserves its own persisted handoffs, deterministic rendering,
and system-level responsibility boundaries.

Consequence: The extracted pipeline receives a persisted `ContentJob`, emits a
platform-specific `ContentPackage`, and uses four deterministic slide templates
at 1080×1920. Future `o2_english` formats receive independent contracts rather
than extending or weakening the fixed idiom schema.

## 023 - One Isolated Vertex Gemini Client

Date: 2026-08-17

Decision: Route determination and pipeline-owned Gemini work through one
`VertexGeminiClient`. It reads `GOOGLE_CLOUD_PROJECT`,
`GOOGLE_CLOUD_LOCATION`, and `GEMINI_MODEL`; the historic `GEMINI_MDOEL` and
`VERTEX_AI_MODEL` names are read only as temporary compatibility aliases.

Reason: Gemini belongs in two distinct responsibility boundaries, but direct
SDK calls scattered through workers would make credentials, structured output,
and failures difficult to control.

Consequence: The determination worker uses Gemini to select an available
pipeline/profile and recipe. The pipeline uses Gemini for its structured
content and tags/hashtags. Both fail visibly when Vertex configuration or IAM
access is unavailable; neither has a deterministic creative fallback.

## 024 - Instagram Carousel Posting Design Is Open

Date: 2026-08-17

Decision: Keep Instagram Graph API publication, public-media delivery, retry
behavior, and account credential handling as open Posting Agent design work.

Reason: The current o2 English end-to-end target needs a posting path, but the
correct platform integration and operational behavior are not yet settled.

Consequence: The o2 pipeline creates assets locally and stops at a ready
`ContentPackage`. The Posting Agent design must remain system-level and must
not move platform delivery into the pipeline or renderer.

## 025 - Documentation Operating Model

Date: 2026-08-17

Decision: Use `docs/current.md` as the single operational status page,
`architecture.md` for durable boundaries, `interfaces.md` for contracts,
`roadmap.md` for milestone ordering, `runbooks/` for procedures, and this file
for immutable dated decisions.

Reason: Repeating current status in several narrative documents caused drift
when scope and posting plans evolved.

Consequence: Update `current.md` whenever active scope changes. Add a new
decision for an architectural change; do not rewrite an older entry to conceal
the earlier context.

## 026 - Gemini Usage Ledger and Split O2 Metadata Generation

Date: 2026-08-18

Decision: Record successful Gemini usage in an append-only `api_usage` ledger
outside the Gemini client, at the owning determination or pipeline boundary.
For the o2 idiom pipeline, generate and validate slide content before making a
separate Gemini call for caption, tags, and hashtags. A metadata retry reuses
the validated slide draft.

Reason: End-to-end cost needs phase and entity attribution, while metadata
validation should not discard otherwise valid creative slide work.

Consequence: `estimated_cost_usd` remains optional until configured pricing
rates are supplied. Pipeline workers record content and metadata calls
separately, and retry metadata without re-running slide generation. The
historic model-variable compatibility described in decision 023 is superseded:
only `GEMINI_MODEL` and `VERTEX_AI_MODEL` are supported.

## 027 - Instagram Graph API Carousel Delivery for the O2 POC

Date: 2026-08-20

Decision: Use a Posting Agent-owned Instagram Graph API adapter for the first
o2 English carousel publication. The adapter converts rendered assets to JPEG,
stages them at configured public HTTPS URLs, creates item and carousel
containers, verifies readiness, and publishes the parent container. SQLite
persists one idempotent post request, delivery attempts, retry timing, Graph
container IDs, and the final external post ID.

Reason: Instagram fetches publish media from public URLs, while this POC's
renderer writes assets locally. Delivery is operational work and must remain
separate from content generation and rendering.

Consequence: Meta credentials and public-asset-store credentials are local
configuration only. The current R2 adapter is one implementation of the
public-media boundary; replacement storage must preserve the same public-URL
contract. Posting never changes pipeline-owned caption, tags, hashtags, or
asset order.
