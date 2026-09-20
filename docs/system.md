# Content Factory System Guide

This is the architecture and document-owner index. Read
[current operations](current-state.md), then only the focused contracts relevant
to the change. [The roadmap](plans/target-implementation.md) is the sole future
backlog. Specs describe implemented behavior and its limits, not proposed features.

## Current Objective

Make both Detection and human ideation observable through Determination and
ContentJobs on the local Mac Mini. SQLite is the only cross-worker handoff.
The dashboard is the human interface; it never invokes a worker or provider.

Pipelines are domain intelligence, not accounts or platforms.
[The domain catalog](pipelines/domains.md) owns the five remits and quality criteria.

## Components, Inputs, and Persisted Outputs

```text
Source / Feed → Collector → Raw Feed Items → lexical clusters
  → local semantic resolution → frozen Clusters → attention scoring
  → complete Detection Selection → Opportunities
  → ContentThread + source-backed BriefRevision + DeterminationRequest

Human idea/reply → ContentThread + message + IntakeRequest
  → Intake clarification, or BriefRevision + DeterminationRequest

Determination → decision + five domain routes
  → each selected route: ContentJob + pending GenerationRun
```

`--planning-only` stops here. The existing downstream implementation is:

```text
GenerationRun → CanonicalContent + OutputRequests
  → AdaptationRun → ContentPackage → RenderRun → ReviewRequest
  → exact human Post now → PostRequest + PostRecord → Posting Agent
```

Detection's `canonicalization_v2` handles lexical equivalence only. Pinned
local MiniLM compares plausible recent lexical clusters; its decisions are
frozen before deterministic `attention_v3` scoring. Linked members do not pool
scoring credit. Detection never calls an LLM or chooses an editorial domain.

Idea Intake interprets bounded human conversation, not routes or content.
Determination evaluates all five domains against the request's immutable
catalog and source evidence. Zero, one or several distinct angles may be chosen.
Each selected route atomically creates a job; no worker directly calls the next.

The dashboard shows Raw Feed Items, Clusters, Opportunities and ContentJobs as
separate linked views. Collection-attempt, source-health and Cluster Selection
statuses have different owners. Storage measurements are advisory through job
creation; they never admit or deny planning work.

The renderer owns assets; adaptation owns platform copy and metadata; posting
only delivers approved content. Default development destinations are synthetic
and non-deliverable. Production and delivery are explicit separate modes and
require configuration, readiness and exact per-package authorization.

## Document Router

| Concern | Canonical reference |
| --- | --- |
| Commands, environment, project map and limitations | [Current state](current-state.md) |
| Identity, transactions and record ownership | [Data model](specs/data-model.md) |
| Executable schema and record inventory | [SQLite records](specs/data/records.md) |
| SQL/JSON contract ownership | [Contracts](contracts/README.md) |
| Detection and semantic evidence | [Detection](specs/detection.md) |
| Human conversation, briefs, five-domain decisions | [Intake and Determination](specs/idea-intake-and-determination.md) |
| Domain editorial policy | [Domains](pipelines/domains.md) |
| Nonsecret releases and settings | [Configuration](specs/configuration.md) |
| Dashboard visibility and commands | [Dashboard](specs/dashboard.md) |
| Polling, claims, retries and process operation | [Runtime](specs/runtime.md) |
| Canonical generation and adaptation | [Content production](specs/content-production.md) |
| Instagram and X payloads | [Platform outputs](specs/platform-outputs.md) |
| Local asset rendering | [Visual rendering](specs/visual-rendering.md) |
| Publication and reconciliation | [Posting](specs/posting.md) |
| Recovery, budgets and external safety | [Reliability](specs/reliability.md) |
| Provider facts | [Meta](platforms/meta.md), [X](platforms/x.md) |

### Required reading for a code change

Read this guide and current state first. For every changed persisted boundary,
also read the data model, SQLite records and executable contract.

| Change | Additional required reading |
| --- | --- |
| Detection | Detection, configuration, runtime; dashboard if visibility changes |
| Human ideas or routing | Intake and Determination, domains, configuration, reliability, dashboard |
| Dashboard | Dashboard and the owning stage contract |
| Generation/adaptation | Content production, domains, platform outputs, reliability |
| Rendering | Visual rendering, platform outputs, runtime, reliability |
| Posting/review | Posting, dashboard, platform outputs, reliability, runtime, selected provider |
| Runtime/budgets/storage | Runtime, reliability, configuration and owning stage |
| Schema/configuration | Data model, records, configuration and affected stage contracts |

## Keeping the documents efficient

- README is the entry point, not a second runbook.
- Current state owns runnable capabilities, copyable operations and the project map.
- Each focused spec owns its detailed rules; link rather than repeat them elsewhere.
- SQL and in-code schemas own exact executable fields; prose explains meaning and limits.
- Roadmap owns proposed behavior, acceptance criteria and human decisions.
- Keep no dated audit/decision archive or verification diary. Git retains source
  history; immutable runtime records retain operational evidence.
- Keep version IDs only where code/configuration/persistence actually uses them.

Change the owning spec with its implementation, and update this router only when
ownership or top-level boundaries change. [Agent instructions](../AGENTS.md) own
the editing and verification workflow.
