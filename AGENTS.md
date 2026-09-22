# Content Factory Working Instructions

## Start here

1. Read `docs/system.md` for architecture and document ownership.
2. Read `docs/current-state.md` for implemented modes and safe operations.
3. Follow the required-reading matrix in the system guide for the affected boundary.
   Read domain references when that detail is relevant.

## System boundaries

- Local-first Mac Mini PoC; SQLite is the persisted cross-worker interface.
  Do not introduce direct worker calls, distributed queues or cloud workers.
- Detection is LLM-free: deterministic lexical canonicalization, local MiniLM
  resolution and frozen deterministic scoring. Gemini is limited to Intake,
  Determination, canonical generation, Instagram adaptation and image rendering.
- Use Source / Feed, Raw Feed Item, Cluster, Opportunity, Determination Decision
  and ContentJob. An Opportunity requires a committed Detection handoff.
- A selected domain/angle creates a job. Generate platform-neutral canonical
  content once per job, then adapt for its Instagram destination.
  The only domains are `english`, `ai_tech`, `psychology`.
  Domain IDs are not account IDs.
- Adaptation owns copy/metadata; the shared renderer owns assets; posting only
  delivers exact reviewed content. Every destination needs its own Post now.
- The dashboard persists commands and reads evidence; it never invokes workers
  or providers. Preserve immutable snapshots, lineage and safe uncertain outcomes.
- Planning through ContentJob creation ignores storage admission. Monitoring is
  advisory; actual write errors and downstream production gates still apply.
- Deterministic workers are the default. `--gemini --planning-only` stops at jobs.
  `--gemini --review-preview` enables generation through review. Actual provider
  delivery is outside the current implementation scope.
- All three active domains use Gemini image rendering. Never silently substitute
  the inactive HTML renderer. English `expression_breakdown_v1` is the accepted
  visual baseline and must not be changed incidentally while modifying other
  domain profiles. Preserve its prompt, splitting, overlays and six-slide review.
- The deterministic visual library and its HTML renderer are preserved inactive;
  keep their assets, primitives, registry, gallery tooling and useful tests.

## Change discipline

- Explore code/tests before editing; specs must describe current behavior.
  Do not claim a planned safeguard exists or silently relax an implemented one.
- Use explicit persisted models/statuses and boundary tests. Preserve unrelated
  dirty-worktree changes and user data.
- Secrets stay outside tracked files, diagnostic logs and model inputs.
  Isolate external API access in small adapters.
- Do not run live provider checks, paid inference, public posts or non-temporary
  retention as routine verification.
- All workers use `database.current`. Setup creates a fresh database;
  never reset or migrate an existing database as an incidental repair.
- All Content Factory timestamps are UTC-naive ISO-8601 second-precision strings:
  `YYYY-MM-DDTHH:MM:SS`. Never persist `Z`, `+00:00`, other offsets, fractional
  seconds or local wall-clock timestamps. Convert external/aware timestamps to
  UTC before removing timezone information; use `common.timestamps` for parsing
  and serialization. An explicitly requested database migration is the sole
  exception to the no-incidental-migration rule.
- After documentation-only changes run `.venv/bin/python scripts/check_docs.py`.
  After code/tooling changes also run `.venv/bin/python scripts/run_tests.py`.

## Documentation maintenance

Keep one owner for each contract, as routed by `docs/system.md`. Update the owner
in the same change; link to it instead of duplicating its detail. Update
`docs/current-state.md` when runnable capabilities or operations change.

Keep repository documentation current. Do not add dated
audit registers, decision archives, migration narratives, verification diaries
or superseded algorithm descriptions. Retain version identifiers only when used
by running code, configuration or persisted evidence. Runtime history belongs in
its immutable records; source-change history belongs in Git.
