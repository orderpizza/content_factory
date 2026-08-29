# Worker Runtime and Scheduling Specification

**Document role:** Tier 2 target design contract. It defines required runtime
behavior; verify implementation conformance from code and tests.
**Owner:** Mac Mini worker processes, scheduling, polling, restart behavior,
heartbeat, and scheduler configuration.
**Read this for:** Worker entry points, background services, `launchd`, polling,
cadence, claim behavior, startup/shutdown, or backlog handling. Read
[the system guide](../system.md) first, then [the data model](data-model.md)
and [reliability specification](reliability.md) for state and safety rules.

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
- Worker intervals, batch sizes, and enabled/disabled state are local runtime
  configuration. Defaults below are the documented operating policy; a change
  must update this specification and dashboard freshness thresholds together.
- Stop requests finish no new claim, release/allow expiry of an active lease,
  persist a safe outcome when possible, and exit. Long Gemini, rendering, R2,
  or social calls must not occur inside a SQLite transaction.
- A worker crash is handled by `launchd` restart and expired SQLite lease
  recovery. Recovery resumes the same record; it never creates a replacement
  handoff from unchanged input.

## Worker schedule and contract

| Worker | Default cadence and trigger | SQLite input and claim | Output / no-work behavior | Fresh / warn / stale |
| --- | --- | --- | --- | --- |
| Trend Scout + Shortlist | Every 15 min; always runs (a source may reuse a completed longer measurement window) | Enabled external source instances plus prior detection state; one Scout run lease | Persist observations, snapshots, every scored `TrendCandidate`, then atomically create source-backed `ContentThread` + `IntakeRequest` records only for selected candidates. Update source health/worker heartbeat even with zero candidates. | ≤20 min / >20 min / >45 min |
| Idea Intake Agent | Every 30 s when pending input exists; 5 min idle health poll | Pending/retry-ready `IntakeRequest`; conditional fenced request claim | Persist a clarification message and `needs_clarification`, or atomically persist immutable `BriefRevision` + pending `DeterminationRequest`. No eligible request: heartbeat only; do not call Gemini. | ≤1 min / >1 min / >3 min with pending input |
| Determination Worker | Every 30 s | Pending `DeterminationRequest`; conditional request claim | Persist one `accepted`, `not_recommended`, or `blocked` decision and a unique `ContentJob` only when accepted. No pending request: heartbeat only; do not call Gemini. | ≤1 min / >1 min / >3 min with pending work |
| Pipeline Runner | Every 30 s | Pending/retry-ready `ContentJob` and its `GenerationRun`; conditional fenced run claim | Invoke the selected in-process pipeline strategy, checkpoint validated creative, then persist one immutable `ContentPackage`, or safe retry/failure. No pending work: heartbeat only. | ≤1 min / >1 min / >3 min with pending work |
| Visual Renderer | Every 30 s | Pending `RenderRun`; conditional run claim | Persist verified manifest/assets and create review availability, or a safe failure. No pending run: heartbeat only. | ≤1 min / >1 min / >3 min with pending work |
| Posting Agent | Every 15 s; **Post now** creates an immediate-mode record whose due time is resolved by the active posting policy | Due/retry-ready `PostRecord`; conditional fenced record claim. `PostRequest` remains immutable authorization. | Persist attempt/result and cleanup tasks. No due post: heartbeat only. A policy-eligible Post now record is normally claimed within one poll interval; Instagram processing time is additional. | ≤30 s / >30 s / >90 s when due work exists |
| Cleanup Worker | Every 5 min | Pending safe `DeliveryCleanupTask`; conditional task claim | Persist R2 cleanup outcome. No task: heartbeat only. | ≤10 min / >10 min / >20 min with pending cleanup |
| Publication Reconciliation Worker | On explicit human request; optional 15-min check while unresolved requests exist | Pending/retry-ready `ReconciliationRequest` for `publication_unknown`; conditional fenced claim | Append a read-only `ReconciliationCheck`; resolve only an unambiguous match or mark `needs_human`. It never publishes or retries. | Show last check; warning until resolved |

Review availability is created by the completed renderer transaction; it has no
separate worker. The dashboard is not a worker: while visible, it refreshes its
SQLite reporting snapshot every 10 seconds; while hidden, it does not poll.

## Eligibility, pickup, and “change detection”

Workers do not need a database trigger or subscription. Their SQL eligibility
predicate is their pickup mechanism. Examples include a pending Intake or
Determination request, a pending job/run, a completed render awaiting review,
or a due Post Record. A record written by one component becomes visible to the
next component when that worker makes its next poll.

Human commands use the same mechanism. **Post now** does not make the dashboard
call Instagram: it atomically creates immutable authorization and an
immediate-mode `PostRecord`. The active posting policy computes when that record
is eligible for the Posting Agent. This guarantees the command survives a
browser close, process restart, or temporary network failure and remains
visible in the audit trail.

The exact conditional claims, leases, terminal states, safe retries, and
ambiguous-publication rules are owned by the
[reliability specification](reliability.md) and [data model](data-model.md).

## Health and operations

Every process updates its single `worker_heartbeats` row on each poll. It adds
an append-only `worker_runs` row only when it substantively claims or processes
work, preventing an unbounded audit row for every empty poll. The dashboard
computes health from current heartbeats, substantive runs, active leases,
backlog, and the thresholds above; it never infers worker health from browser
activity.

For every worker, the dashboard must show enabled state, configured interval,
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
