# Content Factory Instructions

## Project Rules

- This is a local-first automated content-factory POC. Mac Mini is the primary
  runtime, SQLite is the POC state store, and GCP is used for Vertex Gemini.
- Preserve persisted SQLite handoffs. Do not introduce direct module-to-module
  calls, distributed queues, or unnecessary infrastructure.
- Keep detection deterministic and LLM-free. Gemini belongs only in
  Idea Intake, Determination, and pipeline-owned generation.
- Respect the responsibility chain: a selected trend or human idea becomes a
  `ContentThread` and immutable `BriefRevision`; then
  `Determination -> ContentJob -> Pipeline -> ContentPackage -> Visual Renderer
  -> Review -> Posting Agent`.
- Pipelines are platform- and format-specific. `ContentJob` is a recipe;
  `ContentPackage` is the actual platform-specific content and metadata.
- Posting never generates or changes captions, tags, hashtags, or visual
  content. Public delivery requires the human-review and explicit
  delivery-authorization boundary defined by the Tier 2 contracts.
- The dashboard is the Human–Agent Interface: it persists human idea, review,
  and explicit delivery-authorization records, including **Post now**. It never
  invokes a worker or external API directly.
- Keep secrets out of the repository. Isolate external API access behind small
  services or adapters.

## How To Start Work

1. Read `docs/system.md` first. It is the primary Human–Agent Interface and
   current narrative source of truth.
2. Use the **Required reading for a code change** matrix in `docs/system.md`.
   Read every Tier 2 document named for the planned change before editing code.
3. Read the relevant pipeline or platform reference only when its detail is
   needed.
4. Consult `docs/archive/decisions.md` only when a specific historical rationale
   or conflict needs investigation; it is not required working context.
5. Update `docs/system.md` for current objective/ownership changes and the
   owning focused specification for detailed design changes.

## Development Rules

- Use explicit models and persisted statuses at component boundaries.
- Add or update boundary tests for meaningful behavior changes.
- When code changes a documented contract, update its canonical Tier 2 document
  in the same change. Update `docs/system.md` only for a routing, ownership, or
  top-level boundary change.
- Run `py scripts/run_tests.py` and `py scripts/check_docs.py` before handoff.
- Keep architecture detail in its owning specification and link rather than
  duplicate it. Preserve the historical decision archive without using it as a
  routine change log.
- Do not modify unrelated dirty-worktree files.
