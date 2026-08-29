# Content Factory Instructions

## Project Rules

- This is a local-first automated content-factory POC. Mac Mini is the primary
  runtime, SQLite is the POC state store, and GCP is used for Vertex Gemini.
- Preserve persisted SQLite handoffs. Do not introduce direct module-to-module
  calls, distributed queues, or unnecessary infrastructure.
- Keep detection deterministic and LLM-free. Gemini belongs only in
  determination, pipeline-owned generation, and the approved future Idea Intake
  Agent.
- Respect the responsibility chain:
  `Trend Detector -> Trend Shortlist -> Determination -> ContentJob -> Pipeline
  -> ContentPackage -> Visual Renderer -> Review (planned) -> Posting Agent`.
- Pipelines are platform- and format-specific. `ContentJob` is a recipe;
  `ContentPackage` is the actual platform-specific content and metadata.
- Posting never generates or changes captions, tags, hashtags, or visual
  content. The current implementation may public-post ready packages; the
  approved human-review gate is not yet implemented.
- The dashboard is currently read-only. Its approved future controls persist
  human-intake and review records only; they never invoke workers or external
  APIs directly.
- Keep secrets out of the repository. Isolate external API access behind small
  services or adapters.

## How To Start Work

1. Read `docs/system.md` first. It is the primary Human–Agent Interface and
   current narrative source of truth.
2. Read only the focused specification needed by the change:
   `docs/specs/data-model.md` for persistence, `docs/specs/dashboard.md` for
   HAI/freshness, or `docs/specs/reliability.md` for worker/external safety.
3. Read the relevant pipeline or platform reference only when its detail is
   needed.
4. Consult `docs/archive/decisions.md` only when a specific historical rationale
   or conflict needs investigation; it is not required working context.
5. Update `docs/system.md` for current objective/ownership changes and the
   owning focused specification for detailed design changes.

## Development Rules

- Use explicit models and persisted statuses at component boundaries.
- Add or update boundary tests for meaningful behavior changes.
- Run `py scripts/run_tests.py` and `py scripts/check_docs.py` before handoff.
- Keep architecture detail in its owning specification and link rather than
  duplicate it. Preserve the historical decision archive without using it as a
  routine change log.
- Do not modify unrelated dirty-worktree files.
