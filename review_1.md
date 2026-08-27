# Content Factory — Extensive Review 1

Date: 2026-08-27  
Review type: architecture, implementation, persistence, operational safety, documentation, and test coverage  
Status: findings and recommendations only; no fixes are implemented by this document

## 1. Executive summary

The project has a sound overall architectural direction: deterministic trend detection, LLM use restricted to determination and pipeline-owned generation, persisted SQLite handoffs, platform-specific pipelines, a separate renderer, and a posting component that does not generate content. The documentation also communicates the intended responsibility chain clearly.

The current implementation is not yet safe for unattended or live publishing. The most serious risks are:

1. An existing development SQLite database can pass initialization but remain incompatible with the current `ContentJob` model.
2. A successful external Instagram publication can be retried if the subsequent local database update fails, potentially creating a duplicate public post.
3. Determination work can be stranded after exceptions because claims, evaluations, decisions, job creation, and completion are not handled as a recoverable unit.
4. A rejected candidate causes the determination worker loop to stop, leaving later work unprocessed.
5. Candidate cooldown is recorded but not enforced when new determination handoffs are created, and cooldown alone would not prevent repeated content after it expires.
6. Trend aggregation mixes incomparable raw source metrics, which lets large-count sources dominate ranking and conflicts with the documented normalization decision.
7. The active code and configuration still contain a legacy Bluesky pipeline, although the intended project scope is now Instagram o2 only.
8. Instagram publishing, renderer artifact reuse, configuration loading, stale-work recovery, and several boundary validators need stronger fail-safe behavior.

The repair should cover every issue in this report, not only the critical items. Section 7 contains a comprehensive remediation checklist.

## 2. Confirmed project decisions

These decisions were clarified during the review and should guide later implementation.

### 2.1 Bluesky is out of scope

There will be no Bluesky pipeline. The active Bluesky implementation, catalog entries, configuration, tests, and current-facing documentation should be removed.

Historical architecture decisions should not be rewritten or deleted. Per the project rules, add a new dated decision that supersedes the earlier Bluesky direction, while preserving the old entry as history.

### 2.2 Ambiguous publication outcomes must not be retried automatically

The agreed posting behavior is:

- Failures known to occur before the final external publication request may be retried according to policy.
- Once the final publication request has been sent, an exception or unknown response must be treated as an uncertain outcome.
- An uncertain outcome should enter a terminal/manual-review state such as `publication_unknown`.
- A stale `publishing` record must also resolve to `publication_unknown`, not to automatic retry.
- A read-only reconciliation tool may help an operator investigate the external account and local state, but it must not publish.

This is deliberately conservative: a temporarily missed post is preferable to an accidental duplicate public post.

### 2.3 Candidate cooldown is three days, but cooldown is not the duplicate-content boundary

The requested cooldown is three days. A time-only cooldown is insufficient because the same candidate could be selected on day four and generate essentially the same content again.

Recommended layered policy:

- An accepted candidate is treated as consumed for this POC and is not automatically determined again.
- A rejected candidate becomes eligible only after a three-day cooldown **and** only when deterministic source evidence has materially changed.
- A failed attempt resumes or retries its existing persisted handoff; it does not create a fresh determination for the same unchanged candidate.
- Deterministic content identity prevents multiple jobs/packages for the same content recipe.
- Posting idempotency and the conservative `publication_unknown` state prevent duplicate destination requests.

A useful deterministic identity for the current o2 pipeline is based on normalized fields such as:

`pipeline_id + format + normalized teaching_target + recipe/version`

The exact fields should be documented in a decision before implementation. The identity should be persisted and protected by a database uniqueness constraint, rather than enforced only through an application-level lookup.

### 2.4 The current SQLite database is disposable development state

The project is still in development, and the existing database may be wiped and recreated. A production-grade migration for the currently observed legacy schema is therefore not required immediately.

The future fix should still do one of the following explicitly:

- fail initialization with a clear incompatible-schema message and documented reset command, or
- perform a controlled rebuild/migration.

Silently accepting an incompatible schema is unsafe even during development.

## 3. Review scope and verification

The review covered:

- `docs/current.md`, architecture, interfaces, roadmap, decisions, pipeline documentation, and runbooks;
- the persisted responsibility chain from detection through posting records;
- SQLite schema initialization and boundary persistence;
- detection aggregation, scoring, cooldown, and handoff creation;
- determination claiming, evaluation, decision reuse, job creation, and worker behavior;
- o2 generation and validation;
- rendering and visual-worker behavior;
- Instagram posting, retry classification, idempotency, and reconciliation risks;
- configuration, launch templates, maintenance, and dashboard behavior;
- tests and documentation checks;
- the checked local development database in read-only mode.

At the time of the original review:

- `py scripts/run_tests.py` passed 57 tests.
- `py scripts/check_docs.py` passed.
- SQLite integrity checking reported the local database as valid.

Passing those checks does not cover the failure modes in this report. Several problems were reproduced directly with focused temporary or mocked scenarios.

The local database snapshot observed during review contained:

- 1 pending content job;
- 1 content package;
- 3 completed detection runs;
- 7 pending handoffs;
- 1 locally recorded offline publication;
- 26 source-health records;
- 566 snapshots;
- 128 candidates: 118 `new`, 10 `pending_determination`;
- 600 observations;
- 1 trend and no trend-history records.

It also lacked newer tables expected by the current implementation. These counts are review evidence only; the database is explicitly considered disposable development data.

## 4. Detailed findings

Severity meanings:

- **Critical:** can create duplicate public content, corrupt/strand the workflow, or prevent the current pipeline from operating.
- **High:** materially violates architecture or produces incorrect content/ranking/state.
- **Medium:** weakens reliability, validation, diagnostics, or maintainability.
- **Low:** documentation or consistency issue that should be corrected but is not independently operationally dangerous.

### F-01 — Existing SQLite schema can remain incompatible after initialization

Severity: **Critical**

The checked development database had a legacy `content_jobs.trend_id INTEGER NOT NULL` column. The current determination service constructs new content jobs with `trend_id=None`.

`Database.initialize()` relies on `CREATE TABLE IF NOT EXISTS`, followed by additive column checks. That approach cannot remove or relax an existing `NOT NULL` constraint. Initialization therefore appears successful while leaving the database incompatible with the current model.

Reproduction performed during review:

1. Copy the legacy database to a temporary location.
2. Run current database initialization.
3. Confirm that `content_jobs.trend_id` is still `NOT NULL`.
4. Attempt to save a current-style content job with `trend_id=None`.
5. SQLite raises `IntegrityError: NOT NULL constraint failed`.

Relevant implementation areas:

- `src/database/sqlite.py`, initialization and additive schema handling;
- `src/determination/service.py`, construction of a content job without a legacy trend ID.

Recommendation:

- Since development data is disposable, define and document a schema-version reset path now.
- Use `PRAGMA user_version` or a schema-migrations table.
- Refuse to start against an unsupported schema instead of silently continuing.
- Add a test that initializes from a representative legacy schema and verifies either a successful migration or an explicit incompatibility error.

### F-02 — A successful Instagram post can be automatically published twice

Severity: **Critical**

The posting agent performs the external publication and then updates the local record. Both actions are covered by a broad exception handler. If Instagram returns a successful media ID but the local `mark_published` or attempt-finalization write fails, the handler classifies the attempt as retryable. A later attempt can send the same publication again.

The same ambiguity exists when the final Instagram publication request times out: the remote side may have committed the post even though the local process did not receive a response.

Reproduction performed during review:

- Mock the publisher to return a successful external ID.
- Force the subsequent local database update to fail.
- Observe one completed publisher call and a local `retryable_failure` state with a scheduled next attempt.

Relevant implementation area: `src/posting/agent.py`, particularly the publish call, local success recording, and broad exception path.

Recommendation:

- Persist a posting attempt and idempotency key before external publication.
- Distinguish pre-publication failures from post-request uncertain outcomes.
- Never auto-retry after the final publication request may have reached the destination.
- Add `publication_unknown` and manual reconciliation as described in Decision 2.2 above.
- Add a boundary test where external publication succeeds and every following local write fails.
- Add a test for a timeout or connection loss during the final publication request.

### F-03 — Determination exceptions can strand claimed handoffs

Severity: **Critical**

Determination claims a handoff and then performs evaluation, usage recording, decision persistence, job creation, and handoff completion through separate operations. There is no complete exception-state policy covering the sequence.

If an exception occurs after claim, the handoff can remain `claimed` indefinitely. There is also no clear stale-claim recovery lease. If a decision was saved but its job was not, the existing-decision branch completes the handoff without reliably reconstructing the missing job.

Relevant implementation area: `src/determination/service.py`.

Recommendation:

- Define persisted states for `pending`, `claimed`, `completed`, and `failed/retryable`, including timestamps and error summaries.
- Give claims a lease or stale-after time so abandoned work can be recovered deterministically.
- Make decision persistence, content-job creation, and handoff completion idempotently resumable.
- When an existing accepted decision has no corresponding job, reconstruct or resume the job before completing the handoff.
- Add failure-injection tests after every persistence boundary in the determination sequence.

### F-04 — A rejection stops the determination worker

Severity: **Critical**

The determination consumer returns `None` both when no work exists and when a candidate is legitimately rejected. The worker loop uses `None` as its stop signal. Therefore, the first rejected candidate terminates the worker even when additional handoffs are pending.

Relevant implementation areas:

- `src/determination/service.py`, rejected-result return behavior;
- `scripts/run_determination.py`, loop termination condition.

Recommendation:

- Return an explicit result type that distinguishes `no_work`, `accepted`, `rejected`, `failed`, and possibly `deferred`.
- Continue consuming after a rejection.
- Stop only on `no_work`, a configured processing limit, shutdown, or a non-recoverable worker error.
- Add a test with a rejected handoff followed by an accepted handoff and assert both are processed.

### F-05 — Candidate cooldown is stored but not enforced at handoff creation

Severity: **High**

Handoff creation checks for an active handoff but does not consistently enforce candidate status and `cooldown_until`. The scout shortlist can therefore produce another handoff for a candidate whose cooldown is still in the future.

This was reproduced by assigning a future cooldown and observing that handoff creation still succeeded.

Recommendation:

- Enforce eligibility in one deterministic domain/service method used by all handoff creators.
- Protect the invariant in persistence where possible.
- Apply the layered accepted/rejected policy from Decision 2.3.
- Add tests for cooldown before expiry, at expiry, after expiry without evidence change, and after expiry with material evidence change.

### F-06 — Cooldown expiry alone would regenerate duplicate content

Severity: **High**

Even after F-05 is fixed, a simple three-day timer allows an unchanged candidate to re-enter determination and generation. This creates duplicate LLM cost and, more importantly, duplicate or near-duplicate published content.

Recommendation:

- Treat accepted candidates as consumed rather than temporarily cooled down.
- Store a deterministic evidence fingerprint on every determination.
- Reconsider rejected candidates only when both the three-day window has expired and their evidence fingerprint has changed materially.
- Store a deterministic content identity on jobs/packages and add a uniqueness constraint.
- Keep destination-post identity separate but linked, so publication retries never create a second logical post.
- If recurring coverage of the same subject is later desired, define it as a new editorial feature with an explicit freshness/version rule rather than allowing accidental recurrence.

### F-07 — Detection aggregation mixes incomparable raw metrics

Severity: **High**

The aggregation path sums raw activity from sources whose units differ substantially, including RSS presence, Hacker News score, Wikimedia pageviews, and YouTube views. A source with a naturally large numeric scale can dominate a candidate independently of corroboration or editorial value.

This conflicts with the documented decision to use normalized source signals. A reviewed example with activities on the order of `1`, `500`, and `10,000,000` produced a first-snapshot score driven by the largest count rather than balanced evidence.

Relevant implementation areas:

- `src/detection/aggregation.py`;
- `src/detection/scoring.py`.

Recommendation:

- Normalize activity within each source before cross-source aggregation.
- Prefer bounded deterministic transformations, ranks, percentiles, or documented log scaling.
- Separate corroboration breadth from source-local momentum.
- Version the scoring formula and save the version with snapshots/candidates.
- Add fixtures demonstrating that no single source wins solely because its raw unit has more digits.

### F-08 — First-observation and tie behavior is not meaningful ranking

Severity: **High**

First observations do not have history from which to calculate momentum. Many candidates can receive identical or mechanically similar scores. Equal-score ordering then inherits prior iteration order, which can effectively become alphabetical rather than reflecting attention or evidence strength.

Recommendation:

- Define explicit first-observation behavior.
- Add deterministic tie-breakers based on documented signals such as source corroboration, normalized activity, freshness, and stable candidate ID.
- Never rely on incidental dictionary/list order as a ranking rule.
- Add equal-score and first-observation tests.

### F-09 — Only the top 100 ranked candidates are persisted/considered

Severity: **High**

The scout requests `ranked_candidates(limit=100)`. This conflicts with the stated goal of retaining complete scored history and can make candidate history depend on a presentation/selection limit.

Relevant implementation area: `scripts/run_scout.py`.

Recommendation:

- Persist the complete scored snapshot set.
- Apply shortlist limits only after history has been written.
- Distinguish operational selection limits from analytical retention.

### F-10 — Clustered evidence is lost when the determination handoff is built

Severity: **High**

Snapshot construction groups related source topics/headlines into a canonical candidate. Handoff evidence is later selected using exact canonical-topic equality. Supporting observations that contributed to the cluster can therefore disappear from the payload even though source counts or scores still reflect them.

The result is a mismatch between the score/corroboration presented and the evidence the determination model receives.

Relevant implementation areas:

- `src/detection/aggregation.py`;
- `scripts/run_scout.py`.

Recommendation:

- Persist cluster membership explicitly using observation IDs.
- Construct handoff evidence from those stored members, not from a later string-equality query.
- Include source, measurement time/window, source item ID, normalized activity, and canonicalization rationale.
- Add a boundary test in which differently worded source headlines cluster and all members survive into the handoff.

### F-11 — Legacy Bluesky code contradicts the current scope and can create stuck work

Severity: **High**

The active catalog and runner include both the legacy `poc_pipeline` and the Instagram o2 pipeline. Default selection can choose the legacy entry. The pipeline runner registers it, while the visual worker skips non-o2 packages. A legacy package can therefore be generated and remain permanently unrendered.

The current documentation says Bluesky is deferred; the clarified decision is stronger: Bluesky should be removed from active scope entirely.

Relevant implementation areas include:

- pipeline catalog/service defaults;
- `scripts/run_pipeline.py`;
- `scripts/run_visual_worker.py`;
- `.env.example` and pipeline-related tests/docs.

Recommendation:

- Remove active Bluesky code paths, catalog entries, configuration, and tests that assert Bluesky behavior.
- Remove Bluesky from current architecture diagrams and runbooks where it appears as an active or planned pipeline.
- Preserve historical decisions and add a new dated superseding decision.
- Make o2 selection explicit; do not depend on catalog ordering.

### F-12 — o2 content validation checks counts but not required sequence

Severity: **High**

The o2 carousel validator verifies slide-type counts but does not fully enforce ordering. An invalid sequence such as `hook, use, explanation, use, use` can pass. Extra or misplaced hook-like structures can also satisfy count checks without matching the content contract.

Relevant implementation area: the o2 content validator in `src/pipelines/o2/content.py`.

Recommendation:

- Validate a sequence grammar, not just aggregate counts.
- Require exactly one hook in the first position, the expected explanation/concept placement, a contiguous or explicitly defined use section, and the required final slide type.
- Reject unknown or duplicate structural roles.
- Add negative tests for every invalid ordering, missing role, duplicate role, and out-of-range slide count.

### F-13 — Existing PNG files are reused without proving they belong to the package

Severity: **High**

The renderer skips a PNG when a file already exists at the target path. Smoke/local content IDs can restart from `1` in a new database while using a fixed output directory. A later run can therefore reuse old slide images with a new package and caption.

In a live flow, this can publish mismatched or stale visual content.

Relevant implementation areas:

- o2 renderer output/skip logic;
- smoke-run content-ID and output-directory behavior.

Recommendation:

- Render into a package-identity/version-specific directory.
- Use atomic temporary output followed by rename.
- Store and verify an artifact manifest containing package ID, content hash, template/version, slide count, dimensions, and per-file checksums.
- Never treat path existence alone as proof of readiness.
- Clean or isolate smoke artifacts from live output.

### F-14 — Configuration documentation and runtime loading do not match

Severity: **High**

The setup documentation instructs users to copy an `.env` file, but scripts read directly from `os.environ` and do not consistently load that file. A developer can follow the documented setup and still have missing configuration at runtime.

The launchd templates set limited environment values and contain placeholders. Only some components have service templates, so the complete responsibility chain is not yet independently schedulable or unattended.

Recommendation:

- Choose and document one configuration-loading contract.
- If `.env` is supported for local development, load it once at the composition root and never inside domain modules.
- Validate required configuration at process startup with clear messages.
- Supply complete Mac Mini service definitions only for components intended to run autonomously.
- Document ordering, polling, restart, logs, and shutdown behavior for the full chain.

### F-15 — Blank optional cost values can fail after a successful Gemini call

Severity: **High**

Optional cost settings shown as blank in `.env.example` can reach `float("")`, causing a `ValueError`. This can happen after a successful, billable Gemini request, turning a successful model call into a failed workflow and losing accurate cost/accounting state.

Relevant implementation areas include Gemini configuration and environment parsing.

Recommendation:

- Parse blank optional values as `None` or a documented default.
- Validate all numeric settings at startup.
- Record the usage response before optional cost calculation.
- Treat cost-estimation failure as accounting degradation, not as permission to repeat a successful model call.
- Add tests for unset, blank, valid, malformed, zero, and negative settings.

### F-16 — The read-only dashboard mutates the database on GET/startup

Severity: **High**

The dashboard has no workflow buttons, but it opens the normal database layer and calls initialization. A read request can create a missing database or add schema objects. That is operational mutation and violates the stronger meaning of a read-only dashboard.

Relevant implementation areas: dashboard startup/server code and shared database initialization.

Recommendation:

- Open SQLite in read-only URI mode for dashboard access.
- Never call schema initialization or migration from the dashboard.
- Fail with a clear unavailable/incompatible-schema page if the operational database is absent or unsupported.
- Add a test proving dashboard access does not change file timestamps, schema, or data.

### F-17 — Retention average is calculated incorrectly

Severity: **Medium**

The retention summary's average is derived incorrectly. With activities `10` and `20`, the reviewed calculation returned count `2` and average `20` rather than `15`. Existing tests assert the count but do not protect the average.

Relevant implementation area: retention/statistics query logic in `src/database/sqlite.py`.

Recommendation:

- Correct the SQL aggregation.
- Define whether the average is over observations, snapshots, candidates, or source-normalized values.
- Add exact-value tests covering multiple values, nulls, and empty input.

### F-18 — LLM usage accounting misses some successful billed calls

Severity: **Medium**

Usage capture occurs too late in some model-call flows. If Gemini returns a response but parsing or validation fails, the request may still have incurred cost while no usage ledger record is saved. Retry metadata also emphasizes final success and can omit prior billed attempts.

Recommendation:

- Capture provider response metadata and usage immediately after every completed provider response, before application validation.
- Create a usage/attempt record for every call, including invalid-output attempts.
- Associate all attempts with the determination or pipeline operation.
- Distinguish provider failure, transport uncertainty, parse failure, schema failure, and accepted output.

### F-19 — Posting failure classification is too broad

Severity: **Medium**

Posting classifies most exceptions as transient except a small set such as `KeyError`/`ValueError`. Permanent conditions can therefore retry indefinitely or until the attempt limit. Examples include missing files, invalid credentials, permission errors, invalid Graph API requests, and malformed package data.

Recommendation:

- Use typed adapter errors with categories such as `configuration`, `validation`, `authentication`, `permission`, `rate_limit`, `server_transient`, `network_pre_request`, and `publication_unknown`.
- Retry only explicitly transient categories.
- Treat missing local assets and invalid package content as terminal package failures.
- Persist external status/body/error codes in sanitized form.

### F-20 — R2 cleanup failures are silently swallowed

Severity: **Medium**

Temporary-media cleanup errors can be ignored without a persisted audit event or visible warning. This can leak objects and hide incomplete posting cleanup.

Recommendation:

- Treat cleanup as a separately recorded, idempotent operation.
- Do not change a successfully published post back to failed because cleanup failed.
- Record cleanup status/error and retry cleanup independently when safe.
- Provide a read-only report of stale temporary objects.

### F-21 — Rendering lacks persisted in-progress/failure states and resilient worker behavior

Severity: **Medium**

Rendering does not have a complete persisted lifecycle such as `rendering`, `rendered`, and `render_failed`. A worker failure can be indistinguishable from work that never started. The worker can also abort on the first bad package, preventing independent later packages from progressing.

Recommendation:

- Add explicit render-attempt state, timestamps, error category, and artifact manifest.
- Isolate package failures so the worker can continue with other eligible packages.
- Add a stale-render recovery policy.
- Ensure a package becomes posting-ready only after manifest verification.

### F-22 — Tests do not verify actual PNG output dimensions

Severity: **Medium**

The visual contract requires Instagram-compatible dimensions, but current tests do not open the resulting files and assert their actual pixel size and format.

Recommendation:

- Decode every rendered image in boundary tests.
- Assert dimensions, image format, color mode as required, slide count, and non-empty content.
- Test long text, Unicode, wrapping, and boundary slide counts.

### F-23 — `run_poc.py` does not represent a valid end-to-end offline POC

Severity: **Medium**

The script is described as offline but can use real Gemini. It does not consistently transition the package through rendering readiness, and destination/package relationships do not match the current Instagram o2 responsibility chain. It therefore cannot serve as trustworthy end-to-end proof.

Recommendation:

- Either remove the obsolete script or rebuild it as a fully deterministic test adapter flow.
- An offline POC must use a fake determination/generation adapter, render real local artifacts, validate them, post only through a fake publisher, and persist the complete state chain.
- Keep any live Gemini/Instagram smoke script clearly separate and explicitly named.

### F-24 — A documentation path points to the wrong `.env.example`

Severity: **Low**

Pipeline documentation references `docs/.env.example`, while the file is at the repository root.

Recommendation: correct the path and add link/path existence checks for documentation references.

### F-25 — Some architecture decisions are undated

Severity: **Low**

Decisions 015 and 016 do not follow the project's dated-decision convention.

Recommendation:

- Add the actual adoption date if it can be established from repository history.
- Do not invent a date.
- Do not rewrite the substance of earlier decisions when adding the new superseding Bluesky decision.

### F-26 — Posting interfaces and implementation do not use the same boundary model

Severity: **Medium**

Documentation describes distinct `PostRequest` and `PostRecord` concepts. The code effectively uses a `PostRecord` row as both queue input and mutable outcome record, and includes states such as `queued` that are not consistently reflected in the documented interface.

Recommendation:

- Decide whether request and result are separate persisted records or one explicitly stateful posting record.
- Document the exact state machine, ownership, immutable fields, mutable fields, attempt relation, and terminal states.
- Add explicit boundary models matching the decision.

### F-27 — `ContentPackage` template ownership differs between docs and code

Severity: **Medium**

The interface documentation includes a resolved template identifier, while the active model/table do not expose that field directly. Instead, several template-related identifiers can be embedded in `visual_spec`. This makes it unclear whether the pipeline selects a concrete template or the renderer resolves one.

Recommendation:

- Preserve the responsibility rule that the pipeline owns platform/format-specific content and the renderer only renders the supplied specification.
- Store one explicit resolved template ID and version/hash on the package.
- Make `visual_spec` schema-versioned and validate it at the pipeline-renderer boundary.

### F-28 — Wikimedia evidence can be stale or mislabeled

Severity: **Medium**

Documentation describes previous-day interest, but the implementation requests broader monthly data and may fall back repeatedly to earlier periods on exceptions. Older data can then be labeled as if it represented the current collection period. The measurement window is not carried clearly enough into evidence.

Recommendation:

- Define the exact Wikimedia measurement period.
- Persist `measured_from`, `measured_to`, and collection time.
- Only fall back for a known “data not yet available” response, not every exception.
- Penalize or reject evidence outside the permitted freshness window.
- Surface degraded/fallback health explicitly.

### F-29 — Source identity and provenance are incomplete

Severity: **Medium**

Hacker News and RSS observations do not consistently persist stable `source_item_id` values. Health records can label multiple distinct RSS feeds with the same generic source name. This weakens deduplication, traceability, and source-specific health diagnosis.

Recommendation:

- Require a stable source adapter ID and stable item ID where the provider supplies one.
- For RSS, distinguish feeds by configured source identity, not adapter class name alone.
- Store canonical URL and provider timestamp when available.
- Add uniqueness/deduplication rules that include the real source identity.

### F-30 — Handoff creation is a two-step write with a partial-state window

Severity: **Medium**

Handoff creation inserts a row and then updates the payload with the generated handoff ID. A crash between those writes can leave an incomplete payload or missing self-reference.

Recommendation:

- Avoid embedding a database-generated row ID inside the payload unless strictly required.
- If required, generate an application ID before insertion or perform both writes in one explicit transaction.
- Add a recovery/validation test for partially written handoffs.

### F-31 — Persisted status values are insufficiently constrained

Severity: **Medium**

Many status columns are free text without database `CHECK` constraints or a shared explicit model. Typos or obsolete values can silently create states no worker understands.

Recommendation:

- Define state enums at every boundary.
- Add SQLite `CHECK` constraints in a fresh development schema.
- Centralize allowed transitions in small repository/service methods.
- Add tests for illegal transitions and unknown stored values.

### F-32 — Several documented boundary models are implicit or missing

Severity: **Medium**

The project rule calls for explicit boundary models, but concepts such as `DeterminationRequest`, `PostRequest`, and API usage entries are not consistently represented as validated models.

Recommendation:

- Introduce only the boundary models needed by the responsibility chain.
- Keep them serializable, versioned where appropriate, and independent of external SDK objects.
- Validate before persistence and again when a downstream component loads a handoff.

### F-33 — Check-then-insert operations have concurrency races

Severity: **Medium**

Several idempotency paths first query for an existing active record and then insert a new one. Two workers can pass the check concurrently and create duplicates. SQLite serialization alone does not make a multi-statement application check atomic.

Recommendation:

- Encode uniqueness in indexes/constraints.
- Use transactions and handle uniqueness conflicts as idempotent “already exists” outcomes.
- Add two-connection concurrency tests for handoff, job/package, and posting identity creation.

### F-34 — SQLite operational settings and stale-work recovery are incomplete

Severity: **Medium**

The local-first design is appropriate, but there is no comprehensive operational policy for WAL/busy timeouts, multiple workers, or recovery of stale `claimed`, `running`, `rendering`, and `publishing` states.

Recommendation:

- Document the supported process/concurrency model.
- Configure an appropriate busy timeout and consider WAL after testing Mac Mini behavior.
- Use short transactions and never hold a transaction during network/LLM work.
- Add leases only where automatic retry is safe.
- Never automatically recover stale `publishing` to retry; use `publication_unknown`.

### F-35 — Retry-policy configuration accepts unsafe values

Severity: **Medium**

Posting retry settings are not fully validated. Values such as zero maximum attempts or negative intervals can create immediate failure or nonsensical schedules.

Recommendation:

- Validate all policy values at startup.
- Require attempts `>= 1`, intervals `>= 0`, and a bounded list/strategy.
- Test boundary and malformed values.

### F-36 — Posting readiness validation is weaker than the o2 contract

Severity: **Medium**

Generic Instagram validation permits a broad slide-count range, while o2 has a narrower format contract. Database readiness checks can also accept an arbitrary caller-supplied required count, and path existence/content is not always verified. A malformed package could therefore be marked ready for publication.

Recommendation:

- Resolve validation by pipeline and package schema version.
- Let the package declare its immutable expected artifact manifest; do not let arbitrary callers redefine readiness.
- Verify exact slide count, ordering, file existence, checksums, dimensions, and package identity before enqueueing a post.

### F-37 — Caption and hashtag validation is incomplete

Severity: **Medium**

The platform boundary does not fully enforce Instagram length and token rules. Hashtag validation is permissive enough to accept malformed or ambiguous values, and caption size constraints are not comprehensively protected before posting.

Recommendation:

- Normalize the caption once in the pipeline.
- Validate final serialized caption length against the documented platform policy.
- Define hashtag representation and syntax explicitly.
- Do not let the posting agent repair or regenerate invalid text; reject the package before posting.

### F-38 — Source health does not fully describe degraded collection

Severity: **Medium**

Fallback collection, partially missing identifiers, and multiple RSS configurations are not represented with enough specificity for operators to understand whether detection is healthy or merely produced some rows.

Recommendation:

- Track source-instance identity, requested measurement window, actual measurement window, item count, fallback mode, latency, and structured error category.
- Keep detection deterministic and LLM-free.
- Display this state in the read-only dashboard without allowing controls.

### F-39 — End-to-end tests follow an obsolete path

Severity: **High**

The existing end-to-end coverage exercises a legacy Bluesky/direct-call flow rather than the current persisted Instagram o2 chain. It therefore passes without proving the architecture the project now intends to operate.

Recommendation:

- Replace the obsolete test with a persisted o2 integration test:
  `observations -> snapshots -> candidate -> determination handoff -> decision -> ContentJob -> o2 pipeline -> ContentPackage -> rendered artifact manifest -> posting request -> fake publisher -> PostRecord`.
- Assert every persisted state and ownership boundary.
- Use deterministic fakes for Gemini and external publishing.

### F-40 — Important failure paths have no regression tests

Severity: **High**

The test suite lacks direct protection for several reproduced or high-risk cases:

- rejected candidate followed by more pending work;
- abandoned determination claim and stale recovery;
- exception between decision save, job save, and handoff completion;
- future cooldown at handoff creation;
- cooldown expiry without evidence change;
- invalid o2 slide ordering;
- successful external publication followed by local database failure;
- timeout during the final publication request;
- stale PNG reuse across databases/packages;
- actual PNG dimensions and file format;
- legacy/incompatible SQLite schema handling;
- renderer failure followed by another eligible package;
- billed LLM usage when validation fails;
- two-worker idempotency races.

Recommendation: implement these as boundary and integration tests as part of the corresponding fixes, not as a later cleanup phase.

### F-41 — Documentation checks are too shallow to detect semantic drift

Severity: **Medium**

The documentation checker primarily verifies file/heading presence and selected phrases. It does not catch active Bluesky code contradicting current scope, incorrect referenced paths, model/status mismatches, or a claimed offline script that calls a live model.

Recommendation:

- Keep the checker lightweight, but add deterministic checks for known contracts:
  - valid referenced repository paths;
  - active pipeline IDs matching the documented current scope;
  - documented status sets matching explicit enums;
  - launch/runbook scripts that actually exist;
  - decision entries following the required metadata format.
- Use architecture tests for code-level dependency boundaries rather than trying to encode all semantics in a docs script.

## 5. Cross-cutting design recommendations

### 5.1 Define explicit state machines

Each persisted boundary should have documented allowed states and transitions. At minimum:

- candidate eligibility and consumption;
- determination handoff/claim;
- content job execution;
- package generation and rendering;
- posting request and attempt;
- cleanup/reconciliation.

State transitions should be conditional updates that fail cleanly when another worker has already moved the record.

### 5.2 Use three separate identities

Avoid treating all “duplicate” concerns as one problem:

1. **Evidence identity:** represents the deterministic source evidence/fingerprint for a candidate.
2. **Content identity:** represents the editorial recipe that should be generated at most once unless intentionally versioned.
3. **Publication identity:** represents the single intended destination publication and its attempts.

Persist each identity and enforce the correct uniqueness rule in SQLite.

### 5.3 Make external side effects the last and most conservative boundary

All local validation, artifact verification, configuration validation, and posting-attempt creation should happen before the external publication request. Once that request may have been transmitted, never infer failure from lack of acknowledgement.

### 5.4 Keep recovery idempotent

Restarting a worker should resume existing persisted work. It should not create a new candidate decision, job, package, or publication merely because the previous process stopped.

### 5.5 Version important deterministic contracts

Persist versions for:

- detection scoring;
- canonicalization/evidence fingerprinting;
- determination prompt/schema;
- pipeline recipe/content identity;
- package/visual specification;
- renderer template;
- posting policy where it affects state interpretation.

This lets the project distinguish an intentional new version from an accidental duplicate.

### 5.6 Keep the dashboard strictly observational

The dashboard may explain state, errors, health, and reconciliation information. It should not initialize/migrate the operational database, retry work, publish, or expose workflow controls unless a later explicit decision changes its responsibility.

## 6. Recommended repair order

This order is based on data/publication safety and dependency structure. It is not permission to omit lower-priority findings.

### Phase 1 — Freeze the intended contracts

1. Add a dated decision superseding Bluesky and defining Instagram o2 as the only active pipeline.
2. Document the three-day rejected-candidate cooldown plus accepted-candidate consumption and evidence-change requirement.
3. Document content identity and publication-uncertainty policy.
4. Align `ContentPackage`, rendering, posting request/record, and status interfaces.

### Phase 2 — Rebuild the development persistence contract

1. Define schema versioning and an explicit development database reset path.
2. Recreate the disposable database using the new constraints.
3. Add status checks, uniqueness constraints, attempt tables/fields, leases, and artifact identity as required.
4. Add incompatible-schema startup tests and concurrency tests.

### Phase 3 — Fix the critical worker behavior

1. Make determination results explicit so rejection does not stop the worker.
2. Add exception handling, idempotent resume, and stale-claim recovery.
3. Ensure accepted decisions always have exactly one matching content job.
4. Add failure-injection tests at each persistence boundary.

### Phase 4 — Correct detection and duplicate prevention

1. Normalize source metrics and define first-observation/tie behavior.
2. Persist complete scored history before shortlist limits.
3. Persist cluster membership and full evidence provenance.
4. Enforce candidate eligibility and the three-day rejected cooldown.
5. Add evidence fingerprints and content-identity uniqueness.

### Phase 5 — Make generation and rendering trustworthy

1. Remove the active Bluesky pipeline.
2. Enforce the o2 slide sequence grammar.
3. Resolve and persist template ID/version explicitly.
4. Render atomically to package-specific paths with verified manifests.
5. Add rendering lifecycle/failure recovery and real image QA tests.

### Phase 6 — Make posting safe for live side effects

1. Validate package/artifacts fully before posting.
2. Persist publication identity and the attempt before calling Instagram.
3. Use typed failure classification.
4. Add `publication_unknown` and prohibit automatic retry after an uncertain final request.
5. Record cleanup separately and provide read-only reconciliation/reporting.
6. Test successful remote publication followed by every possible local failure.

### Phase 7 — Operational and documentation completion

1. Align `.env` instructions and runtime loading; validate all settings at startup.
2. Make dashboard SQLite access truly read-only.
3. Replace/remove the misleading POC script and obsolete end-to-end test.
4. Complete Mac Mini run/service documentation for the intended components.
5. Correct path/date/interface documentation drift.
6. Strengthen documentation and architecture checks.

## 7. Complete remediation checklist

This checklist is included to ensure every finding remains in scope during implementation.

- [ ] F-01: add schema version/reset or migration behavior; test incompatible legacy schema.
- [ ] F-02: prevent automatic duplicate publication after uncertain/successful external side effects.
- [ ] F-03: make determination claims and downstream writes resumable and recoverable.
- [ ] F-04: continue the determination worker after rejection.
- [ ] F-05: enforce cooldown/status at handoff creation.
- [ ] F-06: add evidence and content identities so cooldown expiry does not regenerate duplicates.
- [ ] F-07: normalize heterogeneous detection metrics.
- [ ] F-08: define first-snapshot and deterministic tie behavior.
- [ ] F-09: persist complete scored history before shortlist limiting.
- [ ] F-10: preserve clustered evidence membership in handoffs.
- [ ] F-11: remove active Bluesky scope and add a superseding dated decision.
- [ ] F-12: validate the exact o2 slide sequence.
- [ ] F-13: stop unverified reuse of existing PNG paths.
- [ ] F-14: align `.env`, process configuration, and launch documentation.
- [ ] F-15: safely parse optional costs and record successful Gemini usage.
- [ ] F-16: make dashboard access operationally read-only.
- [ ] F-17: correct and test retention averages.
- [ ] F-18: ledger every billed LLM attempt, including invalid output.
- [ ] F-19: introduce typed posting error classification.
- [ ] F-20: persist/audit R2 cleanup outcomes.
- [ ] F-21: add rendering lifecycle, isolation, and stale recovery.
- [ ] F-22: assert actual image dimensions and format.
- [ ] F-23: remove or rebuild the misleading `run_poc.py` flow.
- [ ] F-24: correct the `.env.example` documentation path.
- [ ] F-25: resolve missing decision dates without inventing history.
- [ ] F-26: align PostRequest/PostRecord documentation and code.
- [ ] F-27: make resolved template ownership explicit on ContentPackage.
- [ ] F-28: correct Wikimedia measurement/fallback freshness and provenance.
- [ ] F-29: persist stable source/feed and item identities.
- [ ] F-30: make handoff creation atomic or avoid self-ID payload mutation.
- [ ] F-31: constrain statuses and allowed transitions.
- [ ] F-32: add missing explicit boundary models.
- [ ] F-33: replace check-then-insert races with database-enforced idempotency.
- [ ] F-34: define SQLite concurrency settings and stale-work policies.
- [ ] F-35: validate retry configuration values.
- [ ] F-36: enforce o2-specific posting readiness and artifact manifests.
- [ ] F-37: complete caption and hashtag validation before posting.
- [ ] F-38: make source-health degradation and fallback visible.
- [ ] F-39: replace obsolete end-to-end coverage with persisted Instagram o2 coverage.
- [ ] F-40: add all listed failure-path regression tests alongside fixes.
- [ ] F-41: strengthen docs/architecture drift detection.

## 8. Acceptance criteria for the eventual repair

The repair should not be considered complete until all of the following are true:

1. Only the Instagram o2 pipeline is active.
2. A fresh development database is created at an explicit schema version, and an incompatible old database cannot be silently used.
3. Rejection does not halt determination, and process crashes do not permanently strand safe-to-retry work.
4. Accepted candidates are not automatically reconsidered; rejected candidates require both three elapsed days and changed evidence.
5. The same deterministic content identity cannot produce a second job/package unintentionally.
6. Detection ranking uses documented normalized source signals and preserves full evidence/history.
7. Invalid o2 slide order is rejected before rendering.
8. Rendered files are proven to belong to the exact package and match the required manifest/dimensions.
9. A final Instagram publication request is issued at most once automatically for a logical publication.
10. Any ambiguous final publication outcome becomes `publication_unknown` and requires reconciliation rather than retry.
11. Every billable model call and every posting attempt is represented in the ledger, including failed validation and uncertain outcomes.
12. The dashboard cannot create, migrate, or update the operational database.
13. Configuration following the documented setup works consistently on the Mac Mini runtime.
14. All items in Section 7 have either been fixed and tested or explicitly deferred in `docs/current.md` with rationale and acceptance criteria.
15. `py scripts/run_tests.py` and `py scripts/check_docs.py` pass after the new boundary and regression tests are added.

## 9. Final assessment

The project should continue with its current local-first, SQLite-handoff architecture. None of the findings require distributed queues, direct module-to-module calls, LLM-based detection, or additional infrastructure. The main need is to make the existing persisted boundaries explicit, idempotent, and conservative around irreversible external side effects.

The highest-risk issue is duplicate external publication. The broadest correctness issue is that identities and state transitions are currently implicit: evidence recurrence, content duplication, retryable work, rendered artifacts, and publication attempts need separate persisted definitions. Once those contracts are explicit, most of the fixes become small, testable changes within the existing architecture.

This file records the review only. It does not modify or approve changes to application code, documentation decisions, runtime configuration, or the SQLite database.
