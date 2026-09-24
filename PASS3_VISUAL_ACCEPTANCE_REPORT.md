# Pass 3 visual acceptance report

## Executive summary

**PASS 3 PARTIALLY ACCEPTED — specific visual and coverage defects remain.**
Live Gemini Image produced structurally valid, review-ready assets through the
production renderer. The strict 2×2, 1×1 and 3×2 contracts, split/normalization,
overlays, raw-asset retention and ReviewRequest creation have real evidence.
However, 2×1 and live multi-board processing did not complete after a provider
failure, and real generated text contains a visible misspelling. English's
adaptive margin/gutter path also lacks live evidence because its upstream
Generation call failed.

## Environment and cost

| Item | Result |
| --- | --- |
| Image model / requested size | `gemini-3.1-flash-image` / `2K` |
| Text model | `gemini-3-flash-preview` |
| Compiler / renderer contract | `gemini_storyboard_prompt_v4` / `image_storyboard_paginated_v2` |
| Image attempts / completed boards | 6 / 4 |
| Text attempts / completed | 9 / 7 |
| Settled ledger estimate | `$0.445809` |

The original five-case preflight planned 26 total calls (14 text, 12 image) and
`$6.11`, below the authorized `$10` / 15-image-call ceiling. The campaign used
focused, smaller runs after a local per-job admission mismatch was discovered;
no automatic paid retry occurred.

## Board coverage and 3A contract results

| Grid | Live evidence | Raw board / validation | Status |
| --- | --- | --- | --- |
| 1×1 | AI/Tech 5-slide fixture, board 2 | PNG, 1856×2304, 4:5; valid | PASS |
| 2×1 | None | The 14-slide fixture failed before its first board returned bytes | INCOMPLETE |
| 2×2 | AI/Tech 5-slide fixture, board 1 | PNG, 1856×2304, 4:5; valid | PASS |
| 3×2 | Frozen Detection AI/Tech journey | PNG, 2304×1856, 5:4; valid | PASS |
| Multi-board | None completed | 14-slide fixture provider `ClientError` before board 1 | INCOMPLETE |

Every successful board had one original PNG, a recorded requested ratio and raw
dimensions, SHA-256 hash, prompt hash, source rectangles, final hashes and
StoryboardPlan lineage. The local image-job cap initially allowed one board and
blocked a later board; the focused acceptance run used the authorized envelope
as its isolated job cap and completed the 4+1 case. This was an admission setup
defect, not an image-processing defect.

## 3B processing and visual inspection

The 5-slide fixture proved deterministic board order 4+1, row-major splitting,
global counters 1/5–5/5 and final-slide cue removal. The frozen-Detection
journey proved 3×2 row-major extraction and counters 1/6–6/6. All successful
final PNGs are exactly 1080×1350. No swapped, duplicated or missing panels,
overlay collision, or cross-panel composition was seen in the successful boards.

The transparent chrome is readable and unobtrusive: dynamic headers, counters
and non-final swipe cues are correct; no footer brand appears for AI/Tech.
Comparing raw-board cells with final PNGs showed no material softness, crop
damage or encoding degradation. The source rectangles are equal-grid cells and
the rendered UI lines/text remain crisp after Lanczos fit and overlay.

English margin/gutter diagnostics are **not exercised live**. The English Human
journey stopped at a classified Generation transport failure before StoryboardPlan
or image rendering; no equal-grid fallback or adaptive margin decision can be
claimed for this campaign.

## 3C full journey results

| Journey | Result |
| --- | --- |
| Human → English → ReviewRequest | Generation transport failure; no image attempt or ReviewRequest |
| Frozen Detection → AI/Tech → ReviewRequest | Complete six-slide 3×2 carousel; ReviewRequest created |
| Human → Psychology → ReviewRequest | Intake provider `504 DEADLINE_EXCEEDED`; no image attempt or ReviewRequest |

The completed Detection carousel used `ai_tech_product_ui_v1`. The fixture
carousel used `ai_tech_explainer_v1`; it is valid board evidence but not a
publication-quality editorial sample.

## Visual findings and failure taxonomy

| Category | Finding |
| --- | --- |
| Provider | One multi-board image `ClientError`; English Generation transport failure; Psychology Intake 504. All are retained as distinct errors. |
| Board contract / splitter / overlay | No deterministic defect observed on the four completed boards. |
| Text fidelity | The Detection board's “Unstated Details” panel renders **“Dareo certifications”** rather than the supplied “certifications”. The fixture carousel also paraphrases supplied body copy and includes malformed “ceess”. This is a Gemini visual-text defect. |
| Content density | The Detection carousel is readable and well structured; some visual labels add model-authored text beyond the adaptation copy and need human editing. |
| Aesthetics | The Detection product-UI carousel is coherent, legible and educational. The fixed fixture is structurally useful but visually generic and text-heavy. |

The strongest success is the frozen-Detection AI/Tech carousel: source-bound
content, six separable panels, precise overlays and a complete ReviewRequest.
The most important visual defect is provider-rendered text fidelity, not the
deterministic image-processing path.

## Evidence locations

Local, ignored acceptance workspaces retain raw boards, compiled prompts,
validation, manifests, final slides and galleries:

- `data/acceptance/20260924T141256-927001fb/` — 2×2 + 1×1 fixture
- `data/acceptance/20260924T141553-3b7bc0af/` — complete frozen-Detection carousel
- `data/acceptance/20260924T141719-18153459/` — Psychology Intake 504

No raw provider assets, databases or credentials are committed.

## Known non-visual debt

Psychology adaptation can still strengthen uncertain or scenario-bound language.
This campaign did not reach Psychology adaptation, so that publication-readiness
debt remains separate from the Intake provider failure and visual acceptance.

## Remaining risks and decision

- Obtain one successful 2×1/multi-board run before treating the dynamic
  paginated renderer as fully accepted.
- Obtain a real English board before accepting adaptive margin/gutter handling.
- Keep human review mandatory for Gemini-rendered typography and model-authored
  labels; correct misspellings before publication.
- Provider reliability/resume remains operational debt; no automatic paid retry
  is implemented.

**PASS 3 PARTIALLY ACCEPTED — specific visual defects remain.** Continue with
the proven renderer contract, but run the smallest replacement evidence cases
when the provider is healthy: one English 3×2 board and one 14-slide dynamic
multi-board carousel. Posting remains disabled.
