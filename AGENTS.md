# Content Factory Instructions

## Project Rules

- This is a local-first automated content-factory POC. Mac Mini is the primary
  runtime, SQLite is the POC state store, and GCP is used for Vertex Gemini.
- Preserve persisted SQLite handoffs. Do not introduce direct module-to-module
  calls, distributed queues, or unnecessary infrastructure.
- Keep detection deterministic and LLM-free. Gemini belongs in determination
  and pipeline-owned generation only.
- Respect the responsibility chain:
  `Trend Detector -> Determination -> ContentJob -> Pipeline -> ContentPackage
  -> Visual Renderer -> Posting Agent -> PostRecord`.
- Pipelines are platform- and format-specific. `ContentJob` is a recipe;
  `ContentPackage` is the actual platform-specific content and metadata.
- Posting never generates or changes captions, tags, hashtags, or visual
  content. Its design is currently under development.
- The dashboard is read-only. Never put workflow controls in it without an
  explicit decision.
- Keep secrets out of the repository. Isolate external API access behind small
  services or adapters.

## How To Start Work

1. Read `docs/current.md` first.
2. Read `docs/architecture.md` for responsibility boundaries and
   `docs/interfaces.md` before changing a handoff or model.
3. Read `docs/roadmap.md` for scope and `docs/decisions.md` for prior decisions.
4. Update `docs/current.md` when the current target, status, acceptance criteria,
   or explicitly deferred work changes.

## Development Rules

- Use explicit models and persisted statuses at component boundaries.
- Add or update boundary tests for meaningful behavior changes.
- Run `py scripts/run_tests.py` and `py scripts/check_docs.py` before handoff.
- Document a new architectural choice as a new dated entry in
  `docs/decisions.md`; do not rewrite an earlier decision to erase history.
- Do not modify unrelated dirty-worktree files.
