# Content Factory POC

## Objective

Prove one inspectable autonomous loop: discover an interesting signal, decide whether to create content, persist an explicit recipe, execute one pipeline, render assets, and publish through the Posting Agent.

The permanent system responsibilities and handoff design are documented in [architecture.md](architecture.md), [interfaces.md](interfaces.md), and [system-flow.md](system-flow.md). This document records temporary scope limits and shortcuts.

## Active POC Constraints

### Runtime, infrastructure, and state

- The Mac Mini is the primary runtime.
- SQLite is the single persisted state store and handoff boundary.
- GCP is used for Vertex Gemini access only. Do not move the database, workers, scheduling, rendering, or queues to GCP for this POC.
- The system is local-first. Cloud databases, cloud workers, Kubernetes, and distributed infrastructure are out of scope.
- Secrets remain in a local `.env` file and must never be committed.

### Orchestration and job volume

- One scheduled local Scout/detection loop, one determination worker, and one simple polling pipeline runner are sufficient.
- Do not introduce Kafka, RabbitMQ, Redis, Celery, distributed queues, or direct module-to-module handoffs.
- One accepted trend may create at most one `ContentJob`.
- Transient posting-delivery failures use bounded retry and backoff through persisted attempts; sophisticated delivery orchestration is deferred.
- Configuration and package-contract delivery failures are terminal; only transient failures are retryable.
- The dashboard is read-only and is not a workflow-control surface.

### Active pipeline and publishing scope

- There is one active end-to-end pipeline: [o2 English Instagram](pipelines/o2-english-instagram.md).
- The POC supports one platform and one configured target account. Multi-pipeline, multi-platform, and multi-account publishing are deferred.
- Posting integration is limited to the implementation documented by the active pipeline. Advanced cadence optimization and approval workflows are deferred.
- Rendering uses deterministic code and a fixed initial visual profile. AI image generation and a broad template library are out of scope.

### Detection and determination scope

- Detection is deterministic, independently observable, and LLM-free.
- Enabled source types are Hacker News, configured RSS/Atom feeds, and Wikimedia pageview analytics.
- Reddit and YouTube adapters are implemented but disabled until credentialed; Google Trends is disabled pending an approved usable access path.
- Source failures are retried and stored as source-health records without stopping other sources.
- The initial shortlist is the top five candidates with a minimum score of 0.25.
- A candidate gets one frozen `DeterminationRequest` with source evidence, trend history, and producing detection-run ID; repeated Scout cycles must not create duplicate active requests.
- Gemini is used for determination and pipeline-owned generation. If Vertex configuration or IAM is unavailable, those workers fail clearly and never substitute hardcoded tags or hashtags.

### POC retention policy

- Keep 90 days of detailed detector data in the primary store.
- Archive older detailed detector rows as compressed JSONL under `data/archive`.
- Preserve monthly topic/source summaries in `trend_history` for long-term observation.
- Retain content and publication records for the POC audit trail.
- The current state model uses `trends`, `trend_observations`, `topic_snapshots`, `trend_candidates`, `detection_runs`, `determination_handoffs`, `determination_decisions`, `source_health`, `content_jobs`, `content_packages`, and `api_usage`; posting-specific records evolve only as needed for the POC loop.

## Current Detection Source Roadmap

“Enabled” means available to the running Scout configuration. “Implemented” means an adapter exists but may still need credentials.

| Source | Current status | Access | Cost | Priority |
| --- | --- | --- | --- | --- |
| Wikimedia | Enabled | Public API | Free | Core |
| Hacker News | Enabled | Firebase/API | Free | Core |
| NPR RSS | Enabled when configured | RSS | Free | Core |
| Reddit | Not enabled; adapter ready | Reddit Data API approval/OAuth | TBD | High |
| Google Trends | Not enabled | Trends data/API or approved access | Potentially free | Very High |
| YouTube | Not enabled; adapter ready | YouTube Data API v3 | Free within quota | Very High |
| X | Not enabled | X API | Paid/usage-dependent | High, later |
| Instagram | Not enabled for detection | Meta APIs | Mostly free, limited discovery | Low |
| Facebook | Not enabled | Meta Graph API | Mostly free, limited discovery | Low |
| TikTok | Not enabled | TikTok APIs | Commercial trend access problematic | Low |

This roadmap is subject to access policies, terms of use, rate limits, and cost changes.

## Work Remaining Within the POC

- Improve semantic clustering and classification as source coverage grows.
- Keep initial clustering deterministic and conservative; local semantic methods may be evaluated later without moving clustering into Gemini.
- Revise scoring, baselines, and source weights from observed data.
- Tune lifecycle thresholds, cooldown, and downstream-claim policy from real multi-run history.
- Observe the Scout for several days on the Mac Mini.
- Add source adapters while preserving the common observation contract.
- Verify one controlled live post after the required publishing credentials are configured.

## POC Success Criteria

The POC succeeds when, with minimal manual intervention:

1. A trend is detected and persisted.
2. Gemini records a determination that rejects it or creates one explicit `ContentJob`.
3. The selected pipeline persists a validated platform-specific `ContentPackage`.
4. Deterministic rendering creates required visual assets and records the package as ready.
5. The Posting Agent queues and publishes it at a cadence-eligible time, then persists a publication record with the external identifier.
6. The persisted records explain the triggering trend, job, pipeline, generated content and metadata, queue time, publication time, and external post identifier.

The implementation-specific acceptance criteria for the active pipeline are in [pipelines/o2-english-instagram.md](pipelines/o2-english-instagram.md).

## Out of Scope

- Multiple content pipelines or a generic plugin architecture.
- Advanced trend prediction or complex machine-learning trend models.
- Dynamic workflow generation or complex agent-to-agent architecture.
- Distributed queues, cloud workers, cloud databases, Kubernetes, or large-scale vector databases.
- AI image generation for every asset.
- Multi-platform or multi-account publishing.
- Automatic model routing, fine-tuning, or custom model training.

## Development Order

1. Repository structure, configuration, and SQLite.
2. Trend collection and detection.
3. Determination and `ContentJob` persistence.
4. One POC pipeline and visual renderer.
5. Validate generation and rendering.
6. Complete controlled publishing, observe failures, and improve.
7. Add other pipelines only after the active path is proven.
