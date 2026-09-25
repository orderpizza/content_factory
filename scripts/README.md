# Scripts

This directory contains stable operator and developer entrypoints. They remain
flat for now: splitting them into subdirectories is deferred until the script
count justifies the path churn.

## Runtime/operator

- `run_detection.py` — collect due feeds and run deterministic Detection.
- `run_workflow.py` — run planning or Gemini review workers.
- `serve_dashboard.py` — serve the loopback dashboard.
- `run_storage_monitor.py` — record model-free storage and growth observations.

## Setup/maintenance

- `setup_development.py` — create a fresh development database and seed local configuration.
- `create_local_idea.py` — submit or refine a human idea.
- `run_maintenance.py` — perform explicit backup, restore verification, or pruning.
- `install_review_baseline.py` — manage the five review-only Mac Mini LaunchAgents.

## Development verification

- `run_tests.py` — run the offline deterministic suite.
- `check_docs.py` — check documentation links and ownership contracts.
- `check_smoke_readiness.py` — inspect local planning or review prerequisites without a provider call.

## Review baseline lifecycle

Install (or reinstall) the baseline after creating a current development
database:

```sh
.venv/bin/python scripts/install_review_baseline.py --install \
  --artifacts data/artifacts/review-baseline \
  --backups data/backups/review-baseline
```

Use `--status` to inspect all five agents. Use `--stop` to boot out just those
agents while retaining their plist files, then rerun `--install` to restart
them. Use `--uninstall` to boot out and remove only those five owned plist
files. Do not stop the baseline by killing worker PIDs: launchd `KeepAlive`
will restart the continuously running services.
