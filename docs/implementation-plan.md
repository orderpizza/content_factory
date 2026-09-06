# Target Implementation Plan and Acceptance Matrix

**Document role:** Noncanonical implementation sequencing aid. The Tier 1
[system guide](system.md) and its routed Tier 2 contracts remain the source of
truth; when this plan conflicts with one of them, the contract wins.

**Use this for:** Planning a cohesive implementation slice and its boundary
tests. Do not use it to invent a schema field, status, provider fact, or product
behavior.

## Delivery sequence

| Stage | Implement only after | Scope | Acceptance evidence |
| --- | --- | --- | --- |
| 1. State foundation | No prerequisite | Forward SQLite baseline migration, foreign keys, immutable/audit helpers, command receipts, fenced claims, leases, status validation, and read-only reporting connection. | Migration preserves a fixture database; invalid FK/status/duplicate identity is rejected; two claimers cannot both finalize; dashboard connection cannot write/migrate. |
| 2. Threads and routing | Stage 1 | `ContentThread`, free-text messages, Intake, immutable revisions, capability snapshots, Determination, model ledger/reservations, and accepted-job atomicity. | Human and trend origins create the same lineage; clarification resumes correctly; revision history is immutable; duplicate/restart cannot create two decisions/jobs; stale Gemini work is cost-uncertain and not repeated. |
| 3. Detection | Stage 1 | Source registry, NASA RSS, Wikimedia pageviews, YouTube US popular, Hacker News, deterministic normalization/clustering/scoring/shortlist/recurrence, and source health. | Fixtures prove source provenance, versioned scoring/ranking, quota gate, selected-thread atomicity, cooldown/material evidence behavior, and no Gemini invocation. |
| 4. O2 generation | Stages 1–2 | Registered O2 capability, GenerationRun checkpoints, claim-reference validation, `o2_creative_v1`, `o2_word_count_v1`, metadata, immutable package, and per-job Gemini caps. | A frozen accepted job creates one validated package; metadata retry reuses creative; invalid claims/word counts/metadata fail safely; content identity blocks duplicate generation. |
| 5. Rendering and review binding | Stages 1 and 4 | `editorial_clean_v1`, templates/bindings, pinned local assets/fonts, manifests, atomic filesystem promotion/recovery, canonical review assets, and review creation. | Golden render verification passes; malformed/overflow binding fails; restart/quarantine recovery cannot adopt arbitrary files; review binds exact package/manifest/asset hashes. |
| 6. Dashboard HAI | Stages 1–5 | Loopback read model, Trend Opportunities default view, trace/drill-down, pipeline portfolio, simple idea/revision/review commands, freshness and storage display. | All human commands are idempotent/version-checked and persist only their allowed records; no command directly invokes a worker/API; an end-to-end trace is complete; disabled/historical pipelines remain inspectable. |
| 7. Posting and Meta | Stages 1, 5, and 6 | Post now request/record, policy eligibility, R2 staging/cleanup, Instagram adapter, attempt/resource audit, cancellation, uncertain outcome and reconciliation. | Safe test doubles prove pre-final retry, duplicate prevention, cancellation race, expiry, and `publication_unknown`; R2 credentials check is read-only/temporary; live smoke test is separately authorized and public-content-aware. |
| 8. Runtime hardening | Stages 1–7 | `launchd` units, cadence/heartbeats, Storage Monitor, backups/restore verification, retention, disk gates, operational dashboard, and failure injection. | Restart/lease-expiry test resumes safely; every enabled worker meets pickup/freshness targets; backup restore verifies integrity; low-disk gates prevent new generation/render without erasing review/publication evidence. |

## Integration gates

1. Run `py scripts/check_docs.py` for a documentation-only change. Run both
   `py scripts/run_tests.py` and `py scripts/check_docs.py` for every
   implementation change.
2. Do not enable a later stage’s worker until its persisted inputs, output
   constraints, and boundary tests are present.
3. Use local fixtures/fakes for Gemini, R2, and Meta by default. Credential
   and live publication checks require the explicit user authorization stated
   in the system guide.
4. Before unattended O2 operation, run an operator-observed end-to-end path:
   source or human idea → review asset → one-click Post now → audited outcome,
   then repeat the relevant restart/duplicate/expired-approval failure cases.
5. Expansion to another pipeline or platform starts by adding its focused
   pipeline/platform contract and capability; it must not fork the shared
   state, renderer, review, posting, or runtime contracts.
