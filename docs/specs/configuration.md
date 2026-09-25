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

## Preserved production configuration

The inactive delivery catalog accepts a closed `production_configuration_v2`:
`policy_version`, `approved_by`, `approved_at`, `visual_configuration_approved`,
`destinations` and `bindings`. Registration freezes the configuration and copies
its visual approval into each output binding. Superseded configuration shapes
are rejected; this is not a migration path or a provider-enabling command.

`visual_configuration_approved` is a separate operator attestation that the
visual setup intended for the bound destinations has been accepted: account
visual identity, curated archetype set, prompt compiler, technical renderer
contract and local overlays. `approved_by`/`approved_at` identify the configuration
registration; they do not by themselves assert visual acceptance. A false visual
approval blocks the production catalog, Post now, delivery preparation and the
final-send check even when provider readiness is current. These are the preserved
delivery gates, not an additional approval for each selected archetype or post.
Exact post review and per-destination Post now remain separate requirements.
This flag is not an automatic comparison against visual-code fingerprints.
The active review-only workflow does not use this production approval gate.

Output bindings describe domain/destination/format and readiness. The technical
renderer contract is frozen once in VisualRecipe, not duplicated on the binding.
Production configuration contains no renderer-owned template or unused font
metadata. Active review overlays use `CONTENT_FACTORY_FONT_PATH` and the existing
local fallback-font sequence in `gemini_image_renderer.py`. No production JSON
font path is loaded and no font fingerprint is currently verified or recorded;
this cleanup does not introduce a font-attestation subsystem.

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

Live acceptance has a separate campaign envelope, owned by
[`acceptance/README.md`](../../acceptance/README.md). Its optional environment
limits are `LIVE_TEST_MAX_USD`, `LIVE_TEST_MAX_CALLS`,
`LIVE_TEST_MAX_IMAGE_CALLS` and `LIVE_TEST_MAX_CASES`. A finite positive USD
ceiling is required for live execution; CLI limits can tighten environment
limits. The `CONTENT_FACTORY_ENABLE_LIVE_GEMINI_TESTS=1` setting is only one
half of a separate acceptance double opt-in; `--live-gemini` is also required.
Neither setting changes production worker composition.

Optional `GEMINI_{PHASE}_MAX_INPUT_TOKENS` and
`GEMINI_{PHASE}_MAX_OUTPUT_TOKENS` override these phase defaults:

| PHASE | Input | Output |
| --- | --- | --- |
| INTAKE | 8000 | 2000 |
| DETERMINATION | 12000 | 4000 |
| EDITORIAL_PLANNING | 12000 | 4000 |
| GENERATION | 12000 | 6000 |
| ADAPTATION | 12000 | 8000 |

All text-stage output overrides must be positive integers no greater than the
code-owned `MAX_TEXT_OUTPUT_TOKENS` ceiling of 10,000. This is an architectural
invariant, not an environment setting or a default response size. An output
allowance is a hard provider/budget cap; prompts and schemas determine the
practical response length. The calibrated defaults above remain unchanged so
worst-case reservations do not increase. Future text stages may request more
headroom, up to this ceiling, when evidence supports it.

For Gemini 3 text models, Intake, Determination, Editorial Planning, Generation and Adaptation set
the provider thinking level to `LOW`; other text models receive no thinking-level
setting. Thinking and JSON share the output allowance. Adaptation retains its 8000-token
ceiling: dynamic v3 output is bounded at fourteen units; truncation fails validation.
Generation uses a 6,000-token default after bounded-evidence calibration found a
4,000-token truncation near the limit; the 6,000-token sample completed well
below its ceiling. A lower or higher ceiling should follow measured usage and
truncation checks. The tracked template spells out every override.
[Reliability](reliability.md#gemini-accounting) owns admission,
uncertain usage and the limits of input-token estimates.

## Local composition

| Variables | Meaning |
| --- | --- |
| `CONTENT_FACTORY_ARTIFACT_ROOT`, `CONTENT_FACTORY_BACKUP_ROOT` | Local assets and explicit maintenance backups |
| `CONTENT_FACTORY_DASHBOARD_HOST`, `CONTENT_FACTORY_DASHBOARD_PORT` | Loopback server; defaults 127.0.0.1:8787 |
| `CONTENT_FACTORY_FONT_PATH` | Optional font for transparent image overlays |
| `CONTENT_FACTORY_LOG_ROOT`, `CONTENT_FACTORY_LOG_MAX_BYTES`, `CONTENT_FACTORY_LOG_BACKUPS` | Safe rotating diagnostic logs |
| `R2_ACCESS_KEY_ID`, `R2_SECRET_ACCESS_KEY` | Preserved inactive R2 relay credentials; never needed for review |

R2 bucket/account/public-origin inputs remain explicit relay configuration, with
no active provider setup CLI. They are not unused environment placeholders.
