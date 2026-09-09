# Audit action register

**Updated:** 2026-09-10

**Agreed scope:** finish current detection/dashboard and local-scaffold repairs;
retain unbuilt production stages in the implementation plan.

Resolved findings are removed from this active list. Original evidence and closure
notes remain in [audit history](docs/archive/audits/repository-audit-2026-09.md).
Unbuilt features are mapped by audit ID in the
[implementation plan](docs/plans/target-implementation.md#audit-to-plan-disposition),
not marked fixed or implemented.

## Genuine review and rollout items

### 1. Choose the development-data rollout

The approved hybrid scoring and corrected normalization are implemented and tested.
No runtime database was migrated, replaced, created or switched.

- **Continue existing handoffs:** back up/migrate the exact database and activate
  `detection-hybrid-v2`. Scoring is corrected; historical normalization remains.
- **Start a separate normalized experiment:** choose a new filename and use
  `setup_normalized_detection.py`. Hybrid scoring and corrected title/URL matching
  are enabled there. The original DB and handoffs remain untouched, but its
  conversations/history do not automatically appear in the separate experiment.

For development, the second option enables the corrected behavior without rewriting
old identities. Cross-normalization activation is refused in both directions.
Do not erase the original database or treat the new experiment as a production
history migration. See [rollout instructions](docs/current-state.md#normalized-detection-experiment).

**Your decision:** which database should become the active development runtime,
and whether to continue the existing queue or start the isolated experiment.
No credentials are requested.

### 2. Authorize actual-runtime acceptance

Locked dependencies and the installed-wheel migration path are verified on Windows,
not on the Mac Mini. Before rollout, review the exact deployment/database paths and
authorize separately scoped Mac/launchd and source-provider acceptance. A source
smoke test must not enable Gemini, public posting or retired retention.
Provider/configuration availability is assumed, not diagnosed as missing.

### Later human gates

When the corresponding planned stages exist, review editorial route/claim quality,
concrete account/model/budget/profile releases, and exact content for each destination.
These are not current requests to approve nonexistent implementation artifacts.

## Follow-up repairs — 2026-09-09

Current-slice repairs cover reproducible scoring/evidence, bounded typed source
inputs, versioned title/URL normalization, guarded configuration activation,
local claim/cancellation/command safety, bounded dashboard tracing/refresh validation,
retired unsafe legacy side effects, dependency locking and packaged canonical SQL.

`canonicalization_v2` requires an explicitly created separate database. Historical
serializers/scores were not relabeled or rewritten. Production workers, reuse/
recurrence, browser commands, real rendering, exact approval/posting and maintenance
remain unbuilt where [Current state](docs/current-state.md) says so.

### Verification

Final checks, rerun after resuming on 2026-09-10:

- `py scripts/run_tests.py`: **131 tests passed**, including installed-wheel and
  fresh-database CLI refusal/migration regressions.
- The same suite passed in a separate locked Windows environment with socket
  `connect`/`connect_ex` blocked. No existing environment was replaced.
- `uv lock --check --offline`, `py scripts/check_docs.py` and `git diff --check` passed.
- A 10,000-worker-row fixture returned only the latest 50 rows and under 100 KB
  of HTML; one measured local render took about 17 ms. Source lookup uses an index.
  This is bounded reporting evidence, not production-load acceptance.
- Applied v1/v2 SQL and the original release manifest remain unchanged. Corrected
  normalization has a new configuration schema/release; no historical rewrite.

Tests use temporary databases and provider fakes. Dependency resolution/install
reads PyPI; no live content-source, Gemini, Meta/X/R2 or public-delivery request
was made. No service or actual runtime database was activated. Generated egg-info
metadata remains excluded from source control and is recoverable from Git.

## Report maintenance

Keep unresolved findings and genuine review/rollout items here. Close a defect only
with a fix and proportionate verification, or an explicit retirement/scope disposition.
Retain compact closure evidence in audit history; do not use the architectural
decision archive as a repair log. Future features remain in the implementation plan.
A regression creates a new active finding.
