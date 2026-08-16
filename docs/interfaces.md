# Interfaces

This file defines the contracts between components. Change these deliberately:
they are the most important boundaries in the POC.

```text
TrendCandidate
  -> Determination
  -> ContentJob
  -> ContentPackage
  -> PostRequest
  -> PostRecord
```

Exact Python models and SQLite columns can evolve during implementation, but
the responsibilities below should remain stable.

## Observation

Produced by a source adapter and stored as raw detector evidence.

Conceptual fields:

```text
topic
title
source
source_item_id
url
observed_at
current_volume
baseline_volume
raw_data
```

Source adapters must not call an LLM. They normalize external data into this
contract.

## TrendCandidate

Produced by the deterministic Scout after historical analysis.

Conceptual fields:

```text
topic
score
lifecycle_stage
score_breakdown
supporting_sources
first_seen_at
last_seen_at
status
cooldown_until
```

The candidate is the handoff boundary to determination. It must explain why it
was ranked and retain enough evidence for downstream review. `NEW` means there
is not enough history yet; `EMERGING` means a previously observed topic is
showing strong positive growth. A candidate may be updated while cooldown
prevents repeated downstream claims.

The detector may persist many scored candidates, but its handoff output is a
shortlist: candidates must pass the configured minimum score and rank within
the configured top-N limit. Selected records are marked
`pending_determination`, identifying the records for the determination worker.

## ContentJob

Produced by the determination layer and consumed by the pipeline runner.

Conceptual fields:

```text
job_id
trend_id
pipeline_id
topic
angle
audience
objective
key_points
sources
priority
status
created_at
updated_at
```

Rules:

- Determination creates a `ContentJob`.
- Determination does not call pipeline functions directly.
- `pipeline_id` exists even though the POC has only one real pipeline.
- The pipeline runner loads pending jobs from SQLite.

## ContentPackage

Produced by a content pipeline and consumed by visual rendering and posting.

Conceptual fields:

```text
content_id
job_id
pipeline_id
title
body
caption
visual_spec
assets
sources
created_at
```

The posting agent should not need to know how the content was generated.

## VisualSpec

Contained within a `ContentPackage` and consumed by the visual renderer.

Conceptual fields:

```text
template_id
title
subtitle
body
theme
format
```

For the POC, visual rendering should be deterministic with one template, one
theme, one primary font configuration, and standardized dimensions such as
`1080x1350`.

## PostRequest

Produced when content enters the posting queue.

Conceptual fields:

```text
content_id
platform
account
caption
assets
requested_at
scheduled_at
status
```

The posting queue should support duplicate protection and basic scheduling.

## PostRecord

Produced and updated by the posting agent.

Conceptual fields:

```text
id
content_id
platform
account
status
scheduled_at
published_at
external_post_id
error
created_at
updated_at
```

The database must answer:

- What have we posted?
- When did we post it?
- Where did we post it?
- Was it successful?
- Has this content already been posted?

## Boundary Tests

At minimum, tests should cover:

- Observation stored correctly.
- TrendCandidate score and lifecycle calculated correctly.
- Candidate cooldown and atomic claiming.
- Source failure persisted without stopping other sources.
- TrendCandidate accepted by a fake determination consumer without Gemini.
- `Trend` stored correctly.
- `Trend` to `ContentJob`.
- `ContentJob` to pipeline execution.
- Pipeline to `ContentPackage`.
- `ContentPackage` to visual asset.
- `ContentPackage` to post queue.
- Post queue duplicate protection.
- Post queue to publication record.
