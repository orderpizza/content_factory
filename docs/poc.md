# Content Factory POC

## Objective

Prove that the system can automatically discover something interesting, decide
what content to create from it, execute a predefined content workflow, and
render upload-ready visual assets, then publish through the Posting Agent.

The POC must demonstrate this flow:

```text
Trend Detection
  -> Trend Candidate
  -> Determination Request and Decision
  -> ContentJob (explicit production recipe)
  -> One Content Pipeline
  -> Platform-specific ContentPackage
  -> Visual Rendering
  -> Ready ContentPackage
  -> Post Queue
  -> Posting Agent
  -> Publication Record
```

## Scope

- One deterministic Scout/detection implementation.
- A small number of free trend sources.
- One determination process.
- One current end-to-end content pipeline target: `o2_english_instagram`.
- One fixed initial `o2_english` format: a 5–8-slide 1080×1920 idiom carousel.
- One fixed deterministic visual profile with four slide-template variants.
- One primary font/theme configuration.
- One accepted trend produces at most one `ContentJob` in the POC.
- Posting Agent design and live platform integration are under work; they are
  required to complete the current o2 English end-to-end target.
- SQLite database.
- Mac Mini as the primary runtime.
- Gemini API for determination and content generation where useful.
- One read-only system dashboard, initially focused on trend detection.

The detector remains independently observable and does not use Gemini or any
other LLM API. The production determination worker uses Gemini only after it
receives a persisted detection handoff.

Vertex Gemini access is isolated in one client shared by the determination and
pipeline-owned generation boundaries. If local configuration or IAM access is
unavailable, those workers fail clearly rather than fall back to hardcoded tags
or hashtags.

The active `o2_english_instagram` pipeline has a fixed idiom-carousel schema
and four deterministic slide templates. Other English-education formats,
including usage comparison, are future pipeline formats with their own
contracts.

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
observability. This is the initial `Trend Detection` view of the system
dashboard. Downstream views should be added as the corresponding POC modules
are implemented.

## Detection Work Remaining Before Determination

- Improve semantic clustering/classification as source coverage grows.
- Expand source adapters while preserving the common observation contract.
- Carefully revise scoring, baselines, and source weights using observed data.
- Tune lifecycle thresholds from real multi-run history.
- Add candidate cooldown and downstream claim behavior to operating policy.
- Observe the Scout for several days on the Mac Mini.
- Run retention maintenance separately: keep 90 days of detailed detector
  data, archive older records as compressed JSONL, and preserve monthly
  topic/source summaries for long-term history.
- Store the full scored history for observability, but mark only a configured
  top-N shortlist that passes the minimum score as `pending_determination`.
  Initial defaults are top 5 and minimum score 0.25.
- Create one frozen `DeterminationRequest` per eligible candidate, including
  candidate metadata, source evidence, trend history, and the producing
  detection run ID. Do not create a duplicate active request on every Scout
  cycle.

Clustering and scoring are high-impact because their output directly controls
which candidates the downstream determination layer consumes.

## Success Criteria

The current POC succeeds when the system can complete the o2 English
end-to-end loop with minimal manual intervention:

1. A trend appears.
2. The system detects and stores it.
3. Gemini evaluates whether content should be created.
4. The decision either rejects the trend or stores one explicit `ContentJob`
   selecting the POC pipeline, target platform/account, format, audience, and
   creative brief, including a high-level visual profile.
5. The POC pipeline executes.
6. A platform-specific `ContentPackage`, including its content, caption, and
   Gemini-generated tags/hashtags, is generated. The pipeline may refine the
   selected visual profile from its allowed choices; deterministic code resolves
   the concrete visual template.
7. Required visual assets are rendered and the package is recorded as ready for
   posting.
8. The Posting Agent queues it at its cadence-eligible time.
9. The Posting Agent publishes it to the configured o2 English Instagram
   account and stores a publication record.

The system must also be able to explain afterward:

- Which trend triggered the content.
- Which `ContentJob` was created.
- Which pipeline ran.
- What content was generated.
- Which caption, tags, and hashtags were generated and validated.
- When it was queued and published, with the external post identifier.

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
7. Validate the content and visual-rendering path.
8. Observe failures and improve.
9. Complete the Posting Agent and verify one o2 English publication.
10. Add other pipelines only after the o2 target is proven.
