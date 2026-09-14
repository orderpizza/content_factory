# Worker Runtime and Scheduling Specification

**Document role:** Tier 2 target design contract. It defines required runtime
behavior; verify implementation conformance from code and tests.
**Owner:** Mac Mini worker processes, scheduling, polling, restart behavior,
heartbeat, and scheduler configuration.
**Read this for:** Worker entry points, background services, `launchd`, polling,
cadence, claim behavior, startup/shutdown, or backlog handling. Read
[the system guide](../system.md) first, then [the data model](data-model.md)
and [reliability specification](reliability.md) for state and safety rules.

**Implementation status:** [Current implementation and operations](../current-state.md)
is the sole as-built map for available workers, templates, commands, and known
gaps. This specification is a target runtime contract and does not assert that
a worker or supervisor is installed or active.

## Runtime model

Content Factory is intended to run continuously on the Mac Mini. Components do
not push work to one another and SQLite does not emit change events. Each worker
periodically queries SQLite for records that are eligible for its own stage,
claims work safely, persists its result, and polls again at its configured
cadence.

```text
Scheduler/supervisor starts or keeps worker alive
  → worker polls SQLite for its eligible records
  → worker conditionally claims one record
  → worker does its bounded responsibility
  → worker persists output/status and heartbeat
  → downstream worker sees eligible persisted output on its next poll
```

This is a cron-style scheduling model, but the Mac Mini target uses macOS
`launchd`, not a user-managed `crontab`. `launchd` starts workers at boot,
restarts a failed service, and maintains a small, inspectable local operating
surface. Each worker remains a separate process and never calls the next worker
directly.

## Scheduler and process contract

- Run one supervised process per worker type. `launchd` keeps it alive and
  starts it after reboot; it is not a deployment platform or a replacement for
  SQLite state.
- Each process owns an internal poll loop. It completes at most its configured
  bounded batch per poll, writes a heartbeat even when no work exists, and then
  waits until the next cadence.
- Only one active process of a worker type is allowed in the initial POC.
  SQLite conditional claims remain mandatory so a restart or accidental overlap
  cannot duplicate work.
- Worker intervals, batch sizes, and enabled/disabled state come from the
  activated non-secret configuration release. Local environment settings only
  compose the process and resolve secrets; they cannot silently override policy.
  A worker freezes its release fingerprint when it claims work.
- Stop requests finish no new claim, release/allow expiry of an active lease,
  persist a safe outcome when possible, and exit. Long Gemini, rendering, R2,
  or social calls must not occur inside a SQLite transaction.
- A worker crash is handled by `launchd` restart and expired SQLite lease
  recovery. Recovery resumes the same record; it never creates a replacement
  handoff from unchanged input.

## Worker schedule and contract

| Worker | Default cadence and trigger | SQLite input and claim | Output / no-work behavior | Fresh / warn / stale |
| --- | --- | --- | --- | --- |
| Trend Source Collector | Every 5 min; materializes due source-instance collection attempts at their configured cadences | Pending/retry-ready `SourceCollectionAttempt`; conditional fenced attempt claim | Makes one bounded provider operation, then persists immutable observations and source-health evidence. A completed attempt is never fetched again; no due source: heartbeat only. | ≤20 min / >20 min / >45 min for a due source |
| Trend Scout + Shortlist | Every 15 min; materializes one evaluation slot, then claims it | Pending/retry-ready `ScoutEvaluationRun`; conditional fenced evaluation claim | Freezes the latest usable collection attempt or explicit health state for every enabled source, scores/persists every `TrendCandidate`, then atomically creates source-backed `ContentThread` + `BriefRevision` + `DeterminationRequest` only for selected candidates. It makes no provider call. | ≤20 min / >20 min / >45 min |
| Idea Intake Agent | Every 30 s when pending human input exists; 5 min idle health poll | Pending/retry-ready human `IntakeRequest`; conditional fenced request claim | Persist a clarification message and `needs_clarification`, or atomically persist immutable `BriefRevision` + pending `DeterminationRequest`. No eligible request: heartbeat only; do not call Gemini. | ≤1 min / >1 min / >3 min with pending input |
| Determination Worker | Every 30 s | Pending `DeterminationRequest`; conditional request claim | Persist one `accepted`, `not_recommended`, or `blocked` decision. Completion atomically creates five route assessments and one immutable domain job/run per selected route; reuse creates no duplicate job. No pending request: heartbeat only; do not call Gemini. | ≤1 min / >1 min / >3 min with pending work |
| Production Admission Gate | Every 30 s and after any slot release | Waiting GenerationRuns/AdaptationRuns under frozen production policy; no provider call | Atomically reserves required execution/downstream slots and promotes eligible work to `pending`; human-origin first. Full capacity remains `waiting_capacity` without paid work. | ≤1 min / >1 min / >3 min while capacity wait exists |
| Pipeline Runner | Every 30 s | Pending/retry-ready `GenerationRun`; conditional fenced run claim, with immutable parent `ContentJob` recipe | Invoke the selected in-process pipeline strategy, checkpoint validated domain content, then persist one immutable `CanonicalContent` and every frozen OutputRequest/AdaptationRun, or safe retry/failure on that same run. No pending work: heartbeat only. | ≤1 min / >1 min / >3 min with pending work |
| Adaptation Worker | Every 30 s | Pending/retry-ready `AdaptationRun` with immutable canonical content and OutputRequest, required reservations, and fenced claim | Invoke the selected in-process Instagram/X output adapter; checkpoint native content/metadata; atomically create one immutable ContentPackage and first RenderRun. No work: heartbeat only, no Gemini call. | ≤1 min / >1 min / >3 min with pending work |
| Visual Renderer | Every 30 s | Pending `RenderRun`; conditional run claim | Persist verified manifest/assets and create review availability, or a safe failure. No pending run: heartbeat only. | ≤1 min / >1 min / >3 min with pending work |
| Capability Readiness Monitor | Every 5 min after explicit installation; immediately after configuration activation only when live readiness is operator-authorized | No work claim; active configuration plus safe local/provider dependency checks | Upsert each current `CapabilityReadiness` row and append its check evidence. Local config/renderer checks run every poll. Provider/account/token checks occur only in an explicitly operator-approved installed live monitor, at most every 6 h; a manual `--live` run is one-time authorization. It never changes configuration or posts. | ≤10 min / >10 min / >20 min |
| Posting Agent | Every 15 s; **Post now** creates an immediate-mode record whose due time is resolved by the active posting policy | Due/retry-ready `PostRecord`; conditional fenced record claim. `PostRequest` remains immutable authorization. | Persist attempt/result and cleanup tasks. No due post: heartbeat only. A policy-eligible Post now record is normally claimed within one poll interval; provider processing time is additional. | ≤30 s / >30 s / >90 s when due work exists |
| Cleanup Worker | Every 5 min | Pending safe `DeliveryCleanupTask`; conditional task claim | Persist R2 cleanup outcome. No task: heartbeat only. | ≤10 min / >10 min / >20 min with pending cleanup |
| Publication Reconciliation Worker | On explicit human request; optional 15-min check while unresolved requests exist | Pending/retry-ready `ReconciliationRequest` for `publication_unknown`; conditional fenced claim | Append a read-only `ReconciliationCheck`; resolve only an unambiguous match or mark `needs_human`. It never publishes or retries. | Show last check; warning until resolved |
| Recovery Worker | Every 1 min while a Recovery Request is pending; 5 min idle health poll | Pending/retry-ready `RecoveryRequest`; conditional fenced claim | Validates target fingerprint/terminal state/no external ambiguity and either creates one replacement local run/task or records a typed rejection. It never calls a provider or resets history. | ≤2 min / >2 min / >5 min with pending request |
| Storage Monitor | Every 5 min | No work claim; local read-only filesystem/database-size sample | Persist current free space, threshold state, database/WAL/artifact/backup sizes, and heartbeat. It never deletes anything itself. | ≤10 min / >10 min / >20 min |
| Maintenance Worker | Every day at 03:30 Asia/Seoul; restore verification on the first Sunday monthly at 04:15 | One local `maintenance_runs` execution protected by a process lock; it does not claim business work | Runs backup, safe checkpoint, artifact cleanup, and SQLite retention as separate audited operations. No overlap: records `skipped_overlap` and tries again at the next scheduled run. | backup ≤26 h / >26 h / >50 h; restore ≤35 d / >35 d / >42 d |

The shared production admission rules and reservation ownership are canonical in
[Content production](content-production.md). Domain strategies share one Pipeline
Runner process; Instagram/X output strategies share one Adaptation Worker
process. Adding a domain/account does not create a new supervisor service.

Review availability is created by the completed renderer transaction; it has no
separate worker. The dashboard is not a worker: while visible, it refreshes its
SQLite reporting snapshot every 10 seconds; while hidden, it does not poll.

## Current detection-milestone entrypoints

The implementation-ready slice exposes separate one-shot process entrypoints
for scheduler isolation:

| Process | Entrypoint | launchd interval |
| --- | --- | ---: |
| Trend Source Collector | `scripts/run_collector.py` | 5 minutes |
| Trend Scout + Shortlist | `scripts/run_scout.py` | 15 minutes |
| Loopback dashboard/HAI | `scripts/serve_dashboard.py` | kept alive |
| Production workflow/posting | `scripts/run_workflow.py --gemini --review-preview --production --delivery --poll` | kept alive; internal 5-second poll |
| Destination readiness | `scripts/check_production_readiness.py --live --confirm-transient-r2-write --only-due` | 5 minutes only in an explicitly operator-approved recurring live monitor; otherwise, run manually once |
| Maintenance | `scripts/run_maintenance.py --prune-backups` | daily 03:30 local scheduler time |

`scripts/check_smoke_readiness.py --mode preview|production|delivery` is an
operator-invoked, read-only preflight rather than a scheduled worker. It makes
no provider call and exits nonzero while local configuration, dependency,
storage, backup, secret-reference, or persisted readiness gates are incomplete.
It cannot verify ADC validity, provider entitlements, creative quality, or a
public-delivery result.

`check_production_readiness.py --live` is not a routine verification command.
An operator may authorize a one-time live check. Installing a `launchd` monitor
with `--live --only-due` is a separate authorization for recurring external
requests and must not be inferred from ordinary preflight, testing, or worker
installation.

`scripts/run_detection.py` runs the due collector pass and one Scout evaluation
sequentially for local development only; it is not the unattended scheduler
boundary. `scripts/setup_normalized_detection.py` is the schema/configuration
setup entrypoint and is always operator-invoked. Scout requires schema v5 and
the pinned MiniLM model provisioned with `setup_semantic_detection.py
--database <path> --download-model`. The download is explicit setup traffic;
Scout uses offline CPU inference only, capped by the activated manifest's
recent-cluster, pair, batch and thread limits. Inference runs outside SQLite
write transactions; the resolution commit checks owner, claim version and
lease expiry. Frozen retries never embed again. See
[Detection](detection.md#semantic-event-resolution) for the exact stage contract.
`scripts/setup_workflow.py` separately applies the optional local v2 scaffold.
Neither worker nor dashboard performs
implicit migration. The corresponding `com.contentfactory.*.plist` templates
must have their placeholder paths replaced during Mac Mini installation. The
workflow template also depends on database/artifact/backup and credential
settings in the process environment or repository `.env`. The maintenance
template targets the v4 audited service, but `--prune-backups` should be retained
only after the owner accepts its 14-newest/eight-weekly policy.

The local workflow scaffold recovers expired no-model claims within attempt
limits, rejects expired/stale finalizers, records processing failures and checks
thread cancellation under the finalization lock. Claims with model history or
delivery risk fail closed. This is not the complete production heartbeat,
lease-renewal, capacity, or supervision envelope specified below.

`scripts/run_workflow.py` executes one sequential pass by default. `--poll`
repeats that pass every five seconds unless `--poll-interval` overrides it and
stops cleanly on Ctrl+C. `--gemini` swaps only the Intake and Determination
workers and registers the five synthetic domain/Instagram/X fixture bindings;
it neither changes downstream fixture workers nor enables delivery.
`--review-preview` requires `--gemini` and replaces generation, adaptation, and
rendering with their real implementations. Synthetic bindings stay review-only.
`--production` additionally requires schema v4, real immutable bindings, a
backup root, priced model policy, production checkpoints/profiles, and current
storage evidence. `--delivery` composes credentialed Posting, R2 cleanup, and
reconciliation workers; it still cannot post without an exact dashboard Post
now record. `com.contentfactory.workflow.plist` is an uninstalled template for
this explicit composition.

## Eligibility, pickup, and “change detection”

Workers do not need a database trigger or subscription. Their SQL eligibility
predicate is their pickup mechanism. Examples include a pending Intake or
Determination request, a pending job/run, a completed render awaiting review,
or a due Post Record. A record written by one component becomes visible to the
next component when that worker makes its next poll.

Human commands use the same mechanism. **Post now** does not make the dashboard
call Instagram or X: it atomically creates immutable authorization and an
immediate-mode `PostRecord`. The active posting policy computes when that record
is eligible for the Posting Agent. This guarantees the command survives a
browser close, process restart, or temporary network failure and remains
visible in the audit trail.

The active destination's versioned posting policy computes eligibility and slot
release. Its exact time zone, daily cap, interval, and uncertain-publication
reservation rule are owned only by the [Posting Agent](posting.md#initial-cadence-policy--posting_policy_v1);
runtime consumes the frozen policy without restating or overriding it.

The exact conditional claims, leases, terminal states, safe retries, and
ambiguous-publication rules are owned by the
[reliability specification](reliability.md) and [data model](data-model.md).
Storage thresholds, backup/restore verification, and retention are also owned
by [Reliability and safety](reliability.md). The Storage Monitor's persisted
threshold state is the gate for new claims; workers do not make an independent
disk-space decision.

## Maintenance Worker — `maintenance_v1`

The initial `run_maintenance.py`/`com.contentfactory.maintenance` contract is
one daily 03:30 local-time invocation. It takes a nonblocking local advisory lock;
overlap records `skipped_overlap`. One invocation:

1. creates an online SQLite backup, fsyncs it, and audits its SHA-256 after
   SQLite integrity and migration validation;
2. requests a passive WAL checkpoint and truncates only when no claimed/running/
   publishing workflow row exists;
3. optionally (`--prune-backups`) retains the 14 newest plus up to eight older
   weekly representatives, deleting only tracked/hash-matching surplus files;
4. optionally (`--restore-verify`, or the current first-Sunday run) restores the
   new audited backup into a temporary directory and verifies integrity,
   migrations, and trace counts; and
5. records a current storage sample after the maintenance sequence.

Artifact cleanup, SQL-row retention, off-device copies, internal retry timers,
and a separate 04:15 monthly launchd trigger are not implemented. Maintenance
does persist success/failure/overlap heartbeat state. A failed invocation exits
nonzero for launchd/operator visibility
and can be rerun safely after inspection. The dashboard shows the latest storage
gate and delivery/cleanup summary, not the full maintenance portfolio described
by the target design.

Storage admission uses the single action matrix in Reliability; a heartbeat is
not a storage sample. A missing/stale sample fails closed for new business work;
a current warning sample is not equivalent to missing storage evidence.
The normal/warning/critical/emergency thresholds, action matrix and recovery rule are owned by
[Reliability and safety](reliability.md#storage-backup-and-retention--storage_safety_v1).

## Initial lease and retry envelope — `worker_recovery_v1`

For current installation reproducibility, `uv.lock` freezes resolved dependency
versions and artifact hashes across supported markers; build tools are pinned in
`pyproject.toml`. Use an isolated environment and `uv sync --locked --extra dev`,
then the documented test/check commands. `--locked` rejects stale project metadata
instead of silently changing the lock. Locked/install portability has Windows
fixture evidence, and the current Mac host passes the offline suite including
the review renderer. Installed launchd behavior and owner-approved production
font/profile output remain separate rollout gates. See the official
[uv locking documentation](https://docs.astral.sh/uv/concepts/projects/sync/).

Every worker claims one item per poll in the POC. The following table is the
single recovery envelope; it is configuration mirrored in persisted work at
creation, not a worker-local default. "Maximum runtime" is the time allowed
for one claimed execution before it must persist a safe retryable outcome or
allow its lease to expire. It does not authorize an interrupt of a final social
request that may already be in flight.

| Worker | Lease | Renew | Maximum runtime | Maximum executions |
| --- | ---: | ---: | ---: | ---: |
| Trend Source Collector | 10 min | 3 min 20 sec remaining | 8 min | 3 per source collection attempt |
| Trend Scout + Shortlist | 10 min | 3 min 20 sec remaining | 8 min | 3 per Scout evaluation run |
| Idea Intake | 5 min | 1 min 40 sec remaining | 4 min | 3 per request |
| Determination | 5 min | 1 min 40 sec remaining | 4 min | 3 per request |
| Production Admission Gate | none | n/a | local transaction only | no execution retry; re-evaluate next poll |
| Pipeline Runner | 10 min | 3 min 20 sec remaining | 8 min | 3 per generation run |
| Adaptation Worker | 10 min | 3 min 20 sec remaining | 8 min | 3 per adaptation run; does not reset the parent job's model budget |
| Visual Renderer | 10 min | 3 min 20 sec remaining | 8 min | 3 per render run |
| Posting Agent | 5 min | 1 min 40 sec remaining | 4 min | 3 only before a final provider request |
| Cleanup Worker | 10 min | 3 min 20 sec remaining | 8 min | 3 per task |
| Publication Reconciliation | 10 min | 3 min 20 sec remaining | 8 min | 3 per request/check cycle |

Attempt 1 is immediately eligible. Safe reattempts 2 and 3 use nominal delays
of 30 seconds and 5 minutes respectively, with a deterministic plus-or-minus
10 percent jitter derived from the entity identity and attempt number. A
rate-limited adapter may use a longer provider `Retry-After` value. Exhausted
work becomes terminal `failed` with its last typed safe diagnosis; it never
loops indefinitely. A graceful stop takes no new claim, records a completed
safe local step where possible, and otherwise releases or lets its active lease
expire for the next worker instance.

Only transport/pre-side-effect, provider-transient, and locally retryable
validation failures are retryable. A stale Gemini `started` invocation is
cost-uncertain and is never retried automatically. A final social-publication
request that may have been sent becomes `publication_unknown`, never retryable.

**Implemented subset and target gap:** detection records heartbeat/run evidence;
the shared workflow poller updates one heartbeat per logical stage on every pass
and appends `worker_runs` only for returned substantive results. Readiness,
storage, and maintenance also update heartbeat state. The dashboard applies the
stage-specific freshness thresholds above. A swallowed stage failure remains
visible on its business record but may leave the last heartbeat as idle, and a
process crash before result recording has no durable workflow-run row. Full
active-claim correlation, restart counts, mid-call renewal, and capacity-aware
supervision remain target work.

For every worker, the complete target dashboard must show enabled state, configured interval,
last start/success/failure/no-work poll, next expected poll, active claim,
backlog, restart count, stale reason, and the safe operator action. Worker logs
are local diagnostic output; SQLite is the audit source of truth.

## Acceptance requirements

Before relying on unattended operation, verify that:

- `launchd` starts every enabled worker at boot and restarts it after a crash;
- a single worker process cannot overlap its own scheduled execution;
- each worker picks up an eligible record within its documented cadence;
- a policy-eligible Post now record is claimed within 15 seconds under healthy
  local conditions;
- no-work polls do not invoke Gemini or external publishing APIs;
- restart/lease expiry resumes the same work without duplicate output; and
- dashboard freshness becomes warning/stale from persisted worker state, even
  when the dashboard browser is closed.
