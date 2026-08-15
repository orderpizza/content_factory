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
