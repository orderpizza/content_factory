# Interfaces

This file defines the system-level contracts between components. Change these
deliberately: they are the stable persisted boundaries. For active POC limits,
see [poc.md](poc.md). For a format-specific contract, see its pipeline
documentation.

The dashboard reads these boundaries but never creates or mutates workflow
state.

```text
TrendCandidate
  -> DeterminationRequest
  -> DeterminationDecision
  -> ContentJob (recipe)
  -> platform-specific ContentPackage
  -> PostRequest
  -> PostRecord
```

## Observation

Produced by a source adapter and stored as raw detector evidence.

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

Source adapters normalize external data into this contract and never call an
LLM.

## TrendCandidate

Produced by deterministic analysis and handed to determination.

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

It retains an explainable score and enough evidence for downstream review.
Candidate lifecycle describes the evolving topic, not delivery of a specific
handoff.

## DeterminationRequest

The fixed, frozen envelope from detection to determination.

```json
{
  "handoff_id": "database-id-or-uuid",
  "detection_run_id": "run-id",
  "created_at": "timestamp",
  "candidate": {"candidate_id": 123, "topic": "normalized topic", "score": 0.61, "lifecycle_stage": "EMERGING", "score_breakdown": {}, "supporting_sources": [], "first_seen_at": "timestamp", "last_seen_at": "timestamp"},
  "evidence": [{"source": "source-name", "source_item_id": "item-id", "title": "source title", "url": "https://example.com/item", "observed_at": "timestamp", "activity_value": 100, "baseline_value": 40}],
  "history": [],
  "status": "pending"
}
```

Handoff statuses are `pending`, `claimed`, `completed`, `rejected`, `failed`,
and `cancelled`. Repeated delivery is suppressed while an active handoff exists.

## DeterminationDecision

Produced from a `DeterminationRequest`. It explicitly accepts or rejects the
candidate and, when accepted, selects one registered pipeline recipe.

```text
handoff_id
decision_status (accepted or rejected)
pipeline_id
target_platform
target_account
content_format
visual_profile_id
audience
angle
objective
key_points
reasoning
created_at
```

Determination selects from a pipeline capability catalog. It does not create
content or invoke the selected pipeline.

## DetectionRun

Each detection execution is traceable through:

```text
run_id
started_at
completed_at
observations_collected
candidates_scored
candidates_selected
status
error
```

Every `DeterminationRequest` references its producing run.

## ContentJob

Produced by determination and consumed by the pipeline runner.

```text
job_id
trend_id
candidate_id
determination_handoff_id
pipeline_id
target_platform
target_account
content_format
visual_profile_id
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

A job is an explicit production recipe, not generated content. It retains
provenance and gives the selected pipeline all necessary high-level direction.

## ContentPackage

Produced by a selected pipeline and consumed by rendering and posting.

```text
content_id
job_id
pipeline_id
platform
account
content_format
title
body
caption
tags
hashtags
visual_spec
resolved_template_id
assets
sources
status
metadata_status
metadata_model
created_at
```

It is the actual platform-specific content and native metadata. The pipeline
persists generated metadata and validates it deterministically. Tags and
hashtags are pipeline-owned channel metadata; the Posting Agent uses the
persisted values exactly as supplied.

The renderer adds final assets before the package becomes ready for posting.
For `visual_spec` structure and validation rules, read the relevant pipeline
document.

## ApiUsage

Produced as an append-only record after a successful external LLM call.

```text
phase
entity_id
model
input_tokens
output_tokens
total_tokens
estimated_cost_usd (optional)
created_at
```

It belongs to the owning determination or pipeline boundary and is not passed
to the next workflow phase.

## PostRequest

The persisted delivery request is the idempotency boundary for one
content/platform/account destination.

```text
id
content_id
pipeline_id
platform
account
status
scheduled_at
attempt_count
last_attempt_at
next_attempt_at
error
created_at
updated_at
```

Generic statuses are `scheduled`, `publishing`, `retryable_failure`,
`published`, `failed`, and `cancelled`. Platform adapters may persist delivery
artifacts and attempt history alongside this request.

## PostRecord

Produced and updated by the Posting Agent after an external publish succeeds.

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

The system must answer what was posted, when and where it was posted, whether
it succeeded, and whether the content was already delivered.

## Dashboard Reporting

Each module persists enough status and reporting data for a read-only system
dashboard to summarize:

```text
SystemOverview
DetectionReport
DeterminationReport
ProductionReport
VisualReport
PostingReport
SystemHealthReport
```

## Boundary Tests

At minimum, test observation persistence; candidate scoring and lifecycle;
handoff creation, duplicate suppression, claiming, completion, rejection, and
failure; the `TrendCandidate` to `ContentJob` boundary; pipeline package
creation; rendering completion; posting idempotency and audit records; and
deterministic validation of pipeline-owned metadata.
