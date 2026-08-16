# Content Factory POC

## Objective

Prove that the system can automatically discover something interesting, decide
what content to create from it, execute a predefined content workflow, render a
visual asset, queue or publish the result, and preserve publication history.

The POC must demonstrate this flow:

```text
Trend Detection
  -> Trend Candidate
  -> Determination
  -> ContentJob
  -> One Content Pipeline
  -> Content Package
  -> Visual Rendering
  -> Post Queue
  -> Posting Agent
  -> Published Content
  -> Publication Record
```

## Scope

- One deterministic Scout/detection implementation.
- A small number of free trend sources.
- One determination process.
- One real content pipeline: `poc_pipeline`.
- One deterministic visual template.
- One primary font/theme configuration.
- One posting platform initially.
- SQLite database.
- Mac Mini as the primary runtime.
- Gemini API for determination and content generation where useful.

The current work is intentionally paused before determination while the
detection layer is completed and observed independently. The detector does not
use Gemini or any other LLM API.

Current detection sources:

- Hacker News public API.
- Configured RSS/Atom feeds.
- Wikimedia pageview analytics.

## Trend Source Roadmap

This matrix records the current source plan. “Enabled” means the source is
available to the running Scout configuration. “Implemented” does not mean the
source is active; Reddit and YouTube adapters exist but require credentials.

| Source | Current status | Access | Cost | Priority |
| --- | --- | --- | --- | --- |
| Wikimedia | Enabled | Public API | Free | Core |
| Hacker News | Enabled | Firebase/API | Free | Core |
| NPR RSS | Enabled when configured | RSS | Free | Core |
| Reddit | Not enabled; adapter ready | Reddit Data API approval/OAuth | TBD | High |
| Google Trends | Not enabled | Trends data/API or other approved access | Potentially free | Very High |
| YouTube | Not enabled; adapter ready | YouTube Data API v3 | Free within quota | Very High |
| X | Not enabled | X API | Paid/usage-dependent | High, later |
| Instagram | Not enabled | Meta APIs | Mostly free, limited discovery | Low |
| Facebook | Not enabled | Meta Graph API | Mostly free, limited discovery | Low |
| TikTok | Not enabled | TikTok APIs | Commercial trend access problematic | Low |

This source roadmap is subject to access policies, terms of use, rate limits,
and cost changes. Credentials must be kept in `.env` and never committed.
Google Trends remains intentionally disabled until an approved, usable access
path is available.

The detector runs as a scheduled local process, stores observation history and
ranked candidates in SQLite, and exposes a read-only live dashboard for
observability.

## Detection Work Remaining Before Determination

- Improve semantic clustering/classification as source coverage grows.
- Expand source adapters while preserving the common observation contract.
- Carefully revise scoring, baselines, and source weights using observed data.
- Tune lifecycle thresholds from real multi-run history.
- Add candidate cooldown and downstream claim behavior to operating policy.
- Observe the Scout for several days on the Mac Mini.
- Store the full scored history for observability, but mark only a configured
  top-N shortlist that passes the minimum score as `pending_determination`.
  Initial defaults are top 5 and minimum score 0.25.

Clustering and scoring are high-impact because their output directly controls
which candidates the downstream determination layer consumes.

## Success Criteria

The POC succeeds when the system can complete the loop with minimal or no manual
intervention:

1. A trend appears.
2. The system detects and stores it.
3. Gemini evaluates whether content should be created.
4. A `ContentJob` is stored.
5. The POC pipeline executes.
6. A `ContentPackage` is generated.
7. A visual asset is rendered.
8. The content is queued for posting.
9. The posting agent publishes or schedules it.
10. A publication record is stored.

The system must also be able to explain afterward:

- Which trend triggered the content.
- Which `ContentJob` was created.
- Which pipeline ran.
- What content was generated.
- When it was queued.
- When it was published.
- What external platform post ID was recorded, if any.

## Out Of Scope

- Multiple content pipelines.
- Advanced trend prediction.
- Complex machine-learning trend models.
- Generic plugin architecture.
- Complex agent-to-agent architecture.
- Dynamic workflow generation.
- Kafka, RabbitMQ, Redis, Celery, or other distributed queues.
- Kubernetes.
- Cloud databases.
- Cloud workers.
- Large-scale vector databases.
- AI image generation for every asset.
- Visual template libraries.
- Multi-platform publishing.
- Multi-account publishing.
- Advanced posting optimization.
- Automatic model routing.
- Fine-tuning or custom model training.

## Development Order

1. Repository structure, configuration, and SQLite.
2. Trend collector/detector.
3. Trend to determination.
4. `ContentJob` persistence.
5. One POC pipeline.
6. Visual renderer.
7. Posting queue.
8. Posting agent.
9. End-to-end autonomous test.
10. Observe failures and improve.
