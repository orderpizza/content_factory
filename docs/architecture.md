# Architecture

This guide owns architecture and document routing. Focused specs describe current
code, configuration and persisted contracts.

## CURRENT: review generation and offline delivery authorization

The three domains are `english`, `ai_tech`, `psychology`. Each has one Instagram
destination. Domain IDs are editorial identities, never account IDs. Both
Detection and human ideas are first-class inputs for every domain.

```text
Source / Feed → Collector → Raw Feed Item → lexical clustering
→ local semantic resolution → frozen Cluster scoring → committed Opportunity
→ source-backed BriefRevision + DeterminationRequest

Human idea / reply → ContentThread + IntakeRequest
→ clarification or BriefRevision + DeterminationRequest

Determination → three domain assessments → EditorialPlanRun
→ immutable EditorialPlan + ContentJob + GenerationRun
→ canonical content → deterministic visual planning → Instagram adaptation
→ deterministic storyboard planning → deterministic prompt compilation → Gemini rendering
→ ReviewRequest + exact slides → dashboard
```

SQLite is the only persisted cross-worker interface. Workers claim records; they
never call the next worker. Detection is LLM-free: lexical `canonicalization_v2`,
pinned local MiniLM resolution and frozen `attention_v3` scoring. It selects
attention evidence, never editorial domains. Determination evaluates all three
remits against immutable evidence and catalogs. Editorial Planning selects the
angle and content lane from bounded alternatives before creating a job.

Each active account/domain has exactly three curated archetypes. The current
visual registry uses the one-account-per-domain limitation; account-first
multi-account ownership is not implemented. Deterministic planning
selects an immutable recipe from canonical semantics and recent account history
before Instagram adaptation. Account identity, archetype, compiler, technical
renderer contract and overlays are separate contracts; only an archetype is a
visual template. A persisted StoryboardPlan determines boards, provider aspect
ratios and splitting/normalization separately from the fixed final slide profile.
Content pagination freezes units in the package; render pagination packs them by
versioned deterministic text-load budgets. Six English slides may use multiple
image calls. Every final Instagram slide is 4:5 at 1080×1350. English produces 4–6
review PNGs; AI/Tech and Psychology produce 4–14 ordered review PNGs. The accepted English baseline prompt and overlays are preserved.
Unsupported combinations stop explicitly with no HTML fallback. See
[visual rendering](specs/visual-rendering.md) for the nine archetypes and provenance.

The generation acceptance boundary is review-ready slides visible in the dashboard.
Phase 3B1 adds an explicit offline path from a bound English PNG review to an
immutable JPEG delivery revision, local exact-asset report, separate human JPEG
approval, then separate Post now authorization. It reuses WorkflowStore publication
records and retains original evidence. Schema 19 has an explicit backed-up v18
migration; startup never upgrades data. Checkpoint 1 adds a disabled-by-default registered
Instagram factory, authenticated transport and preflight/run boundaries, tested
with fake HTTP/storage through production configuration. No live contract is
verified and no send command or automatic delivery worker is enabled. External
delivery and R2 staging remain offline-only. The read-only Phase 3A exporter remains available; the Phase 3B1
preparation command explicitly appends a separately reviewed delivery revision.
[Posting](specs/posting.md) owns both boundaries and the future adapter contract.
The dashboard reads evidence and persists review/planning commands; it invokes
neither providers nor workers. Planning through ContentJob creation ignores
storage admission; monitoring remains advisory there.

## Document Router

| Concern | Canonical reference |
| --- | --- |
| Commands, project map and limitations | [Current state](operations.md) |
| Identity, transactions, schema initialization and record inventory | [Data model](specs/data-model.md) |
| SQL/JSON contract ownership | [Contracts](contracts/README.md) |
| Detection and semantic evidence | [Detection](specs/detection.md) |
| Human conversation, briefs, three-domain decisions and editorial planning | [Intake and Determination](specs/idea-intake-and-determination.md) |
| Domain editorial policy | [Domains](pipelines/domains.md) |
| Nonsecret releases and settings | [Configuration](specs/configuration.md) |
| Dashboard visibility and commands | [Dashboard](specs/dashboard.md) |
| Polling, claims, retries and process operation | [Runtime](specs/runtime.md) |
| Canonical generation, Instagram adaptation and package contract | [Content production](specs/content-production.md) |
| Visual planning, local asset rendering and registry | [Visual rendering](specs/visual-rendering.md) |
| Publication and reconciliation | [Posting](specs/posting.md) |
| Recovery, budgets and external safety | [Reliability](specs/reliability.md) |
| Offline safeguards and opt-in live acceptance | [Testing](testing.md) |

### Required reading for a code change

Read this guide and current state first. For every changed persisted boundary,
also read the data model and executable contract.

| Change | Additional required reading |
| --- | --- |
| Detection | Detection, configuration, runtime; dashboard if visibility changes |
| Human ideas or routing | Intake and Determination, domains, configuration, reliability, dashboard |
| Dashboard | Dashboard and the owning stage contract |
| Generation/adaptation | Content production, domains, reliability |
| Rendering | Visual rendering, content production, runtime, reliability |
| Posting/review | Posting, dashboard, content production, reliability, runtime, owning record contract |
| Runtime/budgets/storage | Runtime, reliability, configuration and owning stage |
| Schema/configuration | Data model, configuration and affected stage contracts |


## Documentation maintenance

README is the short entry point; current state owns runnable commands. Each
focused spec owns one contract; executable SQL and in-code schemas own exact
fields. Update the owner with code changes and link instead of duplicating.
The [roadmap](roadmap.md) owns planned work and completion gates. Git retains source history;
immutable records retain runtime evidence. [Agent instructions](../AGENTS.md)
own safe editing and verification.

## TARGET: publish and measure before expanding

This section is direction, not implemented capability. The [product goal](product.md)
is a profitable, repeatable operation, initially for one Instagram account.
The selected first pilot is global English Learning at A1–B1. The
[roadmap](roadmap.md) sequences offline publishing foundations, separately authorized
real integration and measurement before expansion. English content/visual refinement
and paid quality calibration are last; current production topology is unchanged.
Complete a human-approved publication and measurement loop first: exact reviewed
assets → authorized delivery → reconciled publication receipt → observed outcomes
→ editorial decisions. Define measurement provenance and attribution before
claiming that engagement or revenue improved.

After that loop is demonstrated, separate account identity and editorial policy
from domains. An account will own its audience, voice, platform credentials,
review policy and performance history; domains remain reusable subject areas.
Canonical content, destination adaptation, rendering and delivery should retain
explicit boundaries. Other platforms follow demonstrated multi-account operation.

SQLite handoffs, immutable evidence, bounded cost and explicit human authorization
are current safeguards. Framework choice, account modeling and scheduling are
future design decisions; Phase 1 changes no runtime topology or schema.
See the [roadmap](roadmap.md) for gates and unresolved decisions.
