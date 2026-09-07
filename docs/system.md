# Content Factory System Guide

This is the primary Human–Agent Interface (HAI) and narrative source of truth.
Read this architectural map first, then the owning focused contracts. Legacy
implementation is not architectural authority.

## Documentation Contract

- **Tier 1 — this guide:** objective, component boundaries, ownership, and routing.
- **Tier 2 — focused contracts:** one canonical owner per detailed concern.
  `specs/` owns shared behavior; `pipelines/` owns domain intelligence;
  `platforms/` owns time-sensitive provider facts.
- `contracts/` owns executable SQL and versioned JSON schemas; `profiles/` owns
  reusable visual implementations; `sources/` owns source-provider facts;
  `plans/` is derived sequencing; `archive/` is historical rationale only.

**Must** is mandatory, **should** requires a recorded exception, and **may** is
permitted discretion. The [Contract Registry](contracts/maturity.md) declares
maturity, dependencies, and verification requirements. An accepted architecture
does not make a draft payload, migration, or provider integration ready to run.
Breaking deployed contracts requires a new version or forward migration.

## Current Objective

Phase 1 is a local-first, inexpensive trend-to-static-social-content experiment:
five domain pipelines decide which credible angles to produce, generate reusable
canonical content, and adapt it for Instagram and X under human review.

| Domain pipeline ID | Specialization |
| --- | --- |
| `english` | O2English: expressions, vocabulary, phrases, and cultural language |
| `ai_tools` | AI developments, tools, capabilities, and practical use cases |
| `personal_finance` | Economic developments and ordinary consumers' financial understanding |
| `business_side_hustle` | Commercial implications, entrepreneurship, and practical opportunities |
| `psychology_behavior` | Behavioral patterns, communication, and evidence-grounded interpretation |

Pipeline identity is **not** a platform, format, brand, or account. English's
primary Instagram destination is `o2_english`; other destination names remain
configuration choices. The [domain catalog](pipelines/domains.md) owns remit,
angle eligibility, content extensions, and distribution intent.

The existing implementation milestone remains deterministic detection ingestion
and its local dashboard, ending at selected `ContentThread` + `IntakeRequest`.
This strategy update does not migrate that database, enable production workers,
or claim that the five-domain publishing loop is implemented. Preserve that
observable slice while building the later stages in the
[implementation plan](plans/target-implementation.md).

Phase 1 includes Instagram static carousels and X-native single image + post
text. Image + thread is optional and separately gated. Reuse local HTML/CSS +
Playwright rendering. TikTok, YouTube Shorts, other video-first platforms,
AI-generated video, and Bluesky are outside scope; do not build for a future
video phase. No distributed queues, cloud workers, or generic plugin framework
are required.

## Document Router

| Work | Canonical reference |
| --- | --- |
| Identity, lineage, atomic handoffs, cross-record invariants | [Data model](specs/data-model.md) |
| Exact SQLite columns, constraints, indexes, migrations | [SQLite records](specs/data/records.md), after the data model |
| JSON producer/consumer boundary and version maturity | [Machine contracts](contracts/README.md), [registry](contracts/maturity.md) |
| Configuration releases, registries, account bindings, activation | [Configuration](specs/configuration.md) |
| Detection evidence, normalization, scoring, shortlist, recurrence | [Detection](specs/detection.md) |
| Intake, briefs, worth-producing decision, domain selection, angles, skips | [Intake and Determination](specs/idea-intake-and-determination.md) |
| Five domains, editorial remit, English teaching evidence | [Domain pipelines](pipelines/domains.md) |
| Canonical content, generation, adaptation, checkpoint and fan-out rules | [Content production](specs/content-production.md) |
| Instagram carousel and X image/text/thread composition | [Platform outputs](specs/platform-outputs.md) |
| Shared profiles, templates, fonts, rendering, quality | [Visual rendering](specs/visual-rendering.md) |
| Review interface, commands, routing trace, portfolio visibility | [Dashboard and HAI](specs/dashboard.md) |
| Polling, scheduling, processes, leases, freshness | [Worker runtime](specs/runtime.md) |
| Authorization, delivery adapters, attempts, cleanup, reconciliation | [Posting Agent](specs/posting.md) |
| Recovery, duplicates, artifact integrity, model budgets, external safety | [Reliability](specs/reliability.md) |
| Instagram account/API facts | [Meta reference](platforms/meta.md) |
| X account/API verification and optional-thread gate | [X reference](platforms/x.md) |
| Prior O2-only contract navigation | [O2 compatibility note](pipelines/o2-english-instagram.md) (not an active pipeline contract) |
| Implementation sequencing and acceptance evidence | [Target plan](plans/target-implementation.md) (noncanonical) |

Consult the [decision archive](archive/decisions.md) only for a specific historical
rationale. Do not update it as a routine change log.

### Required reading for a code change

Read this guide, then all rows applicable to the change. For any changed
persisted boundary also read `specs/data-model.md`, `specs/data/records.md`, and
the relevant machine contract/maturity entry. Do not implement a superseded
payload or infer future tables from the detection-only SQL.

| Planned change | Required Tier 2 reading |
| --- | --- |
| Detection, scoring, shortlist, recurrence | `specs/detection.md`, `specs/configuration.md`, `specs/runtime.md`; add dashboard when visibility changes |
| Human ideas, briefs, routing, angles, skip/rejection | `specs/idea-intake-and-determination.md`, `pipelines/domains.md`, `specs/configuration.md`, `specs/reliability.md`, `specs/dashboard.md` |
| Domain generation or canonical validation | `specs/content-production.md`, `pipelines/domains.md`, `specs/reliability.md`, `specs/runtime.md` |
| Output adaptation, caption/text, carousel/thread composition | `specs/content-production.md`, `specs/platform-outputs.md`, `specs/visual-rendering.md`, `specs/reliability.md`, relevant domain contract |
| Renderer, templates, fonts, artifact validation | `specs/visual-rendering.md`, selected profile, `specs/platform-outputs.md`, `specs/reliability.md`, `specs/runtime.md` |
| Dashboard read model | `specs/dashboard.md`, persisted record contracts |
| Human review, Post now, cancellation, reconciliation | `specs/dashboard.md`, `specs/posting.md`, `specs/runtime.md`, `specs/reliability.md`, selected output/platform contracts |
| Posting or provider adapter | `specs/posting.md`, `specs/platform-outputs.md`, `specs/runtime.md`, `specs/reliability.md`, `specs/dashboard.md`, `platforms/meta.md` or `platforms/x.md` |
| Worker, recovery, model ledger, capacity, storage | `specs/runtime.md`, `specs/reliability.md`, `specs/configuration.md`, owning stage contract |
| Configuration, account binding, readiness | `specs/configuration.md`, owning domain/output/platform contracts, `specs/reliability.md` |
| Migration/cutover | `specs/data-model.md`, `specs/data/records.md`, `specs/runtime.md`, `specs/reliability.md`, `specs/dashboard.md`, every affected owner |

## Components, Inputs, and Persisted Outputs

SQLite is the authoritative cross-worker boundary. Components poll, claim,
perform bounded work, and commit persisted results. The dashboard reads that
state and writes only narrow human commands; it never invokes a worker or API.

```text
External sources → Collector → observations in SQLite
  → deterministic Scout + shortlist → selected ContentThread + IntakeRequest
Human idea/rework → message + IntakeRequest in SQLite
  → Idea Intake → immutable BriefRevision + DeterminationRequest
  → Determination → decision + five domain route assessments
      → zero selected: rejection/block reasons, no generation
      → each selected domain + distinct angle: ContentJob + GenerationRun
  → Pipeline Runner / domain strategy → CanonicalContent + OutputRequests
  → Adaptation Worker / output adapter → ContentPackage + RenderRun
  → shared Visual Renderer → exact assets + ReviewRequest
  → human Post now → PostRequest + PostRecord
  → Posting Agent / delivery adapter → audited publication or uncertainty
```

Each cross-stage arrow is a SQLite handoff, not a direct module-to-module call.
Domain strategies are in-process dispatch within the Pipeline Runner; output
adapters are in-process dispatch within the Adaptation Worker; delivery adapters
are in-process dispatch within the Posting Agent. These internal strategies are
not separately scheduled services.

- Detection measures attention deterministically and uses no LLM. It never
  determines editorial value or pipeline selection.
- Intake freezes a route-neutral brief and coverage identity. It does not turn
  every trend into an English expression.
- Determination separately records editorial worth, domain fit, a supported
  angle for each selected domain, skipped domains with reasons, and operational
  blockers. One trend may select one, several, or no pipelines.
- `ContentJob` is the immutable domain/angle recipe. `GenerationRun` creates
  one platform-neutral `CanonicalContent`. An account or platform change is not
  a reason to regenerate that canonical content.
- An `OutputRequest` freezes one canonical-content/destination/format binding.
  Its `AdaptationRun` produces the immutable platform-specific `ContentPackage`
  (copy, metadata, visual specification). Sibling destinations reuse canonical
  content but have independent adaptation, rendering, review, and delivery.
- The renderer uses versioned HTML/CSS + Playwright and validated local assets.
  It makes no editorial change. Posting sends only the exact approved bytes and
  text; it never generates captions, tags, hashtags, visuals, or thread replies.

## Opportunity Intake and Revisions

Human and trend-origin ideas share `ContentThread` and immutable
`BriefRevision` history. Clarifications are durable requests. New evidence does
not silently reopen consumed opportunities or spend model budget. The 72-hour
candidate cooldown is only an eligibility condition; coverage, domain-angle,
canonical-content, output, and publication identities provide independent
duplicate protections. See [Intake](specs/idea-intake-and-determination.md),
[Detection](specs/detection.md), and [Data model](specs/data-model.md).

## Determination, Production, and Posting Boundaries

The central experiment is routing quality, not generating five versions of
everything. Distinct credible angles, deliberate skips, and whole-trend
rejection are successful outcomes. Potential monetization is an editorial
hypothesis, not permission to invent claims, affiliate links, or financial gains.

Domain content is generated once; platform adaptation follows it. Instagram
gets a domain-appropriate carousel. X gets concise native text and one static
card, with optional ordered thread text only after its safety contract is ready.
Shared [production](specs/content-production.md) and
[output](specs/platform-outputs.md) contracts own these boundaries.

Every package enters its own human review. **Post now** authorizes exactly one
package, destination, text, and final asset manifest and writes immediate
delivery intent. The Posting Agent applies account cadence before sending it.
There is no implicit cross-platform approval, batch publishing, or human
scheduling in Phase 1. Public posting is externally visible and potentially
irreversible; a possibly sent publication request is never automatically retried.
See [Posting](specs/posting.md) and [Reliability](specs/reliability.md).

## Local Operation and Verification

The Mac Mini remains the primary runtime; SQLite is the POC store and GCP Vertex
Gemini is the model provider. Existing detection commands are in the
[README](../README.md). These documentation changes do not authorize a database
reset, live publishing, account creation, or background production activation.

```sh
/opt/homebrew/bin/python3.12 -m venv .venv
./.venv/bin/python -m pip install -e '.[dev]'
./.venv/bin/python scripts/check_docs.py
./.venv/bin/python scripts/run_tests.py
```

On Windows use `py scripts/check_docs.py` and `py scripts/run_tests.py`.
Documentation-only changes require the first check; implementation changes
require both. Tests for existing code do not prove the new architecture runs.
Do not enable downstream workers before their exact schemas, migrations, and
boundary fixtures pass the [implementation gates](plans/target-implementation.md).

Use the local [environment template](../.env.example); never commit secrets.
Configuration and safe secret references are owned by
[Configuration](specs/configuration.md). External smoke tests that write temporary
R2 objects or publish real content require their own explicit authorization.
`scripts/smoke_test_o2_instagram.py --live` is legacy public-publishing code, not
a shortcut around the new review/authorization contracts.

## Documentation Ownership and Maintenance

Keep domain knowledge in `pipelines/domains.md`, shared canonical generation in
`specs/content-production.md`, output composition in `specs/platform-outputs.md`,
renderer mechanics in `specs/visual-rendering.md`, and delivery mechanics in
`specs/posting.md`. An output adapter and a delivery adapter are different
responsibilities even when both target Instagram or X.

The data model owns semantic identities and cross-record invariants; the exact
record contract/SQL owns executable constraints. Do not copy provider facts or
schema inventories into multiple documents. Update this guide only for
objective, routing, or ownership changes; update the focused owner with each
detailed contract change and its boundary tests. Keep archive history intact.
