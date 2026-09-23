# Configuration

**Owner:** Nonsecret releases, catalogs and operator-facing environment inventory.

## Releases and catalogs

[The Detection manifest](../../config/releases/detection.json) follows
[configuration_manifest_v4](../contracts/configuration-manifest-v4.schema.json).
It freezes source identities, HTTPS allowlists, cadence, lexical canonicalization,
local MiniLM model/policy and deterministic scoring/shortlist settings.
[Detection](detection.md) owns the algorithm and source roster.

Fresh setup registers exactly `english`, `ai_tech`, `psychology`, each enabled for
planning/generation with one synthetic Instagram binding. Readiness means planning
eligibility, not delivery authorization. Remits come from `workflow.catalog`.
Determination freezes its catalog at request creation. Registration is immutable
and idempotent only for matching input; use a fresh database for this baseline.
No schema migration or database reset is implicit.

## Environment loading

`.env.example` is the canonical tracked inventory of operator-facing variables.
Ignored `.env` holds actual local values with the same preferred keys. Entrypoints
load it before resolving settings: process environment wins over the file, and
explicit CLI arguments win over both. Restart processes after editing values.
The loader accepts literal KEY=VALUE records without interpolation or execution;
invalid lines report a number, never their secret value.

`VERTEX_AI_MODEL` remains an internal compatibility alias for `GEMINI_MODEL`;
only the preferred name is in the operator inventory. Internal Hugging Face
switches enforce offline loading and disable telemetry; they are not operator
settings. `scripts/check_docs.py` checks code lookups against this inventory.

## Model admission

Every `--gemini` runner mode requires positive text-model prices and finite daily
warning/hard and job limits. Image rendering has its own prices but shares the
same daily/job ledger. Prices are operator input, not inferred defaults.

| Variables | Meaning |
| --- | --- |
| `GOOGLE_CLOUD_PROJECT`, `GOOGLE_CLOUD_LOCATION` | Vertex connection; authenticate locally with ADC |
| `GEMINI_MODEL` | Text model identifier |
| `GEMINI_INPUT_COST_PER_MILLION_USD`, `GEMINI_OUTPUT_COST_PER_MILLION_USD` | Text model input/output prices |
| `GEMINI_DAILY_WARNING_USD`, `GEMINI_DAILY_HARD_LIMIT_USD`, `GEMINI_JOB_HARD_LIMIT_USD` | Owner spending limits |
| `GEMINI_IMAGE_MODEL`, `GEMINI_IMAGE_SIZE` | Storyboard model and supported request size; defaults retain 2K |
| `GEMINI_IMAGE_INPUT_COST_PER_MILLION_USD`, `GEMINI_IMAGE_OUTPUT_COST_PER_MILLION_USD` | Image-model accounting prices |
| `GEMINI_IMAGE_RENDERING_MAX_INPUT_TOKENS`, `GEMINI_IMAGE_RENDERING_MAX_OUTPUT_TOKENS` | Image reservation/response bounds, default 8000/8000 |

Optional `GEMINI_{PHASE}_MAX_INPUT_TOKENS` and
`GEMINI_{PHASE}_MAX_OUTPUT_TOKENS` override these phase defaults:

| PHASE | Input | Output |
| --- | --- | --- |
| INTAKE | 8000 | 2000 |
| DETERMINATION | 12000 | 4000 |
| GENERATION | 12000 | 4000 |
| ADAPTATION | 12000 | 8000 |

For Gemini 3 text models, Intake, Determination, Generation and Adaptation set
the provider thinking level to `LOW`; other text models receive no thinking-level
setting. Thinking and JSON share the output allowance. The tracked template
spells out every override. [Reliability](reliability.md#gemini-accounting) owns admission,
uncertain usage and the limits of input-token estimates.

## Local composition

| Variables | Meaning |
| --- | --- |
| `CONTENT_FACTORY_DB_PATH` | Shared database path |
| `CONTENT_FACTORY_ARTIFACT_ROOT`, `CONTENT_FACTORY_BACKUP_ROOT` | Local assets and explicit maintenance backups |
| `CONTENT_FACTORY_DASHBOARD_HOST`, `CONTENT_FACTORY_DASHBOARD_PORT` | Loopback server; defaults 127.0.0.1:8787 |
| `CONTENT_FACTORY_FONT_PATH` | Optional font for transparent image overlays |
| `CONTENT_FACTORY_LOG_ROOT`, `CONTENT_FACTORY_LOG_MAX_BYTES`, `CONTENT_FACTORY_LOG_BACKUPS` | Safe rotating diagnostic logs |
| `R2_ACCESS_KEY_ID`, `R2_SECRET_ACCESS_KEY` | Preserved inactive R2 relay credentials; never needed for review |

R2 bucket/account/public-origin inputs remain explicit relay configuration, with
no active provider setup CLI. They are not unused environment placeholders.
