# Content Factory

Local-first content production on a Mac Mini, with SQLite worker handoffs and a
loopback dashboard. Automatic Detection and human ideas can both reach any of
three domains: `english`, `ai_tech`, `psychology`. Each domain has one Instagram
destination.

```text
Sources / Human ideas → Detection / Intake → Determination
→ Editorial Planning → immutable EditorialPlan → ContentJob
→ Canonical generation → Visual planning → Instagram adaptation → Gemini rendering → Review
```

All three domains produce six 1080×1350 Instagram review PNGs using one Gemini
3×2 storyboard call and shared local processing. English uses
`expression_breakdown_v1`, AI/Tech uses `ai_tech_explainer_v1`, and Psychology
uses `psychology_explainer_v1`, each with its own prompt profile. The dashboard shows
progress, evidence and exact review assets. Actual posting is outside the current
implementation scope; generic delivery records and R2 staging remain preserved.
The deterministic visual library and HTML renderer are preserved inactive.

Start with [operations](docs/current-state.md), [architecture and document
ownership](docs/system.md), and [agent instructions](AGENTS.md).
`.env.example` is the canonical tracked inventory of operator settings; actual
values belong in ignored `.env`. Planning-only mode stops at ContentJobs.
