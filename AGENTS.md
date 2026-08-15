# AGENTS.md

## Project

This is a local-first automated content factory POC.

The POC goal is to prove:

Trend Detection
→ Determination
→ ContentJob
→ One Content Pipeline
→ Visual Rendering
→ Posting Agent

## Core Rules

- Keep the POC simple.
- Do not implement future architecture prematurely.
- Mac Mini is the primary runtime.
- GCP is used primarily for Gemini API calls.
- SQLite is the POC database.
- Prefer deterministic/local processing where practical.
- Keep component boundaries explicit.
- Do not introduce unnecessary infrastructure.

## Source of Truth

Before making significant architectural changes, consult:

- `docs/vision.md`
- `docs/poc.md`
- `docs/architecture.md`
- `docs/interfaces.md`
- `docs/decisions.md`

Keep these documents synchronized with significant architectural decisions.

## Architecture Boundaries

The system is organized around this responsibility chain:

```text
Trend Detector
  -> Determination
  -> ContentJob
  -> Pipeline
  -> ContentPackage
  -> Visual Renderer
  -> Posting Agent
  -> PostRecord
```

- Trend detection answers: what is happening?
- Determination answers: what should we create?
- The pipeline answers: how do we create it?
- The visual system answers: how do we render it?
- The posting agent answers: when and where should we publish it?

Do not let one layer absorb another layer's responsibility.

## Development

- Follow existing project conventions.
- Write tests for important component boundaries.
- Do not modify unrelated code.
- Keep external API access isolated.
- Never commit secrets.
- Prefer explicit data models at component boundaries.
- Keep state in SQLite.
- Make failures visible through logs and persisted status fields.
- Use deterministic/local processing when practical.
- Use Gemini behind a small client/service; do not scatter direct API calls.

## Current POC Scope

One:
- trend detector
- determination layer
- content pipeline
- visual template
- posting platform

Multiple pipelines, sophisticated trend intelligence,
advanced orchestration, multi-platform publishing, etc.
are out of scope unless explicitly requested.

## Implementation Order

1. Repository structure, configuration, and SQLite.
2. Trend collector/detector.
3. Trend to determination.
4. ContentJob persistence.
5. One POC pipeline.
6. Visual renderer.
7. Posting queue.
8. Posting agent.
9. End-to-end autonomous test.
10. Observe failures and improve.
