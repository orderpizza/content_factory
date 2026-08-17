# Local Runtime Runbook

## Verification

```powershell
py scripts/run_tests.py
py scripts/check_docs.py
```

## Local Workers

These workers communicate only through persisted SQLite state:

```powershell
py scripts/run_scout.py
py scripts/run_determination.py
py scripts/run_pipeline.py
py scripts/run_visual_renderer.py
```

The Posting Agent is under development. Do not treat a local worker invocation
as authorization to make a real external post.

## Dashboard

```powershell
py scripts/serve_dashboard.py
```

The dashboard is read-only and must remain an observer of persisted state.
