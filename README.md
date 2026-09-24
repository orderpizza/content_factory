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

English produces exactly six 1080×1350 Instagram review PNGs from one Gemini 3×2
storyboard. AI/Tech and Psychology produce 4–14 slides with deterministic
pagination across 1×1, 2×1, 2×2, and 3×2 boards; each domain has three curated
archetypes. Shared local processing makes every final slide 4:5 (1080×1350).
See the [visual rendering contract](docs/specs/visual-rendering.md) for the
profiles, board mapping, split behavior, and review requirements. The dashboard
shows progress, evidence and exact review assets. Actual posting is outside the
current implementation scope; generic delivery records and R2 staging remain
preserved. The deterministic visual library and HTML renderer are preserved
inactive.

Start with [operations](docs/current-state.md), [architecture and document
ownership](docs/system.md), and [agent instructions](AGENTS.md).
`.env.example` is the canonical tracked inventory of operator settings; actual
values belong in ignored `.env`. Planning-only mode stops at ContentJobs.
