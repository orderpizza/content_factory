# Interfaces

This file defines the contracts between components. Change these deliberately:
they are the most important boundaries in the POC.

The system dashboard is an observability consumer of these persisted
boundaries. It reads SQLite state from each phase, but it does not call modules
directly or create/mutate workflow state.

```text
TrendCandidate
  -> DeterminationRequest
  -> DeterminationDecision
  -> ContentJob (recipe)
  -> platform-specific ContentPackage
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

## DeterminationRequest

This is the fixed handoff envelope from detection to determination. A new
request is created only when the selected candidate has no active handoff and
is not inside its downstream cooldown.

Conceptual JSON shape:

```json
{
  "handoff_id": "database-id-or-uuid",
  "detection_run_id": "run-id",
  "created_at": "timestamp",
  "candidate": { "candidate_id": 123, "topic": "normalized topic", "score": 0.61, "lifecycle_stage": "EMERGING", "score_breakdown": {}, "supporting_sources": [], "first_seen_at": "timestamp", "last_seen_at": "timestamp" },
  "evidence": [{ "source": "rss", "source_item_id": "item-id", "title": "source title", "url": "https://example.com/item", "observed_at": "timestamp", "activity_value": 100, "baseline_value": 40 }],
  "history": [],
  "status": "pending"
}
```

The evidence and history payload is frozen when the handoff is created. It
contains source metadata and trend measurements, not an assumed full copy of
the source article. Handoff statuses are `pending`, `claimed`, `completed`,
`rejected`, `failed`, and `cancelled`.

Candidate status describes the evolving trend; handoff status describes whether
a specific delivery was consumed. These are separate concepts.

## DeterminationDecision

Produced from a `DeterminationRequest`. It records an explicit decision to
either reject the candidate or consume it through one selected pipeline.

Conceptual fields:

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

An accepted decision produces one `ContentJob` in the POC. Determination has
access to the available pipeline catalog in order to make this selection, but
it does not create content or invoke the selected pipeline. The visual profile
is a meaningful creative preset (for example, `explainer` or `quiz`), not a
low-level template configuration.

The first extracted capability is:

```text
pipeline_id: o2_english_instagram
target_platform: instagram
target_account: o2_english
content_format: instagram_idiom_carousel
visual_profile_id: o2_english_idiom_carousel_v1
```

## DetectionRun

Each scheduled Scout execution should be traceable through a run record:

```text
run_id, started_at, completed_at, observations_collected,
candidates_scored, candidates_selected, status, error
```

Every `DeterminationRequest` references the run that produced it.

## ContentJob

Produced by the determination layer and consumed by the pipeline runner.

Conceptual fields:

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

Rules:

- Determination creates a `ContentJob`.
- A job is an explicit recipe for one selected pipeline, not generated content.
- A job retains its candidate and determination-handoff provenance when it was
  created from the persisted production path.
- Determination chooses `visual_profile_id` from the selected pipeline's
  registered profiles. Pipeline Gemini may refine it only from the same allowed
  set; deterministic code resolves the concrete template.
- The POC creates at most one job for an accepted trend. Future determinations
  may create multiple jobs for one trend.
- Determination does not call pipeline functions directly.
- `pipeline_id` exists even though the POC has only one real pipeline.
- The pipeline runner loads pending jobs from SQLite.

## ContentPackage

Produced by a selected content pipeline. It is the platform-specific content
and native metadata, with required asset/visual specifications. It is consumed
by visual rendering and, once all required assets are present, posting.

Conceptual fields:

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

The pipeline may use Gemini to generate platform-specific caption, tags, and
hashtags from the job recipe and content. It persists the generated metadata
and validates it deterministically against platform policy. Visual rendering
adds required final assets before the package is marked ready for posting. The
Posting Agent must not need to know how the content was
generated or modify its creative metadata.

Tags and hashtags are pipeline-owned channel metadata. The Posting Agent uses
the persisted values exactly as supplied; it never generates or changes them.

For `instagram_idiom_carousel`, `visual_spec` contains structured slides and
their resolved template IDs. The fixed idiom contract permits 5–8 slides with
the following types: `hook`, `explanation`, `use_case_monologue`, and
`use_case_dialogue`. Other `o2_english` formats must define separate contracts.

If Vertex configuration or access is unavailable, the metadata generation
boundary fails visibly. It must not silently replace AI-generated tags or
hashtags with hardcoded defaults.

For the o2 idiom format, the pipeline first persists only after both of these
pipeline-owned Gemini results have passed independent validation: structured
slide content, then native metadata derived from those slides. The metadata
call can be retried without calling the content generator again.

## ApiUsage

Produced as an append-only observability record after a successful external
Gemini call. It is associated with the handoff or content job that owns the
call; it is not handed to the next workflow phase.

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

For the active o2 POC, visual rendering is deterministic: one named profile,
four fixed slide templates, a neutral temporary palette, and `1080x1920`
dimensions. A brand palette and visual matrix are future work.

## PostRequest (Under Development)

Merged into PostRecord. See PostRecord below.

## PostRecord (Under Development)

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

## Dashboard Reporting

Each module should persist enough status and reporting data for the system
dashboard to show its state without importing private implementation details or
calling the module directly.
Conceptual reporting areas are:

```text
SystemOverview
DetectionReport
DeterminationReport
ProductionReport
VisualReport
PostingReport
SystemHealthReport
```

These reports should summarize statuses, counts, recent activity, pending work,
and failures. Exact report models can evolve during the POC, but the dashboard
must remain an observer rather than a workflow controller.

## Boundary Tests

At minimum, tests should cover:

- Observation stored correctly.
- TrendCandidate score and lifecycle calculated correctly.
- Candidate cooldown and atomic claiming.
- Selection creates at most one active handoff for the same candidate.
- Handoff payload contains candidate, evidence, history, and detection run ID.
- Handoff claim, completion, rejection, and failure states are persisted
  independently of candidate state.
- Source failure persisted without stopping other sources.
- TrendCandidate accepted by a fake determination consumer without Gemini.
- `Trend` stored correctly.
- `Trend` to `ContentJob`.
- `ContentJob` to pipeline execution.
- Pipeline to `ContentPackage`.
- `ContentPackage` to visual asset.
- AI-generated tags/hashtags stored in `ContentPackage` and deterministically
  validated against the target platform policy.
