# Testing and acceptance

## Offline verification

From the repository root with the development environment installed:

```sh
.venv/bin/python scripts/run_tests.py
.venv/bin/python scripts/check_docs.py
```

The suite uses temporary databases, fake providers and local browser checks.
Install Chromium using `.venv/bin/python -m playwright install chromium` first;
if using a custom `PLAYWRIGHT_BROWSERS_PATH`, export the same path for tests.
No paid Gemini calls or public posting belong in routine verification.
The documentation check validates links, contract routing, schema inventory,
source roster, operator commands and environment settings.

## Safeguards and regression owners

| Boundary | Coverage in `tests/` |
| --- | --- |
| Fresh schema, configuration and packaged contracts | `test_hybrid_detection.py`, `test_configuration.py`, `test_packaged_contracts.py`, `test_visual_configuration.py` |
| Atomic handoffs, idempotency and lease fencing | `test_workflow_claims.py`, `test_planning_flows.py`, `test_workflow_planning.py`, `test_adaptation_checkpoints.py` |
| Evidence, claims and domain integrity | `test_detection.py`, `test_semantic_detection.py`, `test_gemini_workflow.py`, `test_prompt_contracts.py`, `test_domain_boundaries.py` |
| Budget, uncertainty and bounded retries | `test_model_budget.py`, `test_gemini_transport_reliability.py`, `test_render_recovery.py` |
| Geometry, asset integrity and checkpoint recovery | `test_storyboard_pagination.py`, `test_gemini_image_renderer.py`, `test_render_text_policy.py`, `test_render_recovery.py` |
| Review and duplicate-delivery protection | `test_delivery_boundaries.py`, `test_visual_configuration.py`, `test_workflow_planning.py`, `test_r2_relay.py` |
| Dashboard security and operator recovery | `test_dashboard.py`, `test_gemini_workflow.py`, `test_storage_and_maintenance.py` |
| Acceptance isolation and documentation integrity | `test_acceptance_harness_offline.py`, `test_documentation_contracts.py` |

Delivery logic is not composed into a live posting service. Its tests protect
explicit approval and conservative uncertain outcomes for future integration.
Do not delete these checks merely because current operation stops at review.
Current domain/visual policy tests are not obsolete just because future accounts
will be configurable. Replace a contract and its coverage together when that
future design is approved.

## Fresh bootstrap smoke

Follow [operations](operations.md#fresh-setup) to create a new timestamped DB.
The deterministic `scripts/run_workflow.py` default exercises planning only.
Existing fake-provider journey tests exercise generation through exact review
assets; they validate mechanics, not real model quality. Never reset a local
operator database to run a smoke check.

## Opt-in paid acceptance

[The acceptance runner](../acceptance/README.md) owns stage, chain and full-journey
commands, finite budget requirements and authorization switches. Reusable
scenarios and fixtures remain tracked in `acceptance/`; results, databases,
boards and galleries belong in ignored `data/acceptance/`. A golden scenario
asserts stable evidence/routing/output constraints, never exact generated prose.

Live acceptance needs explicit authorization and does not enable publication.
Human reviewers must inspect editorial accuracy, qualifications, typography and
visual continuity. Successful geometry or schema checks do not establish those
qualities. The controlled fidelity profile compares the same frozen package
under different board layouts; thresholds remain provisional until measured.
