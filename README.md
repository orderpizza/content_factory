# Content Factory

Local-first AI content planning on a Mac Mini, with SQLite handoffs and a
loopback dashboard.

Detection turns Raw Feed Items into scored Clusters and selected Opportunities.
Human ideas enter through conversational Intake. Both feed five-domain
Determination; each selected domain gets a ContentJob. Planning-only mode stops
there, without generating or publishing content.

## Where to start

- [Current state and operations](docs/current-state.md): setup, commands, runtime
  modes, troubleshooting and verification limits.
- [Architecture and document router](docs/system.md): component ownership and
  focused specifications.
- [Roadmap](docs/plans/target-implementation.md): prioritized future work and
  genuine human acceptance.
- [Agent instructions](AGENTS.md): safe change workflow.

`.env.example` is the tracked settings template; `.env` is ignored local
configuration. Never commit credentials. Instagram, R2 and X credentials are
unnecessary for planning; actual Gemini calls require Vertex access and priced
budgets. Storage monitoring is advisory through ContentJob creation.

The dashboard separates Raw Feed Items, Clusters, Opportunities and ContentJobs
with evidence/origin links. Default workers are fixtures; editorial quality and
live provider access require explicit acceptance.
