# Decisions

Record meaningful architectural decisions here. Keep entries short, dated, and
oriented around choices that affect component boundaries or future work.

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
`poc_pipeline`.

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
