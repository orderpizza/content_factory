# Content Factory Instructions

## Project Rules

- The rules below define the target boundaries, not an implementation inventory.
  Code/tests establish current behavior; `docs/current-state.md` maps implemented,
  partial and legacy paths. Do not claim a planned safeguard already exists.
- This is a local-first automated content-factory POC. Mac Mini is the primary
  runtime, SQLite is the POC state store, and GCP is used for Vertex Gemini.
- Preserve persisted SQLite handoffs. Do not introduce direct module-to-module
  calls, distributed queues, or unnecessary infrastructure.
- Keep detection deterministic and LLM-free. Gemini belongs only in
  Idea Intake, Determination, domain generation, and bounded output adaptation.
- Respect the responsibility chain: a selected trend or human idea becomes a
  `ContentThread` and immutable `BriefRevision`; then
  `Determination -> domain/angle routes -> ContentJob -> GenerationRun
  -> CanonicalContent -> OutputRequest -> AdaptationRun -> ContentPackage
  -> RenderRun -> Visual Renderer -> ReviewRequest -> PostRequest -> PostRecord
  -> Posting Agent`. Zero, one, or several domains may be selected.
- Pipelines are domain/intelligence modules: `english`, `ai_tools`,
  `personal_finance`, `business_side_hustle`, and `psychology_behavior`.
  Keep pipeline identity separate from social account identity. Generate
  platform-neutral canonical content once, then adapt it for Instagram or X.
- Phase 1 is static: Instagram carousels and X-native image + text; threads are
  optional and gated. No TikTok, YouTube Shorts, AI video, or Bluesky.
- Output adaptation owns platform copy/metadata and visual-profile selection;
  the shared HTML/CSS + Playwright renderer owns assets. Delivery adapters do
  not generate. Every destination requires its own exact human approval.
- Posting never generates or changes captions, tags, hashtags, or visual
  content. Public delivery requires the human-review and explicit
  delivery-authorization boundary defined by the Tier 2 contracts.
- The dashboard is the Human–Agent Interface: it persists human ideas, replies,
  preview decisions, scoped review feedback, and—in schema v4—exact **Post now**,
  pre-final cancellation, and reconciliation commands. It never invokes a
  worker or external API directly.
- The runner keeps deterministic workers as its default. Its explicit
  `--gemini` mode may use Gemini for Idea Intake and Determination;
  `--review-preview` also enables canonical generation, output adaptation, and
  the local Playwright renderer. Synthetic mode remains non-deliverable.
  `--production` selects the immutable v4 real-destination catalog and priced
  admission; `--delivery` additionally composes credentialed adapters, but no
  public call is possible without one exact dashboard Post now authorization.
- Keep secrets out of the repository. Isolate external API access behind small
  services or adapters.

## How To Start Work

1. Read `docs/system.md` first for the target architecture/router, then
   `docs/current-state.md` for actual implementation and safe operations.
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
- For documentation-only work, run `.venv/bin/python scripts/check_docs.py` before handoff.
  For implementation work, run both `.venv/bin/python scripts/run_tests.py` and
  `.venv/bin/python scripts/check_docs.py` before handoff.
- Keep architecture detail in its owning specification and link rather than
  duplicate it. Preserve the historical decision archive without using it as a
  routine change log.
- Do not modify unrelated dirty-worktree files.
- Never run legacy publishing, live provider checks, public posting, or
  non-temporary retention as routine checks. V1–v4 workers use
  `database.migrations`; `database.sqlite` is incompatible legacy.
- Update `docs/current-state.md` when implemented capabilities or entrypoints
  change; keep future requirements in their focused specifications.
