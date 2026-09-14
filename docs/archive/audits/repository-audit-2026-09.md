# Historical repository audit — September 2026

Historical evidence only. The [active audit](../../../audit_report.md) owns current actions; the [implementation plan](../../plans/target-implementation.md#audit-to-plan-disposition) owns future features. Earlier line references and statuses below describe earlier code snapshots.

# Repository audit — 2026-09-08

**Latest status:** [Follow-up repairs — 2026-09-09](#follow-up-repairs--2026-09-09).
The original findings and 84-test repair snapshot below are retained as historical
evidence, not the current outstanding-issues list. Use the follow-up for disposition.

## Scope, evidence, and verdict

Repository-wide static audit of source, entrypoints, schemas, configuration,
schedulers, tests, and documentation. Current code is evidence of current
behavior; target contracts remain requirements, not proof of implementation.
Initial worktree was clean. This report was written before behavioral repairs.
The final verification section records the subsequent changes and tests.

**Verdict:** a working deterministic ingestion/read-only dashboard slice, an
optional deterministic editorial handoff demo, and a separate legacy content /
publishing implementation coexist. This is not yet a production-ready or
unattended multi-domain content factory. The architectural direction is sound;
the immediate problem is incomplete boundaries and ambiguous operational routing,
not a need for distributed infrastructure.

Baseline: `py scripts/run_tests.py` passed **74 tests**;
`py scripts/check_docs.py` passed. Neither proves conformance of the target system.
Findings describe the pre-repair state unless noted. The
[final repair status](#final-repair-status-and-verification) distinguishes fixed,
partially mitigated and still-open items; an audit finding is not automatically
a completed fix.
Diagnostics used temporary databases and fake providers. No live database was
reset, no credentials were inspected, and no model, publishing, R2, or source
provider call was made for this audit.

## Actual system and repository map

| Area | Classification | Actual behavior / location |
| --- | --- | --- |
| Detection database/configuration | Implemented, with gaps below | `src/database/migrations.py`, `src/detection/store.py`, `configuration.py`; explicit v1 SQL and detection-only release activation. |
| Collection | Implemented, provider operation unverified here | `src/detection/collector.py`, `adapters.py`, `normalization.py`, `models.py`; NASA feed, Wikimedia daily report, YouTube chart, HN Top-100; persisted attempts/observations/health/quota evidence. |
| Scout / shortlist | Partial | `src/detection/scout.py`; deterministic scoring, snapshots and selected thread/Intake handoff exist; scoring/recovery/recurrence gaps remain. |
| Detection dashboard | Implemented compact read model | `src/dashboard/detection.py`, `scripts/serve_dashboard.py`; loopback GET-only HTML, filters, selected opportunities, feed and operations tables. |
| Editorial persistence | Partial scaffold | v2 SQL, `src/workflow/store.py`; messages, revisions, routes, jobs, canonical/output/package/render/review/post records exist. Presence of a table is not implementation of its full contract. |
| Editorial workers | Partial, local placeholders only | `src/workflow/workers.py`; string-based Intake, first-ready-domain routing, generic canonical text, one-card adaptation and HTML-only rendering. No Gemini or external delivery. |
| Human interface | Partial | CLI new idea/continuation; dashboard shows completed decisions and conversations. No browser idea/review/Post now commands or full branch trace. |
| Legacy content system | Legacy, still executable | `src/database/sqlite.py`, `intelligence/`, `intake/`, `determination/`, `pipelines/`, `visual/`, `posting/`, legacy dashboard renderer. Separate incompatible unversioned schema, O2/Bluesky lineage, real Gemini and Instagram/Bluesky adapters. Not connected to v2. |
| Scheduling | Partial | Collector/Scout launchd interval templates and kept-alive dashboard. Editorial workers are one-shot local demos, not supervised production workers. Maintenance template invokes legacy cleanup. |
| Production safeguards | Planned | Budget admission, durable model accounting, capacity/reuse, verified static assets, exact browser review, public-send fencing, reconciliation, storage/backup/restore workers. |
| Development tooling | Implemented, limited coverage | unittest discovery, structural docs checker, fake-provider tests; broad dependency ranges, no lock or complete semantic-contract test suite. |

Actual control flows:

1. Explicit setup → activated detection release → one-shot Collector → SQLite
   evidence → one-shot Scout → SQLite candidate/thread/Intake records → GET dashboard.
2. Explicit v2 setup → CLI human input or selected trend → placeholder workers
   in `run_workflow.py` → HTML preview and review row. The driver calls each
   worker once sequentially; one item can traverse several stages in one invocation.
3. Separate legacy commands → unversioned database → old Intake/Determination
   or direct legacy handoff → platform-bound job → O2/POC package → legacy renderer
   → automatic queue/public adapter. This is not the approved Phase 1 delivery path.

## Severity and repair order

Critical means a reachable path can cause unsafe public side effects. High means
major correctness, recovery, or implementation-readiness failure. Medium means
bounded operational/maintenance debt. Low means cleanup. A planned safeguard is
not falsely reported as a current production feature. Priorities below account
for the fact that v2 public delivery is disabled.

### Critical

#### C1 — Legacy public delivery bypasses exact review and can repeat a possibly successful post

- **Evidence:** `scripts/run_posting.py`; `scripts/smoke_test_o2_instagram.py:run`;
  `src/posting/agent.py:queue_ready_packages/publish_due`; `src/posting/instagram.py:publish_package`;
  `src/database/sqlite.py:start_post_attempt`.
- Ready legacy packages are automatically queued, without a ReviewRequest or
  exact Post now authorization. Broad retry classification includes transport
  timeouts and local persistence errors after a provider may have published.
  There is no durable final-send marker or `publication_unknown` boundary.
  `--live` smoke mode generates new content and publishes without reviewing those
  exact generated bytes. Database duplicate keys do not prevent retrying a remote success.
- **Impact:** unreviewed or duplicate public content if these commands are used
  against a legacy database with credentials. This is a reachable legacy risk,
  not evidence that the safe v2 placeholder actually published anything.
- **Action:** retire/quarantine these entrypoints before any live operation;
  implement the versioned authorization, send marker, uncertainty and reconciliation
  boundary with fake-provider crash tests before enabling a replacement.
- **Behavior:** yes; intentionally stops legacy delivery. Left open rather than
  silently changing a live-capable subsystem during an audit.

### High

#### H1 — Scout retry does not preserve its complete frozen evaluation boundary

- **Evidence:** `src/detection/scout.py:run/_freeze_inputs`.
- A frozen empty attempt list is mistaken for an unfrozen input. Injecting failure
  after freezing an empty database, then retrying, reproduces a unique-constraint
  failure on `scout_evaluation_inputs`. Nonempty retries reuse IDs but calculate
  windows/freshness using the retry's current time. Freeze updates also lack owner/version fencing.
- **Impact:** stuck or non-reproducible evaluations after restart.
- **Action:** recognize persisted freeze completion independently of row count,
  preserve the original evaluation clock, fence the freeze transaction, and test
  empty/nonempty retry and stale ownership. **Behavior:** yes, recovery only.

#### H2 — Completed Wikimedia reports are excluded from current scoring

- **Evidence:** `src/detection/adapters.py:_collect_wikimedia` timestamps a report
  at the preceding day's midnight; `collector.py:_finalize_success` retains that
  effective time; `scout.py:_evaluate` uses a trailing `now - 24h` current window.
- **Reproduction:** a complete Sep 7 report collected Sep 8 at noon stores an
  observation but yields **zero candidates** in a Wikimedia-only fixture.
- **Impact:** one of four configured source kinds cannot supply its normal current
  contribution. The feed can look healthy while the scoring input is absent.
- **Action:** agree and freeze completed-day versus live/trailing-window semantics,
  then version the scoring correction and add source-specific boundary fixtures.
  Do not retimestamp historical evidence or silently rewrite applied `attention_v1` history.
- **Behavior:** yes; changes scores/selection. Requires policy clarification (D1).

#### H3 — Score health/history and evidence do not fully implement the stated formula

- **Evidence:** `src/detection/scout.py:_input_state/_evaluate/_source_activity`.
- `reused` late data receives reliability 1.0 rather than degraded 0.5;
  independence-group breadth and bootstrap eligibility include members even when
  their source is unavailable. Historical validity is inferred from observations
  by source kind, not complete healthy source windows (valid empty days disappear).
  HN activity is not rounded before ranking as specified. Wikimedia activity is
  summed without a report/article dedup guard. Full prominence populations are not frozen.
- **Impact:** rankings, history readiness and eligibility can be wrong or difficult
  to reproduce; unavailable corroboration can help qualify an opportunity.
- **Action:** golden score fixtures for healthy/degraded/absent/empty days,
  repeated reports, ties and independence groups, then a versioned algorithm repair.
- **Behavior:** yes; editorial admission changes. Open.

#### H4 — Collection can mutate evidence already frozen by Scout

- **Evidence:** `src/detection/collector.py:_resolve_activity_contributor` updates
  older `trend_observations.activity_contributor` and appends events to completed
  attempts when a lower-ID source becomes the contributor. Scout freezes attempt
  IDs and rereads their observations rather than immutable evaluation contributions.
- **Impact:** retrying the same frozen input can score different data even after H1.
- **Action:** make contribution selection evaluation-local/frozen, or introduce a
  versioned immutable contribution record. Preserve prior observation and snapshot history.
- **Behavior:** yes; persistence/scoring boundary. Open.

#### H5 — Provider retry parameters and undated-feed freshness are not frozen

- **Evidence:** `adapters.py:_collect_wikimedia` chooses yesterday from wall time
  on every execution; `collector.py:_materialize_attempt` freezes generic source
  options, not that resolved date. `parse_provider_time` falls back to each new
  collection time, not the logical item's first observation.
- **Impact:** a midnight retry of the same attempt can request a different report;
  repeatedly returned undated items can look perpetually fresh.
- **Action:** persist resolved request date/parameters before network work and
  first-observed fallback keyed to the logical item; test midnight and repeated feeds.
- **Behavior:** yes. Open.

#### H6 — Versioned workflow claims can remain stuck indefinitely

- **Evidence:** `src/workflow/store.py:claim/_finish_claim`, all `run_once` methods
  in `workers.py`. Claiming does not reclaim expired claimed/running rows or
  enforce attempt limits; exceptions generally leave the request claimed.
- **Impact:** process crash or invalid input strands the local workflow. Fencing
  columns alone do not implement recovery. V2 also lacks worker heartbeats/runs.
- **Action:** implement bounded stage-specific recovery/failure outcomes and
  crash/fence tests before adding paid work. Keep uncertain model calls nonretryable.
- **Behavior:** yes. Open; not repaired with a generic unsafe reset.

#### H7 — Cancellation does not fence every downstream finalization

- **Evidence:** `store.py:complete_intake` marks a cancelled request then raises
  inside the same transaction, rolling that update back. `record_decision`,
  `create_canonical`, `create_package`, `complete_render` lack thread-cancellation checks.
- **Impact:** cancelled work can remain claimed or create additional descendants.
- **Action:** transactional terminal cancellation without rollback-by-exception;
  test cancellation against every finalize boundary. Browser cancellation itself is planned.
- **Behavior:** yes. Open.

#### H8 — Placeholder approval is not a safe production authorization service

- **Evidence:** `store.py:approve_review`; v2 `review_requests`/`post_requests`.
  `command_id` is unused. The method checks status/version but not expiry,
  physical assets, package/manifest hashes, placeholder eligibility, cancellation,
  destination readiness or cadence. A temporary fixture with expiry in 2000 was accepted.
- **Impact:** invalid authorization rows can be created; retries do not return
  their original command result. Actual v2 external delivery remains disabled.
- **Action:** keep this demo-only; implement exact immutable review binding and
  command receipts with rejection/race tests before browser Post now or delivery.
- **Behavior:** yes. Open.

#### H9 — Capability catalog mixes configuration releases and fixture readiness

- **Evidence:** `store.py:register_capability/catalog`; `scripts/enable_placeholder_route.py`.
  Fixture capabilities are appended to a detection-only release after activation.
  Catalog reads all releases, takes the first domain's enabled/readiness state,
  and combines bindings across versions. Readiness is a supplied boolean, not a dated check.
- **Impact:** a new disabled release may not disable a domain; jobs may combine
  stale outputs and unrelated release policy. Currently confined to the demo path.
- **Action:** separate fixture capability scope from production configuration;
  freeze one validated active domain/output release and typed readiness snapshot.
- **Behavior:** yes. Open.

#### H10 — Identity labels overstate duplicate prevention

- **Evidence:** `store.py:coverage/record_decision/create_canonical/create_package`.
  Coverage omits NFKC and component percent-encoding despite labeling itself v2.
  Content identity hashes the entire recipe including outputs; platform changes
  therefore alter canonical identity. Domain-angle reservations, canonical reuse
  links and final public-payload suppression are not implemented.
- **Impact:** equivalent coverage may split; unchanged canonical content may be
  generated again; exact identity collisions can raise rather than reuse, stranding a claim.
- **Action:** versioned serializers, collision fixtures, explicit reuse and output
  identity guards. Do not rewrite persisted identities in place.
- **Behavior:** yes. Open.

#### H11 — Trend-to-editorial evidence and recurrence are incomplete

- **Evidence:** `workers.py:IdeaIntakeWorker` reads the mutable candidate rather
  than resolving the selected frozen topic snapshot; `store.py:complete_intake`
  closes collision seeds without the required evidence/message link and returns
  an owner thread ID in a revision-result path. `record_decision` never records
  candidate consumption/rejection/cooldown; Scout preserves those states but does
  not implement the documented material-evidence recurrence.
- **Impact:** briefs may describe later evidence, collision input is not visibly
  redirected, and the agreed 72-hour-plus-material-change policy is not operational.
- **Action:** complete the frozen evidence, collision result, consumption and
  recurrence handoffs together with lineage tests. Cooldown alone must never permit duplicates.
- **Behavior:** yes. Open.

#### H12 — Five route rows do not mean five-domain intelligence exists

- **Evidence:** `workers.py:IdeaIntakeWorker/DeterminationWorker/PipelineRunner/AdaptationWorker`;
  `store.py:record_decision`; `docs/contracts/editorial-workflow-schema-v2.sql`.
  Intake uses a character-length heuristic; Determination chooses the first ready
  domain, at most one. Production emits generic placeholder fields. SQL checks
  JSON syntax, not the new semantic payload contracts. Only route membership/count
  is validated before decision persistence, not aggregate/angle/catalog/output consistency.
- **Impact:** demo success can be mistaken for routing/content readiness; malformed
  or contradictory payloads can be persisted by future callers.
- **Action:** label placeholders clearly; implement typed contracts and positive/
  negative semantic fixtures before model integration, English first, then other domains.
- **Behavior:** yes for implementation; documentation clarification is nonbehavioral. Open.

#### H13 — Paid legacy model calls have no enforceable cost boundary

- **Evidence:** `src/common/gemini.py:generate_json`, legacy Intake/Determination
  and O2/POC generators. Usage is recorded after successful parsing/validation;
  errors can lose incurred usage. No pre-call durable reservation, uncertain-cost
  recovery, enforced daily/job caps or bounded per-phase output tokens.
- **Impact:** retries/crashes can incur untracked or repeated costs. V2 makes no model calls.
- **Action:** shared invocation/reservation boundary and invalid-response/crash
  fixtures before porting Gemini into v2. Do not treat `api_usage` as that ledger.
- **Behavior:** yes; may block paid calls. Open.

#### H14 — Neither rendering path provides the new reviewable delivery contract

- **Evidence:** `workflow/workers.py:VisualRenderer` writes/overwrites one HTML
  file with nominal 1×1 dimensions; `visual/o2_english.py` reuses an existing PNG
  by path alone after rewriting HTML; `database/sqlite.py:mark_package_rendered_assets`
  considers only asset count; `posting/instagram.py` converts assets to JPEG at send time.
- **Impact:** stale/invalid images can be considered ready, and public bytes differ
  from earlier previews. Neither path supplies verified immutable new-profile assets.
- **Action:** shared versioned renderer with local pinned fonts/runtime, atomic
  promotion/quarantine, full manifest/hash/layout validation and image regression tests.
- **Behavior:** yes. Open.

#### H15 — Legacy delivery resource and cadence handling remains unsafe

- **Evidence:** `posting/instagram.py` swallows cleanup errors, does not persist
  independent cleanup tasks or verify anonymous staged bytes; `posting/agent.py`
  and legacy `posting_policies` scope cadence by pipeline as well as account.
  Recent-post queries omit unresolved publishing/retry states. `start_post_attempt`
  reads eligibility before an unconditional update, without a claim fence.
- **Impact:** orphaned/deleted-too-early staging objects, inconsistent public bytes,
  quota multiplication and overlap hazards. No production conformance claim is warranted.
- **Action:** replace through the versioned posting boundary, not piecemeal reuse
  of the legacy queue. Prove account-scoped serialization and staging cleanup separately.
- **Behavior:** yes. Open.

#### H16 — Maintenance template is not the specified maintenance system

- **Evidence:** `scripts/com.contentfactory.maintenance.plist` invokes
  `cleanup_data.py` at 03:15 host-local time; that script opens the legacy DB and
  originally executes cleanup on import. It does not back up, verify restore,
  checkpoint safely, use a maintenance lock, or protect v2 retained lineage.
- **Impact:** installing all templates does not provide storage safety. Versioned
  databases fail the legacy schema initialization; legacy databases undergo deletions.
- **Action:** do not install that template as current maintenance. Make import
  harmless now; implement versioned online backup/restore before retention.
- **Behavior:** import guard only in this audit; full maintenance remains open.

#### H17 — Incomplete collections discard item-level audit evidence

- **Evidence:** `src/detection/collector.py:_run_source` passes only category/detail
  to `_finalize_failure` when `CollectionResult.complete` is false. Received valid
  items, rejection/exclusion events and response hashes are not persisted by that
  path; counts are only returned by the CLI. `_finalize_success` is the only path
  that writes item events.
- **Impact:** the attempts most in need of explanation lose the detailed evidence
  promised by the collection contract; malformed/partial HN/feed results are not
  fully inspectable. This is independent of whether incomplete items should score.
- **Action:** retain bounded attempt/execution-level rejection and completeness
  evidence without admitting incomplete results to scoring or overwriting retry
  history; add partial-response audit fixtures. **Behavior:** persisted audit changes. Open.

### Medium

#### M1 — Incompatible database families share defaults without explicit routing

- **Evidence:** versioned migrations versus `database/sqlite.py:initialize` and
  legacy `run_intake/run_determination/run_pipeline/run_visual_renderer/run_posting`.
  Both families default to `data/content.db`. Tests against v1/v2 reproduce
  `OperationalError: no such column: topic`; no added tables were observed.
  An additional empty `user_version=99` fixture was incorrectly initialized as
  legacy, confirming the need to reject unknown versions before DDL.
- **Action/impact:** reject versioned DBs before legacy DDL, document family
  boundaries and retain legacy fixtures separately. No verified corruption claim.
  **Behavior:** clearer fail-closed startup, not schema conversion.

#### M2 — Development rebuild is a move, not a verified backup

- **Evidence:** `scripts/setup_detection.py:_backup_legacy_database/main` moves DB,
  WAL and SHM separately, uses second-resolution names, and loads the manifest
  only after moving/creating the DB. No writer lock or backup integrity verification.
- **Impact/action:** an active writer or partial move can make recovery difficult;
  invalid manifests can leave a half-finished setup. Prefer validated inputs,
  stopped writers and SQLite online backup before explicit reset. Reapplying v1
  setup to v2 currently refuses rather than merely applying configuration.
- **Behavior:** yes; operator workflow. Open; no rebuild performed.

#### M3 — Canonicalization and malformed-input handling need adversarial fixtures

- **Evidence:** `detection/normalization.py:canonical_title` preserves substituted
  typographic apostrophes/dashes but removes their ASCII equivalents; `canonical_link`
  can raise on malformed ports/IPv6 and drops trailing/repeated slashes. Feed and
  chart adapters truncate some titles before typed rejection; feed 304 reuse is absent.
- **Impact/action:** equivalent titles split clusters, distinct URLs may collapse,
  one malformed item may fail an entire collection. Add a normalization/input corpus
  and version any identity-changing correction; test bounded rejection per item.
- **Behavior:** yes. Open.

#### M4 — Secret redaction and network validation are incomplete

- **Evidence:** `detection/adapters.py:_validate_public_https/_bounded_get`, HN
  error collection, Scout exception persistence, legacy provider error paths.
  There is no shared safe-error redactor. DNS is checked before a separately
  resolved urllib connection, leaving a rebinding gap; endpoint validation does
  not reject credential-bearing URLs. Allowlisting and bounded HTTPS reads do exist.
- **Impact/action:** hostile or misconfigured metadata/errors can retain sensitive
  text; network guard is not a complete SSRF boundary. Use typed bounded redacted
  diagnostics and bind address validation to actual connection/redirect handling.
  No real secret exposure or exploit was observed. **Behavior:** yes. Open.

#### M5 — CLI composition settings are inconsistent

- **Evidence:** `create_local_idea.py`, `enable_placeholder_route.py`, `run_workflow.py`
  do not load `.env`, unlike setup/detection/dashboard. The workflow driver ignores
  `CONTENT_FACTORY_ARTIFACT_ROOT`. Legacy modules read policy from env despite the
  target release-only rule; `.env.example` is not a legacy configuration reference.
- **Impact/action:** related commands can silently use different databases/roots.
  Align local v2 composition loading; document remaining legacy-only names without
  copying credentials or inventing production policy. **Behavior:** yes, settings consistency.

#### M6 — Dashboard opportunity counts multiply after thread continuation

- **Evidence:** `src/dashboard/detection.py` joins every Intake request for a
  selected thread into both candidate count and list queries, though the visible
  opportunity row uses only its thread ID.
- **Impact/action:** one selected candidate can appear several times and distort
  pagination after v2 replies. Remove the unused one-to-many join; add a continuation
  regression. **Behavior:** corrected reporting only.

#### M7 — The current dashboard hides important non-success states

- **Evidence:** `dashboard/workflow.py:render_workflow_trace` starts from completed
  decisions, so pending, failed and clarification-only threads are absent. No
  canonical/output/render/review/post trace or assets are exposed. Conversation
  history is unbounded and repeated for every decision. Detection intentionally
  displays selected candidates only, with no score/evidence drill-down.
- **Impact/action:** input can look lost and downstream failure can be invisible.
  Add bounded thread-first status/lineage views, then command UI. Keep the compact
  landing page but offer all candidate dispositions in a detail view.
- **Behavior:** yes. Open.

#### M8 — Dashboard freshness and performance claims exceed implementation

- **Evidence:** `detection.py` shows heartbeat state/timestamps without computing
  stale thresholds; meta refresh does not explicitly suspend while hidden. Its
  detection transaction is consistent, but the appended workflow trace is read
  afterward outside it. Startup/report validation runs full FK checks each request.
  `serve_dashboard.py` accepts `::1` although its default server is AF_INET.
- **Impact/action:** stale workers can appear idle; combined views can disagree;
  growing audit history increases query cost. Add status-age tests, bounded trace
  queries, actual supported loopback binding and measured query-plan/load checks.
- **Behavior:** yes. Open.

#### M9 — Conversation bound and command-concurrency contract are partial

- **Evidence:** `store.py:conversation_snapshot/continue_human_thread` bounds each
  message but not the total frozen conversation; revision context can exceed the
  documented 32,000-character invocation limit. Row version is optional and its
  precheck precedes the transaction's first write. Intake thread updates do not
  consistently increment row version. No browser CSRF/session commands exist.
- **Impact/action:** future model input can exceed policy; two clients can race
  stale intent. Implement bounded context and transactional compare-and-update
  receipts before browser commands. **Behavior:** yes. Open.

#### M10 — Legacy determination can lose work or ignore human brief constraints

- **Evidence:** `determination/service.py:consume_next_handoff` commits decision,
  job and completion separately; an existing decision is completed without repairing
  a missing job. `consume_next_request` evaluates reconstructed candidate/evidence
  rather than the full frozen brief; the catalog remains one platform-bound O2 route.
- **Impact/action:** crash can strand a decision without its job; rework constraints
  do not reliably influence routing. Retire rather than port this service unchanged;
  use v2 atomic boundaries with semantic fixtures. **Behavior:** yes. Open.

#### M11 — Legacy retention summary is mathematically incorrect and not crash-idempotent

- **Evidence:** `database/sqlite.py:archive_and_cleanup` uses the old row's
  `observation_count` in the average expression while assigning a new count;
  two values 10 and 20 produce 20 instead of 15. Archives append before DB commit.
- **Impact/action:** summaries are wrong; restart can append duplicate archive
  records. No archive checksum/restore validation exists. Replace under the new
  retention design; preserve old archives as legacy evidence. **Behavior:** yes. Open.

#### M12 — Startup resource handling and read-only URI construction have edge-case bugs

- **Evidence:** `DetectionStore`/`WorkflowStore` do not close connections if schema
  validation fails; `database/migrations.py:connect` interpolates an unescaped
  filesystem path into a URI. A `#` in a valid directory changes the parsed URI:
  the temporary regression opened an unintended schema-version-0 DB rather than
  the requested v1 DB, because the fragment also hid `mode=ro`.
- **Impact/action:** failed opens can retain handles; read-only reporting may fail
  on valid paths or create the wrong file. Close on validation failure and use a
  properly encoded file URI; the final regression also proves writes are refused.
- **Behavior:** bounded startup/path correction.

#### M13 — Dependency and installation reproducibility is not established

- **Evidence:** `pyproject.toml` has broad ranges/no lock; tracked
  `src/content_factory.egg-info/*` contains generated package metadata. SQL is
  loaded relative to a repository checkout rather than packaged resources. No
  installed-wheel smoke test, font bundle or new static-profile golden assets.
- **Impact/action:** clean installations may differ; an installed wheel is not
  proven equivalent to checkout execution. Declare checkout-only operation now,
  then lock a tested runtime and package migration resources if wheel use is wanted.
  No dependency vulnerability claim is made. **Behavior:** deployment only. Open.

#### M14 — Existing green tests are not the target acceptance suite

- **Evidence:** 74 baseline tests; only three in `test_workflow_v2.py`. Numerous
  tests validate old direct queueing, old O2 generation and legacy schema behavior.
  `check_docs.py` checks links/markers/table-name presence, not runtime conformance
  or v2 semantic constraints. Before the audit it did not require the v2 migration
  in its required list; that structural requirement is now added.
- **Impact/action:** architectural regressions can pass CI. Add negative schemas,
  multi-route/reuse/fan-out, stale-claim, repeated-command, cancellation, exact-asset,
  provider uncertainty and cost-reservation tests; label legacy coverage separately.
- **Behavior:** tests/tooling only. Open.

#### M15 — Release changes reset source continuity and validation has edge gaps

- **Evidence:** `detection/store.py:_materialize_detection` creates new source-row
  IDs per release; Collector quota sums and Scout history lookups use those IDs.
  Equivalent logical sources do not inherit prior-release daily quota/history.
  `configuration.py:validate_manifest` detects duplicate aliases only through its
  active-alias map, so duplicate inactive aliases can pass validation and then
  fail the SQL unique constraint. Source-policy numeric checks are handwritten
  and need equivalence tests against the schema (Python booleans are numeric).
- **Impact/action:** a harmless manifest update can reset bootstrap history and
  local quota accounting. Specify continuity for compatible logical source
  versions, then add cross-release and negative-manifest fixtures. Keep incompatible
  changes explicitly isolated. No rollout or quota reset was performed here.
- **Behavior:** yes; configuration/admission semantics. Open.

### Low

#### L1 — Repository hygiene and side-effectful utility imports

- **Evidence:** tracked egg-info; `.gitignore` covers DB files and `generated/`
  but not workflow `data/artifacts/`, archives, logs or configured backup roots.
  `scripts/dashboard.py` reads environment/DB and writes output on import;
  `cleanup_data.py` originally also deletes on import.
- **Action/impact:** use main guards; ignore only known generated local directories
  and document custom-root handling. Consider removing tracked egg-info separately
  after confirming build usage. **Behavior:** import safety; no deletion in this audit.

#### L2 — Legacy renderer/client cleanup and dense persistence code

- **Evidence:** generic `visual/renderer.py` lacks finally-close around browser
  work; `common/gemini.py` constructs a client without explicit close;
  `workflow/store.py` compresses transactions and SQL into long one-line statements.
- **Action/impact:** close owned resources on errors and expand touched transaction
  code for reviewability when implementing boundaries. Avoid a style-only rewrite.
- **Behavior:** resource lifecycle only. Open.

## Documentation drift and unresolved design conflicts

These are not permission to lower safety requirements to match legacy behavior.

| ID / priority | Conflict and evidence | Required resolution / behavioral effect |
| --- | --- | --- |
| D1 / High | Detection describes both a trailing 24-hour feed window and all scoring in completed UTC days; current Scout uses moving windows. | Decide current display/admission semantics for fast signals versus daily reports, baseline alignment and day-boundary inclusion. Version resulting scoring change; see H2/H3. |
| D2 / High | Runtime gives Posting a 4-minute maximum and 5-minute lease; Meta specifies polling each child then parent for up to 10 minutes. | Choose a bounded overall staging protocol/lease renewal or persisted staging continuation; a worker cannot honor both as written. |
| D3 / High | Runtime blocks new work until a normal storage sample, whereas Reliability permits posting/collection under some warning states. | Publish one action-by-storage-state matrix and make runtime reference it. Decide safe delivery treatment explicitly. |
| D4 / High | Posting expires approval if no attempt began in 48h; Data Model also requires expiry before the final request. | Clarify whether an already-started attempt retains authorization beyond 48h, including retries; test exact boundary. |
| D5 / Medium | Data Model calls attempts/resources/checks append-only and never state-mutated, but defines their lifecycle status updates. | Distinguish immutable payload from completion fields or append-only transition events. Do not implement conflicting immutability rules. |
| D6 / Medium | Reliability idempotency bullets describe path existence and content/platform/account uniqueness; later sections require verified hashes and publication identity. It also calls Determination input a handoff. | Update obsolete shorthand to the current exact guards without weakening the later rules. |
| D7 / Medium | `data/records.md` still primarily describes v1; v2 scaffold fields/statuses differ substantially from the target inventory (including waiting-capacity and production validation). | Explicitly route v1 and v2 executable contracts and document scaffold exceptions. Add future production schema versions, not edits to applied SQL. |
| D8 / Medium | `system.md` duplicates long handoff field lists, mentions a nonexistent `docs/sources/`, and originally says the driver advances one stage at a time. README dismisses source as architectural authority. | Separate as-built status/map/operations from target requirements. Keep the top-level guide short over time; link exact field owners. |
| D9 / Medium | Old JSON drafts are properly marked superseded, but the contracts README asserts producer/consumer validation universally; current workflow uses JSON syntax and ad-hoc dictionaries. | Say which validators actually run and gate future payloads. Presence of a JSON Schema file is not enforcement. |
| D10 / Medium | Platform outputs excludes platform/account from canonical identity; Posting says any destination or asset change requires a new content identity. | Use output/publication identity for distribution-only change, preserving canonical reuse; do not regenerate meaning for a new account. |
| D11 / Medium | Documentation claims a complete operational HAI and source evidence trace; only compact detection and completed-decision rows are implemented. README omits v2 demo; runtime says setup_detection is the only setup command. | Update current-state routing and command table; preserve full HAI as roadmap, not delivered UI. |
| D12 / Low | Some provider/profile references look precise but are draft/legacy, and source portfolio text still calls implemented registry code stale. | Keep dated verification/maturity visible and remove stale implementation-status wording. Provider validity was not reverified during this offline code audit. |

### Document-by-document assessment

| Document/group | Assessment |
| --- | --- |
| `README.md`, `AGENTS.md`, `docs/system.md` | Useful routing/target principles; need explicit current-state entry and code-as-evidence rule. Top-level map is too detailed. |
| `specs/detection.md` | Substantial real implementation, but formula/recovery/recurrence conformance overstated; D1 and H1–H5. |
| `specs/configuration.md` | Detection release implemented; domain/runtime/model configuration and uniform `.env` claims are not fully true. |
| `specs/data-model.md`, `specs/data/records.md` | Good identity/transaction direction; target inventory is not v2 DDL. Ambiguous immutability/expiry and duplication need correction. |
| `specs/idea-intake-and-determination.md` | Accepted target, not current Gemini/five-domain implementation. Coverage/rework/collision contracts mostly not fulfilled. |
| `specs/content-production.md`, `specs/platform-outputs.md` | Coherent target split; schemas, capacity, cost and native output contracts still gated. Not delivered production. |
| `specs/visual-rendering.md`, `profiles/editorial-clean-v1.md` | Target/legacy respectively; neither is the current placeholder renderer. New exact static profiles still needed. |
| `specs/dashboard.md` | Compact landing description is current; wider HAI is planned. Missing pending/failed threads is a functional gap, not just a doc issue. |
| `specs/runtime.md`, `specs/reliability.md` | Mainly future operational contracts; recovery, storage, backup and cost claims must not be used as deployment assurances. |
| `specs/posting.md` | Safe target, not legacy implementation. D2/D4/D10 require contract resolution before enablement. |
| `pipelines/domains.md` | Useful domain/evidence requirements; actual domain intelligence is not implemented. |
| `pipelines/o2-english-instagram.md` | Appropriately superseded compatibility router; retain old links. |
| `platforms/meta.md`, `platforms/x.md` | Provider references, not implementation status. Meta has timing conflict; X is explicitly unverified/draft. |
| `contracts/README.md`, `contracts/maturity.md`, SQL/JSON artifacts | Maturity separation is useful. Exact SQL is deployed; semantic JSON validation is not universal. |
| `plans/target-implementation.md` | Useful target sequence; must link current completion evidence rather than imply all prerequisites are satisfied. |
| `archive/decisions.md` | Historical rationale only; not a routine change log or implementation authority. Preserve useful history. |

## Architecture assessment

Keep SQLite, local processes, deterministic detection and the
canonical-content/output/delivery separation. Five domains do not require five
worker services, a message broker, cloud orchestration or a plugin framework.
The v2 transactions are a useful starting point, not a reason to replace the database.

The largest architectural debt is two incompatible persistence/workflow families
sharing names and operational defaults, plus fixture payloads carrying production
contract labels. Port boundary by boundary; do not connect the legacy publisher
to v2 approval rows as a shortcut. Prioritize inspectable failure states and exact
contracts over implementing the entire target inventory at once.

The docs' folder taxonomy is reasonable. Complexity comes mainly from repeated
field/state definitions and mixing target requirements with current behavior,
not from having several focused specifications. One current-state map plus one
target router is sufficient; avoid another competing architecture document.

## Safe repair scope for this audit

Apply only bounded fixes: Scout freeze recovery/fencing, dashboard candidate join,
v2 composition loading, explicit legacy schema refusal, startup connection/URI
safety, and import-safe utility entrypoints. Add focused regressions. Keep applied
SQL/checksums, identities, scoring policy, public delivery and live data unchanged.
Document unresolved architectural/policy decisions rather than guessing.

## Prioritized next actions

1. Quarantine/retire legacy public entrypoints (C1); do not enable delivery.
2. Resolve D1 and correct detection time/health/contribution semantics (H2–H5),
   with reproducible score fixtures and versioned rollout. Surface failures in UI.
3. Fix v2 recovery/cancellation and freeze production identities/payload schemas
   before further worker integration (H6–H12). Implement exact trend lineage and recurrence.
4. Add bounded thread-first dashboard views and safe new-idea/continuation commands.
   Make stopping states visible before growing the full portfolio interface.
5. Implement shared budget/usage admission and English canonical generation;
   then one verified static output/renderer/review path. Add the other domains
   and X through the same tested boundaries.
6. Resolve D2–D5/D10 and implement exact publication/cleanup/reconciliation safety,
   followed by separately authorized live provider validation.
7. Implement backup/restore/storage before retention/unattended operation; lock the
   tested runtime and expand cross-platform/load/security acceptance.

## Verification and remaining uncertainty

Live Gemini, NASA/Wikimedia/YouTube/HN requests, Meta/X/R2 operations, credentials,
provider entitlements/limits, real Playwright visual output, Mac launchd behavior,
live dashboard state, full concurrency/load and restore from an actual backup
were **not verified**. Their configuration is assumed available, not diagnosed as
missing. No live public or paid test is justified by this audit request.

## Final repair status and verification

| Findings | Final status and evidence |
| --- | --- |
| H1 | Fixed the empty freeze, evaluation-clock and freeze-owner/version defects. Three offline regressions pass. H4 still prevents claiming full immutable-input replay safety. |
| M1 | Fixed nonzero-version legacy initialization: v1/v2 dump equality and unknown-version/no-created-table regressions pass. Both code families still exist and must remain operationally separate. |
| M5 | Fixed `.env` loading in the three v2 demo composition roots and artifact-root handling. Mocked composition tests pass; legacy configuration remains separately documented. |
| M6 | Fixed candidate count/list join; one selected opportunity remains one row after thread continuation. |
| M12 | Fixed encoded read-only URI and connection close on validation errors. Unicode/hash/percent-path and validation-failure tests pass. |
| H16, L1 | Partial mitigation: cleanup/static-dashboard utilities now have main guards; known local artifacts/archive/backups/logs are ignored. No legacy cleanup, backup or tracked egg-info was deleted. Maintenance remains unimplemented. |
| M14 | Partial improvement: 10 new regression test methods; checker now requires current-state/v2 SQL and checks audit links. This is not the missing production acceptance suite. |
| D6, D8, D9, D11 | Documentation corrected: obsolete guard wording, duplicate top-level handoff detail, current/target authority, actual validation and operational routing. Missing UI/production behavior is still open under the associated findings. |
| D7, D12 | Scope/maturity clarified and stale registry wording removed. Production successor schemas and provider/runtime verification remain open. |
| All other findings; D1–D5 and D10 | Open. No scoring-policy decision, identity rewrite, production-schema rewrite or public-delivery change was made. |

Code changes are limited to `database/migrations.py`, legacy initialization's
version guard, DetectionStore/WorkflowStore constructor cleanup, Scout freezing,
the dashboard candidate join, and utility/demo composition roots. Applied SQL and
configuration manifests are unchanged. No deployment/service activation occurred.

Documentation created: `docs/current-state.md` (actual state, map, operations,
configuration and roadmap routing) and this report. Updated README/AGENTS/system
and the owning detection, records, dashboard, configuration, runtime, reliability,
contracts/maturity and plan documents. The top-level guide's long duplicate
handoff payload lists became a compact owner index; exact target requirements
remain in their specifications. No historical documents were removed.

Final local evidence:

- `py scripts/run_tests.py`: **84 tests passed** (74 baseline + 10 new regressions).
- The same suite also passed with socket `connect`/`connect_ex` blocked, verifying
  that this run did not depend on provider network access.
- `py scripts/check_docs.py`: passed, including the new current-state and audit links.
- AST parse: **98 Python files**; import check: **48 source modules**.
- Parsed **9 JSON files**, **4 launchd plists**, and `pyproject.toml` successfully.
- `git diff --check`: passed; no changes to applied SQL contracts.
- Focused pre-fix fault injection reproduced empty Scout retry failure, shifting
  retry clock, duplicate dashboard opportunity rows, invalid legacy startup,
  read-only URI misrouting, and missing composition loading. Unresolved probes
  reproduced a completed Wikimedia report yielding zero candidates and acceptance
  of an expired demo review. Legacy two-value retention average is confirmed
  incorrect; it was not changed because that path needs replacement, not activation.

These are Windows/local fixture results, not Mac/provider/load/visual-production
acceptance. The critical legacy publishing issue remains open and must not be
interpreted as repaired merely because offline tests are green.

## Follow-up repairs — 2026-09-09

This section supersedes the earlier repair-status table, not the original audit
evidence. The user authorized obvious repairs and explicitly selected **live fast
signals plus completed Wikimedia daily reports**. No live database was reset or
migrated, no service was activated, and no paid/provider/public-publishing request
was made. Existing v1/v2 SQL and the original release manifest remain unchanged.

### Repair disposition

“Fixed” applies to the named defect and tested local scope. “Mitigated” means the
unsafe path is disabled; it does not mean its production replacement exists.
“Partial” retains concrete technical work below, not an invented human decision.

| Finding | Current disposition |
| --- | --- |
| C1 | **Mitigated by retirement.** Legacy operational scripts and direct real Gemini/Instagram/Bluesky publishing boundaries refuse execution. The local placeholder approval method also refuses. Historical fake-provider algorithms remain only for compatibility tests; the approved public delivery protocol is not implemented. |
| H1 | **Fixed** empty freeze, frozen clock and owner/version fencing; retries keep exact inputs. |
| H2 | **Fixed in opt-in `attention_v2`.** Fast-source trailing live windows and latest complete Wikimedia report days coexist at midday. Empty newer reports do not resurrect older articles. Original `attention_v1` remains historical, not relabeled. |
| H3 | **Fixed scoring defects in v2; recurrence remains separate.** Frozen historical health, healthy empty-day zero baselines, unavailable/zero-trust exclusion, Wikimedia deduplication, six-decimal HN activity, sorted midranks, complete population evidence and evidence-derived last-seen time. Populations are stored once per run/source kind. |
| H4 | **Fixed.** Collection no longer rewrites old observations; each evaluation resolves contributors from its frozen inputs. Optional schema v3 also rejects observation/evidence updates. |
| H5 | **Fixed.** Wikimedia requests freeze their report date at materialization; retry does not use wall-clock yesterday. Undated stable items preserve their first observation time. |
| H6 | **Partial.** Expired local claims recover within attempt limits, stale/expired owners cannot finalize, and processing exceptions become persisted failures. Any recorded model invocation or expired delivery claim prevents automatic retry. Full production renewal/backoff/supervision is still implementation work. |
| H7 | **Fixed local finalization race.** Every scaffold stage checks parent thread status under its finalization transaction and cancels instead of creating children. This is not a complete browser cancellation interface or production side-effect protocol. |
| H8 | **Mitigated.** Placeholder HTML reviews cannot create PostRequests; exact manifest/profile/hash/expiry review must be implemented before enabling approval. |
| H9 | **Fixed fixture registration/catalog defects.** Identical registration is idempotent, conflicting immutable input is rejected, types/bindings are checked, and only the active release supplies the catalog. Production registries remain a separate deliverable. |
| H10 | **Open technical implementation.** Production coverage normalization, domain-angle reservations, canonical identity independent of destinations, and reuse need versioned persisted contracts and migration fixtures. Reuse is rejected by the scaffold rather than falsely represented as completed. No paid production path uses these fixture identities. |
| H11 | **Partial.** Intake now reads the exact selected topic snapshot and memberships; coverage collisions close the unused thread and persist an explicit redirect instead of returning an unrelated ID. Consumption, 72-hour cooldown transitions, material-evidence recurrence and collision event lineage remain unimplemented. |
| H12 | **Partial.** Determination validates five routes, aggregate outcomes, frozen catalog membership, ready selected outputs and output multiplicity. Full production semantic payload schemas/domain evidence and real workers remain unimplemented; placeholders are explicitly nonproduction. |
| H13 | **Mitigated.** The legacy real Gemini call is retired. Atomic budget admission/reservations and durable production invocation reconciliation still need implementation before paid work. |
| H14 | **Partial.** Existing preview directories cannot be overwritten and failures are persisted. Verified static assets, atomic artifact promotion/quarantine and exact reviewable manifests still need implementation. |
| H15 | **Mitigated.** Legacy real posting is retired; its cadence/retry/cleanup algorithms are not treated as the new Posting Agent. New delivery/cleanup/reconciliation remains technical work. |
| H16 | **Mitigated, replacement open.** Legacy cleanup refuses deletion. No backup/restore/storage/retention subsystem was fabricated or activated. |
| H17 | **Fixed for returned normalized responses on v3.** Safe per-execution items/events survive incomplete responses without becoming scoring observations. Raw bodies remain excluded. A provider operation that returns no normalized result has only failure/execution evidence. |
| M1 | **Fixed** legacy schema guard; database families remain deliberately separate. |
| M2 | **Mitigated.** `--rebuild` and the unsafe private file-moving helper refuse operation. Explicit setup accepts validated v1/v2/v3 without downgrade; safety migration refuses missing paths without creating a file. Backup-aware cutover tooling remains future work. |
| M3 | **Partial.** Malformed URL/port/userinfo inputs fail safely. Apostrophe/dash and path-sensitive identity changes require a versioned normalizer with collision/migration tests; existing identities were not rewritten. |
| M4 | **Partial.** Diagnostic URLs/tokens/secret assignments are redacted; typed boundaries avoid raw unexpected exception details. HTTPS connects only to validated public numeric addresses while verifying the original TLS hostname, and ignores environment proxies. This is not a complete sensitive-data/security audit. |
| M5, M6 | **Fixed** environment composition/artifact-root handling and duplicate opportunity joins. |
| M7 | **Fixed trace omission.** Bounded thread-first views show pending, clarification and failure states, conversation once, decisions/routes and downstream branches. Full portfolio filtering/pagination and command UI remain planned. |
| M8 | **Partial.** Dashboard sections share a read snapshot; loopback IPv6 works; hidden-page polling pauses; filter edits pause reload; stale heartbeat age is separate from reported state. Complete lease/backlog/storage-aware health and browser interaction acceptance remain open. |
| M9 | **Fixed.** Positive displayed thread versions are required; receipt/version checks are serialized. Canonical frozen conversation is bounded at 32,000 characters, with explicit failure rather than truncation. |
| M10 | **Mitigated.** Legacy operational Determination is retired. Its historical internal transaction protocol is not ported into production. Local v2 result/child handoffs remain atomic. |
| M11 | **Partial.** Historical weighted-average arithmetic is corrected. Legacy cleanup is retired; append/archive crash-idempotency is not a replacement for implementing safe maintenance. |
| M12 | **Fixed** read-only URI encoding and connection cleanup. |
| M13 | **Partial.** Removed tracked generated egg-info and ignored regenerated packaging artifacts. Runtime lock, wheel contract resources and clean Mac installation verification remain technical work. |
| M14 | **Improved, not complete.** Added focused offline safety/hybrid regressions. Missing production, visual, load and recovery acceptance cannot be replaced by unit-test counts. |
| M15 | **Fixed in hybrid/current validation scope.** Compatible releases share historical evidence; logical-source quota reservations survive activation; numeric booleans, duplicate inactive aliases, oversized registries and credential-bearing endpoints are rejected. Activation checks/writes are serialized. |
| L1, L2 | **Partial/fixed resource cleanup.** Utility main guards and ignores are in place; tracked generated egg-info is removed (recoverable in Git). Renderer browser closure uses `finally`; legacy external client calls are disabled. Broader runtime/package reproducibility remains open. |
| D1 | **Resolved by the user.** Hybrid policy implemented behind versioned manifest/scoring/schema rollout. No further scoring-window choice is outstanding. |
| D2 | **Resolved in contract.** Per-resource staging waits cannot extend the four-minute overall posting budget; timeouts are clipped to remaining budget. Implementation is still gated with the new Posting Agent. |
| D3 | **Resolved in contract.** Reliability owns one storage action matrix; Runtime links to it instead of contradicting it. |
| D4 | **Resolved in contract.** Final-publication marker must precede approval expiry; starting staging does not extend authorization. After a final request may have been sent, retain uncertainty/reconciliation behavior. |
| D5 | **Resolved in contract.** Immutable identity/input fields are distinguished from explicitly permitted lifecycle/completion fields. |
| D6, D8, D9, D11 | **Previously fixed, preserved.** Router ownership, authority and current/target distinctions remain explicit. |
| D7 | **Partial.** Optional v3/configuration v2 are registered separately; applied contracts stay immutable. Production successor payloads and forward migrations remain technical work. |
| D10 | **Resolved in contract; H10 implementation open.** Destination-only changes create new output/publication identity, not new canonical editorial meaning. |
| D12 | **Open verification gate.** Provider/runtime facts and concrete account access must be verified before enabling real integrations; credentials/configuration are assumed available. |

### Remaining technical work — dependency order

These are **not requests for the user to design code**. They remain implementation
work and must not be marked resolved merely because dangerous paths are disabled.

1. Complete versioned production payloads and identity/reuse reservations, including
   migration mapping for scaffold identities. Then implement consumption, cooldown,
   evidence-change recurrence and collision-event lineage (H10–H12, M3, D7).
2. Build shared invocation/budget/capacity admission and complete worker recovery;
   implement real Intake/Determination and domain generation against those boundaries
   (H6, H12–H13). Evaluate editorial quality with recorded fixtures before activation.
3. Complete static adaptation/rendering, manifest integrity and exact review, then
   browser commands using the persisted command boundary (H8, H14, M7–M8).
4. Implement explicit authorized delivery, uncertainty/reconciliation and cleanup.
   Do not reactivate the retired legacy publisher as a shortcut (C1, H15).
5. Build backup/restore/storage admission and crash-safe maintenance; package/lock
   the actual Mac runtime and exercise clean installation and restore (H16, M11,
   M13). Finish these before unattended operation, not after enabling publication.
6. Run boundary/concurrency/load, real-profile visual and separately authorized
   provider acceptance. Unit tests do not establish production readiness (M14, D12).

### Items that genuinely need human attention

- **Editorial acceptance:** confirm route/angle/claim quality from representative
  fixtures when real workers exist; fake “first ready domain” behavior is not an
  accepted editorial policy.
- **Concrete production activation:** approve the exact model/budget, account/output
  bindings and profiles in the production release. This is not a request to provide
  credentials or repeat already accepted architecture.
- **Deployment and live verification:** approve the concrete database backup/migration
  and separately scoped live provider/paid tests when ready. The current hybrid
  rollout is documented in [Current state](../../../docs/current-state.md#detection-database-setup);
  it has not been applied to the user's development database in this repair.
- **Public content:** every destination still requires exact human approval. No
  general audit/repair instruction authorizes posting.

No unanswered product-policy question blocks the completed local repair batch.
The incomplete target implementation is a technical backlog, not a hidden list
of decisions being delegated back to the user.

### Follow-up verification

Final follow-up checks:

- `py scripts/run_tests.py`: **118 tests passed** (34 more than the earlier repair snapshot).
- The same 118-test suite passed with socket `connect`/`connect_ex` blocked.
- Dashboard refresh visibility/input behavior passed in a Node VM with a simulated
  document/timer interface; this is not a real-browser visual acceptance test.
- `py scripts/check_docs.py` and `git diff --check`: passed.
- Applied v1/v2 SQL and the original v1 manifest have no diff. Optional v3 and the
  hybrid configuration are new files, not changes to deployed migration checksums.

Tests cover temporary SQLite databases and fake providers, not live deployment,
visual output, Mac runtime or public delivery. Generated `src/content_factory.egg-info/*` files
were removed from tracking; they are reproducible packaging output and remain
recoverable from Git history. No user database, artifact directory or backup was
deleted.


## Current-system closure after scope clarification

On 2026-09-09 the user chose current-system repairs and retained unbuilt production
stages in the implementation plan. This is a scope distinction, not production readiness.

- M3: corrected title punctuation, URL paths and day-scoped title-only fallback
  are versioned as canonicalization_v2/configuration manifest v3. Collection and
  hybrid scoring use the version consistently. Cross-version activation is rejected;
  separate explicit development DB setup preserves all original data/handoffs.
  Oversized/malformed fields are rejected rather than truncated; partial evidence
  survives. Unconditional feeds reject unexpected 304; conditional caching is future work.
- M4/L2: strict UTF-8/XML input, safe per-item diagnostics, typed chart rejection,
  error-stream closure and cross-host redirect header isolation supplement the
  existing pinned-address TLS/redaction fixes. This does not guarantee every possible
  security defect is absent.
- M8: HTTP snapshots check schema/checksums without rescanning every FK each refresh.
  Full integrity checks remain in setup/normal store validation; consistent snapshots,
  bounded traces and visibility/liveness behavior remain tested.
- M13/L1: uv.lock, pinned build tools, an isolated locked Windows install and a
  checkout-independent installed-wheel SQL/checksum/migration regression are added.
  A PEP 517 build-isolation failure was reproduced and fixed. Actual Mac/launchd and
  production font/profile acceptance remain deployment/future-stage gates.
- Previously closed finding groups retain their stated local scope. Production
  replacements and full production acceptance are mapped by original ID in the plan,
  not marked implemented. Retired unsafe entrypoints remain retired.

Final current-slice verification is recorded in the active audit. No runtime DB,
service, paid invocation, public post or user artifact was changed.
