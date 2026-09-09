# Configuration Control Plane Specification

**Document role:** Tier 2 target design contract. It defines the non-secret,
versioned configuration release and activation boundary; verify implementation
conformance from code and tests.
**Owner:** Local Configuration Operator, repository manifests, validation,
activation, and configuration audit.
**Read this for:** Source instances, cluster aliases, capabilities, visual
profiles/templates, posting policies, teaching references, or non-secret runtime
policy. Read [the system guide](../system.md) first, then [the data model](data-model.md).

The current milestone manifest is
[`config/releases/detection-dashboard-v1.json`](../../config/releases/detection-dashboard-v1.json)
and its intended shape is defined by
[`configuration_manifest_v1`](../contracts/configuration-manifest-v1.schema.json).
That schema intentionally admits only the detection section required by the
current milestone. Later domain sections require a new schema version before
their release is activated; an unvalidated free-form component is forbidden.
Current activation uses the explicit validator in `src/detection/configuration.py`,
not a general JSON Schema runtime. V2 fixture capabilities are a separate local
demo exception, not an activated production domain/output configuration release.

The optional [hybrid release](../../config/releases/detection-hybrid-v2.json) uses
[`configuration_manifest_v2`](../contracts/configuration-manifest-v2.schema.json)
and `attention_v2`, requiring the explicit v3 safety migration. V1 remains
unchanged for historical operation/replay. Compatible logical source IDs and
identical source fingerprints retain scoring history; quota reservations are
counted across releases by logical source ID regardless of fingerprint changes.
Activation checks and writes are serialized. Fixture registration is immutable,
idempotent for identical input, and limited to the active release; reactivation
does not silently carry old fixture capabilities into a new release.

The [normalized release](../../config/releases/detection-normalized-v3.json) uses
[`configuration_manifest_v3`](../contracts/configuration-manifest-v3.schema.json):
hybrid `attention_v2` with corrected `canonicalization_v2`. It requires database
schema v3, not a new SQL migration. Activation rejects any database with a prior
validated release using another normalization version, in either direction.
Use `setup_normalized_detection.py --database <new-path>` to create an isolated
development database explicitly. Existing data/identities are never merged,
renamed, reset or copied into that experiment automatically. In-place historical
identity conversion is outside this repair; choose the rollout before switching
workers. Compatible same-normalization releases still share history normally.

## Purpose and boundary

Configuration is not a worker-local default and the dashboard does not edit it.
The Configuration Operator applies a reviewed, repository-local, non-secret
manifest through an explicit local command. Validation produces an immutable
`ConfigurationRelease`; activation makes one validated release effective for a
scope. Workers read the persisted activated release, then freeze its fingerprint
into every run/decision/package/delivery record that depends on it.

Secrets remain composition-root settings in the local environment or credential
store. A manifest may name a safe `secret_ref` such as `instagram_o2_token`,
but never contains a token, access key, account secret, signed URL, or private
media location.

Local entrypoints load an optional repository-root `.env` before resolving
their composition settings. An already-present process environment value always
wins, so launchd or an operator can override the file without editing it. The
loader accepts literal `KEY=VALUE` records only, performs no interpolation or
command expansion, and never logs values. A malformed file fails startup with
its line number but without echoing secret content.
This is implemented by versioned setup/detection/reporting and v2 demo commands;
legacy entrypoints do not uniformly use it. Explicit CLI paths override defaults.
`run_workflow.py` honors `CONTENT_FACTORY_ARTIFACT_ROOT` unless `--artifacts`
is supplied. Reporting-only settings and legacy environment names are cataloged
in [Current state](../current-state.md#configuration-actually-consumed).

The root [`.env.example`](../../.env.example) is the current implementation template
for this boundary. `GOOGLE_CLOUD_PROJECT` and `GOOGLE_CLOUD_LOCATION` compose
the Vertex connection; `YOUTUBE_API_KEY`, `INSTAGRAM_ACCESS_TOKEN`,
`R2_ACCESS_KEY_ID`, and `R2_SECRET_ACCESS_KEY` resolve named credentials;
`CONTENT_FACTORY_DB_PATH`, `CONTENT_FACTORY_ARTIFACT_ROOT`,
`CONTENT_FACTORY_BACKUP_ROOT`, `CONTENT_FACTORY_DASHBOARD_HOST`, and
`CONTENT_FACTORY_DASHBOARD_PORT` compose local process roots. The dashboard
host must be a loopback address. X authorization secret references must be
added to that template only with its verified provider implementation; no
credential values or guessed account names are required by this doc update.
Every other behavior-bearing value belongs in
the release: including model/version and budget, detection sources/scores,
source quotas, capability/destination IDs, Graph API version, R2 endpoint/
bucket/public domain, worker policy, retention, and visual profiles.

## Configuration release — `configuration_release_v1`

The initial POC uses one `global` scope. The model supports a future narrower
scope such as `pipeline:english` only when its precedence and
compatibility rules are explicitly added; it does not silently override global
policy.

One release is a canonical JSON manifest with a stable release name, schema ID,
SHA-256 fingerprint, and versioned domain sections. The current schema contains
only `detection`. Later schema versions may add:

- `detection`: source instances, source limits, cluster aliases, and scoring /
  shortlist versions;
- `capabilities`: the five domain IDs, domain/content contract versions,
  enabled state, editorial remit, and generation/reference prerequisites;
- `destinations`: stable platform/account identities and safe secret references;
- `output_bindings`: explicit domain-to-destination/format bindings, output
  contract and renderer compatibility versions, native validation policy,
  enabled state, and bounded fan-out intent;
- `rendering`: renderer providers, profiles, templates, themes, local font and
  asset fingerprints;
- `posting`: account/destination policy, public-media domain configuration, and
  safe secret references;
- `teaching_references`: approved internal O2 teaching assertions, with no
  source-attribution or copyright-content requirement; and
- `runtime_policy`: non-secret worker interval, lease/retry, backup, retention,
  and budget-policy values, including priced-required Gemini model/phase price
  snapshots, maximum input/output tokens, UTC-day thresholds, and any frozen
  per-job limits.

The release itself is immutable. Its validation outcome is exactly `validated`
or `rejected`; a rejected manifest is retained with safe diagnostics but cannot
be activated. A validated release materializes immutable domain records that
all name its `configuration_release_id`. Existing source instances,
capabilities, policies, aliases, profiles, and references are never edited in
place to represent a new release.

`configuration_activations` is the sole mutable pointer: `scope_key`, active
release FK, `status` (`active` or `superseded`), positive `row_version`, actor,
reason, timestamps, and command receipt FK. A partial unique index permits one
`active` activation per scope. Applying a release atomically verifies the
manifest, persists/materializes the validated release, supersedes the prior
activation, creates the new active activation, and records the operator command
receipt. Rollback means activating a previously validated release; it never
deletes history.

## Consumers and safety

Startup validates that an active global release exists and that required local
secret references resolve, but startup never writes, repairs, activates, or
silently changes configuration. A worker refuses a new claim that requires a
missing/invalid/stale configuration release. Existing claimed work keeps its
frozen release fingerprint; it does not switch policy midway through execution.

Detection runs freeze the activated source/scoring fingerprint. Intake freezes
the capability release in its routing input; Determination records it in the
decision/catalog snapshot. Jobs/canonical content freeze domain and model policies; OutputRequests and
AdaptationRuns freeze output bindings, native text policy, and rendering release;
packages/Render Runs retain that exact rendering release;
Post Requests/Records freeze the posting release. Readiness checks identify the
same release fingerprint they inspected. This makes a later activation visible
and auditable without rewriting historical decisions.

The dashboard is read-only for configuration: it shows active release name,
fingerprint, activation actor/time, validation diagnostics, affected
domains/scopes, and the last known readiness result. It may link an operator to
the local documented apply procedure but cannot activate, roll back, or edit a
manifest.

## Phase 1 registry validation and readiness

A future manifest schema must distinguish domain capability from output
binding/destination. Reject platform-suffixed pipeline IDs, duplicate bindings,
unknown domains, unresolved destination references, incompatible formats,
missing budgets/profiles, and implicit all-account fan-out. The domain catalog
does not require every account to be configured or every pipeline to be enabled.

Generation readiness is checked per domain/reference/model policy. Output
readiness is checked per configured output binding: adapter contract, verified
native text/media limits, local profile/font/assets, destination configuration,
and relevant safe provider checks. A blocked X binding must not make a ready
Instagram binding editorially irrelevant. Determination records blocked outputs
explicitly and freezes only eligible selected bindings into its output plan.

One activation does not reroute old decisions, regenerate canonical content, or
automatically adapt/publish it to newly added accounts. Existing jobs and outputs
keep frozen policies. Current safety/readiness may block a side effect, but
cannot rewrite historical creative or authorization.

## Acceptance direction

Implementation tests must prove that an invalid manifest never becomes active,
exactly one active release exists per scope, a restart does not mutate the
active release, a rollback preserves both activation records, secrets never
enter SQLite/manifests/logs, and a claimed run retains its originally frozen
fingerprint after a newer release activates.
