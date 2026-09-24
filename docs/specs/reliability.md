# Reliability and Safety

**Owner:** Cross-cutting failure boundaries, Gemini accounting and storage policy.
Normal stage behavior belongs in the owning specs, routed by [system](../system.md).

## Claims and immutable handoffs

Claimable records use SQLite transactions, owner, monotonic claim version, lease,
attempt count/limit and typed terminal or retry state. A stale owner cannot
finalize or create children. Safe local work can be reclaimed; terminal failed
work is not silently polled again. Existing model-call history prevents blind
paid replay. [Runtime](runtime.md#claims-and-recovery) owns process behavior.

Each successful boundary commits output and downstream requests atomically.
Uniqueness guards one decision per request, editorial plan per selected route, job per plan, canonical
result per job, package per output and recipe per visual-plan run. Closed/cancelled threads fence downstream
finalization. A human refinement does not cancel older jobs.

Detection freezes source input and semantic resolution separately; completed
resolution is reused without another embedding call. Scoring uses frozen
membership and lexical credit, not pooled semantic corroboration.
[Detection](detection.md) owns this algorithm and replay contract.

## Artifacts and publication

[Visual rendering](visual-rendering.md) owns deterministic archetype selection, temporary
output, atomic promotion, manifest/hash validation and quarantine of uncommitted
final artifacts.
File existence alone is never proof of a completed render or reviewed asset.

[Posting](posting.md) owns authorization, pre-final cancellation, durable
final-send markers and reconciliation. Once a public request might have been
sent, the result is published or unknown, never automatically retryable.
Staging cleanup is separately audited and cannot undo a confirmed publication.
Preserved generic reconciliation requires human resolution; no provider lookup is active.

## Gemini accounting

`ModelBudgetPolicy` requires positive prices, daily warning/hard limits and a
job hard limit. [Configuration](configuration.md#model-admission) lists settings
and per-phase token allowances. Every real Gemini runner mode uses this policy;
direct test workers use fakes.

Before a call, `begin_model_invocation` checks the live claim, input size and
invocation identity. It records a started invocation and reserves worst-case
micro-USD from configured phase maxima and prices:

```text
ceil(max_input_tokens × input_USD_per_million
   + max_output_tokens × output_USD_per_million)
```

Settled cost plus outstanding reserved/uncertain cost counts toward the UTC-day
limit. Generation, image rendering and all adaptation/metadata attempts also share their original
job cap. Intake, Determination and Editorial Planning have no job yet and consume only the daily cap.
Daily exhaustion defers without a provider call; job exhaustion fails visibly.
Changing process configuration does not erase existing spend.

Image rendering uses a separate price policy against that same ledger and records
`image_rendering` invocations on RenderRuns. Expired image claims with external
history fail instead of being reclaimed for another paid call. One storyboard call has one reservation and invocation identity; local processing
failures preserve that evidence without another paid attempt. A pre-call daily
budget refusal may defer safely.

The provider's returned usage settles reservations; absent usage retains the
worst-case uncertain reservation. The client captures usage before JSON parsing
and counts returned thinking tokens as output. Parse, validation and transport
failures retain their invocation outcome and usage when available. A lost/started
call is not assumed free and cannot be blindly repeated. There is no operator
accounting-recovery command.

Text requests use one provider attempt and a finite 60-second transport timeout.
An interrupted or timed-out request remains uncertain in the invocation ledger;
workers do not convert that uncertainty into an automatic paid retry.

The local input guard is 32,000 serialized request characters, not exact input
tokenization. Output allowance is sent to the client. Configured input-token
maxima are reservation assumptions, not a separately implemented tokenizer or
provider count-tokens check.

The client projects array cardinality limits into wire-schema descriptions for
Vertex while retaining types, required fields and closed objects. Local worker
validators enforce the original bounds before persistence. This is not a paid
retry or permission to persist invalid output.

## Storage, backup and retention

StorageMonitor records physical disk/database/WAL/artifact/backup sizes at most
once per five minutes. The first sample each UTC day includes a consistent
table-count/JSON-byte scan with a five-second SQL budget. Partial results are
explicit; missing data never means zero growth. No row content is exported by
measurement. The dashboard exposes up to 31 daily measurements.

Planning never consults storage admission. Missing, stale, clock-invalid or
low-space samples do not block human ideas/refinements, Collection, Scout,
Intake, Determination, Editorial Planning or ContentJob creation. Actual SQLite/OS writes can still
fail. Monitor measurement failure is observable but does not stop planning.

### Storage action matrix

A current sample is at most ten minutes old. The review runner enforces the following downstream policy; it is not a planning safety gate.

| Action | Normal | Warning | Critical | Emergency / missing / stale / clock-invalid |
| --- | --- | --- | --- | --- |
| Dashboard reads and all planning through ContentJobs | Allow | Allow | Allow | Allow |
| New generation/adaptation/render claims | Allow | Block | Block | Block |
| Post now and new delivery claims | Allow | Allow with exact approved assets | Block | Block |
| Non-work-creating cancellation/reconciliation | Allow | Allow | Allow if durable writes succeed | Allow if durable writes succeed |
| Explicit audited cleanup/backup | Allow | Allow | Allow if durable writes succeed | Allow if durable writes succeed |

Sample classification uses the stricter of free-space ratio and bytes:

- normal: at least 15% and 10 GiB;
- warning: below either normal threshold;
- critical: below 8% or 5 GiB;
- `read_only_emergency`: below 3% or 1 GiB.

The emergency identifier does not put SQLite or planning into read-only mode.
Recovery to normal needs two consecutive normal raw samples. In-flight external
outcomes remain auditable regardless of later storage deterioration.

Explicit maintenance uses a local lock and SQLite online backup, integrity/
schema checks, hash verification and atomic file promotion. It requests passive
WAL checkpointing; truncation requires no active claims and reports busy results.
Restore verification uses a temporary directory. Explicit verified backup pruning
keeps 14 newest snapshots plus eight older weekly representatives.

For the 24/7 review-only Mac Mini baseline, `launchd` schedules one backup and
restore-verification pass daily at 03:15 local Mac time. The backup worker has
the same database, artifact and backup roots as the continuous workers, but is
not kept alive: its next scheduled pass is the retry boundary after a failed
maintenance run. Operators inspect its persisted heartbeat and `maintenance_runs`
before treating backup recovery as healthy.

There is no automatic database-row or terminal-rendered-asset age deletion.
Backup pruning and transient R2 cleanup are not database retention. Measurement
does not delete evidence or authorize deletion.

## Input, privacy and local access

Human text is limited to 8,000 characters per message. Frozen conversations and
model request views are bounded. Planning projects repeated trend observations
to at most 24 representatives with omission counts; immutable full evidence
remains in SQLite. [Intake/Determination](idea-intake-and-determination.md) owns
that projection.

Source adapters retain bounded normalized facts/metadata, not fetched article
bodies. They use configured HTTPS sources, bounded responses/timeouts and
restricted redirects. Models have no browsing or publishing tools. Untrusted
source/user text cannot change policy, catalog, schema or publication authority.

Diagnostic helpers redact secret/header/signed-URL patterns. Model ledgers store
hashes, versions, usage and safe errors, not full prompts/responses.
[Runtime logging](runtime.md#diagnostic-logging) owns process-log limits.
Authoritative submitted messages and validated content remain intact, so never
put credentials or private data in ideas. Redaction is not a guarantee that an
arbitrary user-supplied secret will be removed from the database or its backups.

Dashboard text is escaped, links are scheme-restricted, assets are verified
against configured roots/manifests and CSP permits only fixed application
scripts. The server binds to loopback and uses a per-process CSRF token, command
IDs and row-version checks. It is a trusted single-machine interface, not a
multiuser authentication system.

## Verification limits

Offline tests cover fencing, atomic handoffs, checkpoints, manifests, storage
edge cases and publication uncertainty. They do not prove editorial truth,
live authorization or provider exactly-once behavior.

Storyboard boards share one RenderRun but each has its own invocation and budget
reservation. Successful earlier boards never authorize automatic replay after a
later failure, budget refusal or expired lease. The entire review commits only
after all boards succeed. [Visual rendering](visual-rendering.md) owns the exact
plan, split and English compatibility contracts.
