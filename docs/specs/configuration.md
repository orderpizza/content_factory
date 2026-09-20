# Configuration Specification

**Document role:** Tier 2 current configuration contract.
**Owner:** Nonsecret source/capability policy and local composition settings.

## Releases and catalogs

The [Detection manifest](../../config/releases/detection.json) implements
[configuration_manifest_v4](../contracts/configuration-manifest-v4.schema.json).
It contains `canonicalization_v2`, local semantic resolver parameters,
`attention_v3` and `shortlist_v2`. Model identity/revision, similarity thresholds,
time windows, cluster/pair/group caps, CPU/batch limits and event-signal
vocabulary are configuration, not model guesses. [Detection](detection.md) owns
the algorithm.

`setup_development.py` creates the current schema and active release, disables
YouTube unless explicitly requested, and registers all five domains before
work can arrive. Each has enabled/generation-ready fixture capability and
synthetic Instagram/X bindings. Their readiness means **planning eligible**,
not delivery-ready. Remits are frozen from `workflow.catalog.DOMAIN_REMITS`.
Registration is immutable and idempotent only for matching input.

Determination captures the catalog at request creation. It does not re-read
readiness while deciding. Production final delivery separately rechecks actual
destination readiness. Never modify a queued request to switch catalog modes.

## Environment loading

Runtime entrypoints load repository-root `.env` before resolving settings.
Existing process environment values win; explicit CLI arguments win over both.
The loader accepts literal KEY=VALUE records, without interpolation or command
execution. Invalid input reports a line number, not secret content.
Fresh setup uses an explicit/default new path and does not inherit a potentially
incompatible existing database path.

`.env.example` is the tracked template; `.env` is ignored local configuration.
Restart processes after changes. Keep secrets out of manifests, logs and
conversations.

| Setting | Consumer / purpose |
| --- | --- |
| `CONTENT_FACTORY_DB_PATH` | Shared runtime SQLite path; development default data/development.db |
| `CONTENT_FACTORY_ARTIFACT_ROOT` | Renderer, dashboard asset boundary and storage monitor |
| `CONTENT_FACTORY_LOG_ROOT` | Local process diagnostic directory, default data/logs |
| `CONTENT_FACTORY_LOG_MAX_BYTES`, `CONTENT_FACTORY_LOG_BACKUPS` | Rotation: default 2,000,000 bytes and 3 backups per process; seven-day startup retention |
| `CONTENT_FACTORY_BACKUP_ROOT` | Maintenance and storage monitor; required for production runner |
| `CONTENT_FACTORY_DASHBOARD_HOST`, `CONTENT_FACTORY_DASHBOARD_PORT` | Loopback server, default 127.0.0.1:8787 |
| `GOOGLE_CLOUD_PROJECT`, `GOOGLE_CLOUD_LOCATION` | Vertex project/location |
| `GEMINI_MODEL` | Model ID; `VERTEX_AI_MODEL` is also accepted by the client |
| `GEMINI_INPUT_COST_PER_MILLION_USD`, `GEMINI_OUTPUT_COST_PER_MILLION_USD` | Explicit configured-model prices |
| `GEMINI_DAILY_WARNING_USD`, `GEMINI_DAILY_HARD_LIMIT_USD` | Shared model spending warning/hard cap |
| `GEMINI_JOB_HARD_LIMIT_USD` | Per-job generation + all adaptation attempts |
| `GEMINI_<PHASE>_MAX_INPUT_TOKENS`, `GEMINI_<PHASE>_MAX_OUTPUT_TOKENS` | Optional intake/determination/generation/adaptation phase maxima |
| `YOUTUBE_API_KEY` | Only enabled YouTube collection; disabled in default development setup |
| `CONTENT_FACTORY_FONT_PATH`, `CONTENT_FACTORY_FONT_SHA256` | Explicit reviewed production font and optional expected fingerprint |
| `INSTAGRAM_ACCOUNT_KEY` | Internal account label, not Facebook Page ID |
| `INSTAGRAM_USER_ID`, `META_GRAPH_API_VERSION` | Instagram Professional ID and Graph API version |
| `INSTAGRAM_ACCESS_TOKEN` | Instagram adapter credential |
| `R2_ACCOUNT_ID`, `R2_BUCKET_NAME`, `R2_PUBLIC_DOMAIN` | Nonsecret R2 staging configuration |
| `R2_ACCESS_KEY_ID`, `R2_SECRET_ACCESS_KEY` | R2 staging credentials |
| `X_ACCOUNT_KEY`, `X_USER_ID`, `X_USER_ACCESS_TOKEN` | Optional real X destination and user-context credential |

Planning requires Vertex/ADC and priced budgets, not R2, Instagram or X.
Google Application Default Credentials are resolved by the SDK; use a configured
local ADC credential or standard `GOOGLE_APPLICATION_CREDENTIALS`.

## Model admission

Every real `run_workflow.py --gemini` mode requires positive prices, daily and
job limits. Warning must not exceed the daily hard cap. Intake/Determination
have no ContentJob yet and count toward the daily budget, not the job budget.
Worst-case phase reservations occur before calls and settle against returned
usage; missing/uncertain usage does not silently release spend.

| Phase | Default maximum input / output tokens |
| --- | --- |
| Intake | 8,000 / 2,000 |
| Determination | 12,000 / 4,000 |
| Generation | 12,000 / 4,000 |
| Adaptation | 12,000 / 8,000 |

Adaptation's output allowance includes thinking and JSON. Gemini 3 adaptation
uses LOW thinking and temperature 1.0; local schema/metadata validation still
bounds acceptance. This is not an automatic paid retry policy.

## Production configuration

`configure_production.py` freezes five domain bindings, real destination IDs,
provider configuration, posting policy and approved renderer/font fingerprints.
Use `--disable-x` while X is on hold. `--help` lists required local choices.

The R2 public origin accepts an operator-selected HTTPS r2.dev origin for this
PoC; buying a custom domain is not a planning prerequisite. Meta uses the
configured graph.facebook.com API version. Current X delivery implements a
single native image/text post; threads are not supported.

Production rows are immutable. A changed catalog/account/profile intent needs a
new development database. Configuration and credentials never authorize a post:
exact dashboard review, current readiness, admission and Post now are separate.

The credential diagnostic supports `--local-only` without network access.
Its short SHA-256 fingerprint is a comparison aid, never part of the actual
token sent to Meta. `INSTAGRAM_GRAPH_API_VERSION` is an accepted diagnostic
fallback; prefer `META_GRAPH_API_VERSION` consistently.
