# Worker Runtime Specification

**Document role:** Tier 2 current local runtime contract.
**Owner:** Process composition, polling, claims and operator visibility.

## Processes

Run from the Mac Mini repository root against one current-schema database.
The [operations guide](../current-state.md) owns copyable session commands and
the supported 24/7 review-only LaunchAgent composition.

No process initializes or migrates the database implicitly. Incompatible schemas
fail closed. Secret settings load once at startup; restart after changes.

## Detection polling

`--poll` repeats due checks every 30 seconds by default; `--poll-interval`
changes the delay between passes. Source cadence and Scout slot uniqueness,
not polling frequency, determine collection/evaluation eligibility.
`--source`, `--skip-collection`, `--skip-scout` narrow a pass.

One running poller reuses its Scout/encoder and local model cache. MiniLM
inference uses bounded recent clusters and configured CPU threads. It never
calls an external inference API. Missing model assets fail before scoring;
frozen evaluations replay without a new embedding call.

Collection failures and Scout errors persist stage evidence. Fatal runner errors
stop the process and remain visible through the failed run/last heartbeat;
correct the underlying condition before restarting. Ctrl+C exits cleanly.

## Workflow composition

| Flags | Workers |
| --- | --- |
| Default / `--planning-only` | Deterministic fixture Intake and Determination only |
| `--gemini` / `--gemini --planning-only` | Gemini Intake and Determination; pending GenerationRuns remain untouched |
| `--gemini --review-preview` | Also Gemini generation/adaptation, visual planning and Gemini review rendering |

StorageMonitor runs before workers in every mode and refreshes its sample at
most every five minutes. Monitoring is advisory through ContentJob creation:
missing, old, clock-invalid or low-space samples cannot block dashboard/CLI ideas,
refinements, Intake, Detection or Determination. A monitor measurement error is
logged with a failed heartbeat, but the pass continues to planning workers.
Actual database write failures may still fail. Downstream generation, rendering
and delivery retain the separate [storage policy](reliability.md#storage-action-matrix).
The independent monitor requires no Gemini configuration and consumes no jobs.

`--planning-only` cannot be combined with preview.
`--poll` repeats the pass every five seconds by default; each worker claims at
most one item per pass. Results print every pass. Invalid/non-finite intervals
are rejected; Ctrl+C stops cleanly. Idle polls only update heartbeats.
Substantive results, clarification and failures have persisted run evidence;
failed claims must not be reported as idle.

Review rendering uses one Gemini storyboard call for each supported domain format
in English, AI/Tech and Psychology. Unsupported domain/archetype combinations
block without a model call or HTML fallback. [Visual rendering](visual-rendering.md#gemini-designer-review-rendering)
owns image processing and review assets.

Real Gemini composition always requires a priced ModelBudgetPolicy.
No real providers are invoked by deterministic fixture mode.

## Claims and recovery

Claims use SQLite write transactions, owner, version and lease expiry. Only a
current owner with a live lease can finalize. Long generation/adaptation/render
operations use their ten-minute initial lease; planning uses bounded shorter
claims. The storyboard call requires a still-live render claim. Fenced finalization prevents a stale
worker from creating children.

Local work without external-call history can be recovered under attempt limits.
An existing model invocation prevents blind automatic replay after lease loss.
Budget deferrals persist retry-wait state without a model call. Finalization
checks thread cancellation/closure before inserting downstream output.

A human refinement creates a new immutable brief and request; it does not
silently cancel already-created jobs from an older revision. Planning-only mode
makes these branches inspectable before any generation runs.

## Health and maintenance

The dashboard shows worker state separately from heartbeat freshness and
current claim/lease evidence. Missing heartbeats mean a worker has not reported,
not that it is healthy. Queue counts expose pending, failed and deferred work.

Maintenance uses an exclusive local process lock, SQLite online backups,
checksum/integrity verification and bounded checkpointing. Restore checks are
local temporary operations. Backup pruning is explicit, not part of routine
planning verification. The supported continuous baseline runs exactly one
Detection poller, one Gemini review workflow poller, one loopback dashboard and
one independent storage monitor. A separately scheduled backup process runs an
online backup plus restore verification. Launchd restarts the four continuous
processes after exits; shared database/artifact/backup paths are command-line
arguments, not inferred from process-local defaults.

## Diagnostic logging

Detection, workflow, dashboard, human-idea CLI and storage-monitor entrypoints
emit structured UTC JSON Lines to stderr and PID-scoped rotating files under
`CONTENT_FACTORY_LOG_ROOT` (default `data/logs`). Files rotate at 2 MB, with
three backups per process; seven-day diagnostic retention is applied on process
startup. Sizes/counts are configurable. SQLite remains the authoritative audit.
Logs record identifiers, claim versions, attempt counts, states, timings, counts,
model/token/cost metadata and typed errors. Embedding load/batch timing is separate
from Detection attention. Dashboard logs method, allowlisted path without query,
status and latency; command logging excludes submitted text. No full prompts,
provider responses, human messages, tokens or exception bodies enter process logs.
Missing model usage remains unknown, not zero-cost success. Validation errors are
identified by stage/outcome/type; detailed safe diagnostics remain in SQLite.

See [reliability](reliability.md) for budget, storage and publication uncertainty.
