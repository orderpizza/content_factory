# Worker Runtime Specification

**Document role:** Tier 2 current local runtime contract.
**Owner:** Process composition, polling, claims and operator visibility.

## Processes

Run from the Mac Mini repository root against one current-schema database.
The [operations guide](../current-state.md) owns copyable session commands.

| Entrypoint | Behavior |
| --- | --- |
| `setup_development.py` | Explicit fresh schema/config/catalog and initial storage sample; no provider inference |
| `run_detection.py` | Due collection then Scout; optional continuous polling |
| `run_collector.py` | Detection entrypoint with Scout disabled; forwards CLI arguments |
| `run_scout.py` | Detection entrypoint with collection disabled; forwards CLI arguments |
| `run_workflow.py` | Persisted workers, one pass or polling |
| `serve_dashboard.py` | Loopback visibility and human commands; no worker invocation |
| `create_local_idea.py` | CLI equivalent of idea/reply handoff |
| `enable_placeholder_route.py` | Explicit manual single-domain fixture registration |
| `check_smoke_readiness.py` | Read-only planning/preview/production/delivery prerequisites |
| `run_storage_monitor.py` | Local storage sampling and daily growth measurement; optional polling, no model/source calls |
| `run_maintenance.py` | Verified backup, checkpoint, optional restore verification and storage sample |

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
| Default | Deterministic fixture Intake, Determination, generation, adaptation, visual planner, renderer and disabled PostingAgent |
| `--gemini` | Gemini Intake/Determination; downstream fixtures |
| `--planning-only` | Intake/Determination only, leaving new GenerationRuns pending |
| `--gemini --planning-only` | Live Gemini planning trial, no downstream production |
| `--gemini --review-preview` | Also Gemini generation/adaptation, deterministic visual planning and dispatched Gemini-image/HTML review rendering |
| `--gemini --review-preview --production` | Immutable real-destination catalog and production rendering/admission |
| Above plus `--delivery` | Credentialed posting, R2 cleanup and reconciliation |

StorageMonitor runs before workers in every mode and refreshes its sample at
most every five minutes. Monitoring is advisory through ContentJob creation:
missing, old, clock-invalid or low-space samples cannot block dashboard/CLI ideas,
refinements, Intake, Detection or Determination. A monitor measurement error is
logged with a failed heartbeat, but the pass continues to planning workers.
Actual database write failures may still fail. Downstream generation, rendering
and delivery retain the separate [storage policy](reliability.md#storage-action-matrix).
The independent monitor requires no Gemini configuration and consumes no jobs.

`--planning-only` cannot be combined with preview, production or delivery.
`--poll` repeats the pass every five seconds by default; each worker claims at
most one item per pass. Results print every pass. Invalid/non-finite intervals
are rejected; Ctrl+C stops cleanly. Idle polls only update heartbeats.
Substantive results, clarification and failures have persisted run evidence;
failed claims must not be reported as idle.

Review rendering defaults to `--renderer auto`: supported Instagram archetypes
use one Gemini 3×2 storyboard-image generation; `--renderer html` keeps deterministic rendering.
Production keeps its existing HTML renderer and eligibility gates.
[Visual rendering](visual-rendering.md#gemini-designer-review-rendering) owns
image processing and review asset behavior.

Real Gemini composition always requires a priced ModelBudgetPolicy.
No real providers are invoked by deterministic fixture mode.

## Claims and recovery

Claims use SQLite write transactions, owner, version and lease expiry. Only a
current owner with a live lease can finalize. Long generation/adaptation/render
operations use their ten-minute initial lease; planning uses bounded shorter
claims. Designer rendering renews a still-live render claim before each slide
call, retaining the same owner/version. Fenced finalization prevents a stale
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
planning verification. Launchd templates are optional operator-installed
scheduling examples; manual polling does not install background services.

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
