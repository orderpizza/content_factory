# Content Factory

Local-first automated content factory POC. The Mac Mini is the target runtime,
SQLite is the persisted system boundary, and Phase 1 targets five domain
pipelines producing static Instagram/X content with explicit human approval.

## Start here

Read [the system guide](docs/system.md) before changing architecture or code.
It is the Tier 1 Human–Agent Interface: the current target flow, responsibility
boundaries, and router to every focused contract.

## Documentation layout

- `docs/system.md` — Tier 1 architectural map and required-reading matrix.
- `docs/specs/` — Tier 2 component and cross-cutting contracts. Persistence
  detail is routed from `specs/data-model.md` into `specs/data/records.md`.
- `docs/pipelines/` — domain/intelligence contracts; accounts and output formats
  are separate configuration and shared production/output concerns.
- `docs/platforms/` — time-sensitive provider account/API facts.
- `docs/contracts/` — machine-checkable boundary schemas.
- `docs/profiles/` — reusable concrete renderer profile contracts.
- `docs/plans/` — noncanonical implementation sequencing; contracts win.
- `docs/archive/` — historical rationale for targeted lookup only.
- `config/releases/` — reviewed, non-secret manifests applied through the
  configuration control plane.

The current implementation milestone is the deterministic detection ingestion
feed and its local dashboard view. The new target catalog is
[English, AI/Tools, Personal Finance, Business/Side Hustles, and Psychology/Behavior](docs/pipelines/domains.md).
One trend may select several credible angles, each generating canonical content
before [Instagram/X adaptation](docs/specs/platform-outputs.md). This architecture
update does not claim that downstream production is implemented. Follow the
required-reading matrix in the system guide; do not infer architecture from
legacy code or this README.

The source tree is not architectural authority until it conforms to the routed
target contracts. For documentation-only changes run `py scripts/check_docs.py`;
for implementation changes run that command and `py scripts/run_tests.py`.

## Run the current detection milestone

From the repository root on Windows (use `python3` in place of `py` on the Mac
Mini):

```powershell
py scripts/setup_detection.py
py scripts/run_detection.py
py scripts/serve_dashboard.py
```

Then open `http://127.0.0.1:8787`. Setup is explicit and never runs from a
worker or dashboard process. If an older development database is intentionally
disposable, rerun setup once with `--rebuild`; the old file is moved to a
timestamped backup rather than deleted.

`run_detection.py` is the convenient one-shot development command. The
scheduler-safe entrypoints are `run_collector.py` every five minutes and
`run_scout.py` every fifteen minutes; both recover the same persisted attempt
after a safe retry or expired lease. `report_trends.py` and `dashboard.py` are
bounded read-only reporting commands.

## Non-Goals For The Initial POC

Phase 1 excludes TikTok, YouTube Shorts, other video-first platforms, AI video,
and Bluesky. Do not add distributed queues, cloud workers/databases, Kubernetes,
vector databases, a generic plugin framework, or speculative video infrastructure.
The [target plan](docs/plans/target-implementation.md) distinguishes approved
strategy from pending schemas, provider verification, and implementation.
