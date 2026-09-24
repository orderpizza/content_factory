# Pass 3 visual acceptance report

## Executive summary

**PASS 3 BLOCKED.** The production rendering path and its opt-in acceptance
journey are ready for a bounded live campaign, but no Gemini Image acceptance
call was authorized or configured in this workspace. There is therefore no
honest live visual-quality conclusion yet.

## Environment

The configured production default image model is `gemini-3.1-flash-image` at
`2K`; the acceptance run records the actual configured model rather than relying
on this default. The compiler is `gemini_storyboard_prompt_v4` and the renderer
contract is `image_storyboard_paginated_v2`. No text or image provider calls
were made for this report, so total cost is `$0.00`.

## 3A board contract results

The Pass 3 dry-run profile admits three isolated, production-shaped cases:

| Origin/domain | Planned board coverage | Maximum image calls |
| --- | --- | ---: |
| Human / English | one 3×2, 5:4 board | 1 |
| Frozen Detection / AI/Tech | dynamic approved boards | 3 |
| Human / Psychology | dynamic approved boards | 3 |

No raw board exists yet. The renderer will validate original PNG/JPEG bytes,
size, pixels, cell minima, divisibility and requested-ratio tolerance before
any final slide is persisted.

## 3B processing results

No live images were processed. Offline coverage confirms the preserved English
adaptive margin/gutter path and the dynamic equal-grid, Lanczos,
center-fit-to-1080×1350 path. Live processing evidence will retain raw board
dimensions, source rectangles, split diagnostics, final hashes and overlay
metadata in each render manifest.

## 3C full journey results

The newly added `pass3` profile covers one Human English journey, one frozen
Detection AI/Tech journey and one Human Psychology journey through final
ReviewRequest. They have not run live. The profile’s conservative maximum is
seven image calls, before any provider failures; its maximum cost depends on
the locally supplied production image pricing.

## Archetype review

No archetype has live Pass 3 visual evidence yet. Archetype selection remains
the production deterministic selection; the campaign records the actual chosen
archetype rather than presuming one from a case name.

## Visual failure taxonomy

No live failures were observed. The acceptance result keeps provider, board
contract, splitter/overlay, content-density, text-fidelity and human visual
findings separate. `gallery.html` is deliberately a human-review surface, not
an LLM visual judge.

## Known non-visual debt

Psychology adaptation may still strengthen scenario-bound or uncertain canonical
language. This remains a publication-readiness warning and is not a rendering
contract failure.

## Remaining risks

- Live provider reliability, image text fidelity and board separability remain unobserved.
- A finite `LIVE_TEST_MAX_USD`, image pricing, Vertex configuration and the
  double opt-in are required before calls can be made.
- Provider failures have no automatic paid retry or resume path.

## Decision

**PASS 3 BLOCKED** pending an explicitly authorized, finite live Gemini Image
campaign. The recommended next step is to configure the local image budget and
run `--profile pass3 --live-gemini` with a reviewed ceiling, then inspect the
generated gallery and update this report with actual evidence.
