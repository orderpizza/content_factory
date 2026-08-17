# Current Work

This is the authoritative operational status page. If it conflicts with an
older narrative in another document, this page describes the current target;
record the architectural change as a new entry in `decisions.md`.

## Current Target

Prove one end-to-end o2 English Instagram path:

```text
Trend Detection -> Determination -> ContentJob -> o2_english_instagram
-> ContentPackage -> Visual Rendering -> Posting Agent -> Instagram PostRecord
```

This is the current implementation target, not the system's final scope. The
same system will later support multiple platform-specific pipelines, including
Bluesky.

## Status

| Area | Status | Notes |
| --- | --- | --- |
| Detection | Active | Deterministic, LLM-free, persisted SQLite handoffs. |
| Determination | Active | Vertex Gemini selects consume/reject and a pipeline recipe. |
| o2 English idiom pipeline | Active | Fixed 5–8-slide `instagram_idiom_carousel` contract. |
| Visual rendering | Active | Deterministic HTML/CSS + Playwright at 1080×1920. |
| Posting Agent | Under development | Shared system component; platform delivery design is not settled. |
| Dashboard | Active, read-only | Detection is the current implemented view; other views follow module maturity. |

## Non-Negotiable Boundaries

- Detection identifies measurable attention; it never calls an LLM.
- Determination decides whether and how a candidate is consumed; it writes a
  `ContentJob` and never creates content.
- The selected pipeline creates the platform-specific content, caption, tags,
  hashtags, and visual specification.
- The renderer creates deterministic assets only.
- The Posting Agent will schedule and deliver ready packages; it will not alter
  creative metadata or assets.

## Acceptance Criteria For This Milestone

- A persisted candidate can result in one persisted o2 `ContentJob`.
- The o2 pipeline produces schema-valid structured carousel content with
  Gemini-generated caption, tags, and hashtags.
- All required 1080×1920 PNG assets are rendered and persisted on the package.
- The Posting Agent design is finalized separately, then one o2 package can be
  scheduled and published with an auditable `PostRecord`.

## Explicitly Deferred

- Additional o2 English formats, visual-matrix composition, and brand palette.
- Additional pipelines, including Bluesky implementation work.
- Dashboard approvals and workflow controls.
- Posting-platform implementation details until their system-level design is
  accepted.

## Working Agreement For Codex Sessions

Start with `AGENTS.md` and this page. Read the relevant component contract
before editing. Keep this page short: move durable architecture to
`architecture.md`, exact data contracts to `interfaces.md`, and dated decisions
to `decisions.md`.
