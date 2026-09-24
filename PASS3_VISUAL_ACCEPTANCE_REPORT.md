# Pass 3 visual acceptance report

## Executive summary

**PASS 3 ACCEPTED — VISUAL RENDERING CONTRACT VALIDATED.**

Live Gemini Image evidence now covers the full active board family and both
processing paths: English's six-slide adaptive-split compatibility path and
dynamic 1×1, 2×1, 2×2, and 3×2 boards. The production renderer completed
4+1 and 6+6+2 multi-board runs, retained raw boards, created correctly ordered
1080×1350 review PNGs, applied overlays, and committed ReviewRequests. This is
acceptance of the rendering contract, not acceptance of Gemini typography,
posting automation, provider reliability, or Psychology editorial quality.

## Live evidence

| Contract evidence | Result |
| --- | --- |
| 1×1 | AI/Tech five-slide fixture, second board; PASS |
| 2×2 | AI/Tech five-slide fixture, first board; PASS |
| 3×2 | Frozen Detection AI/Tech journey and both 6-slide long-carousel boards; PASS |
| 4+1 multi-board orchestration | AI/Tech five-slide fixture completed sequentially; PASS |
| English adaptive path | Six-slide English fixture, one 3×2 5:4 board, ReviewRequest; PASS |
| 2×1 | Long-carousel third board, two 4:5 finals, ReviewRequest; PASS |
| 6+6+2 long pagination | Three sequential boards, all 14 ordered finals; PASS |
| Detection through review | Frozen Detection AI/Tech journey; PASS |

The closure campaign was deliberately limited to four image calls: one English
board and three boards for the 14-slide fixture. All four succeeded. The
English board ledger estimate was `$0.101572`; the long fixture's estimate was
`$0.303487`, for `$0.405059` in closure evidence. No text-stage calls or
automatic paid retries were used.

## English adaptive split

The production-shaped English fixture selected `expression_story_scene_v1` and
completed the normal English planner, prompt compiler, renderer, overlay and
ReviewRequest path. Its requested 3×2 board was a 2304×1856 PNG at 5:4, and all
six finals are 1080×1350 PNGs in order.

Gemini returned no confidently detectable shared border/margin family. The
accepted English fallback therefore ran exactly as designed:

| Diagnostic | Result |
| --- | --- |
| Split method | `equal_grid_fallback_v1` |
| Fallback | `true` |
| Outer crop box | `[0, 0, 2304, 1856]` |
| Detected gutters | none |
| Equal source cells | six 768×928 row-major rectangles |
| Normalization | centered Lanczos `ImageOps.fit` to 1080×1350 |

The local English labels, `o2_english` footer, seeded non-final CTA sequence,
and missing final-slide cue are present. The fallback result is visually
separable and crisp; no processing-induced crop or softness defect was found.

## 2×1 and long-pagination result

The existing 14-slide Psychology fixture completed its deterministic plan with
three sequential calls: 6+6+2. The two 3×2 boards were 2304×1856 PNGs; the
third 2×1 board was a 2528×1696 PNG at the planned 3:2 provider ratio. The 2×1
board split into two equal 1264×1696 source cells, then centered-Lanczos fit
them to ordered 1080×1350 finals 13 and 14. Counters run 1/14 through 14/14;
the final slide has no swipe cue. There were no swapped, duplicated, missing,
or processing-softened panels, and no material crop injury was observed.

This corrects the earlier report: the successful five-slide 4+1 fixture had
already proved live multi-board orchestration. The outstanding gaps were the
2×1 board and the longer 6+6+2 sequence, both now closed.

## Remaining visual debt

No deterministic rendering defect was found in the accepted evidence. Gemini's
rendered typography remains a mandatory human-review concern:

- The 2×1 fixture board renders the supplied word `without` as `wit-` / `whout`.
- Earlier evidence retained a malformed `ceess` and “Dareo certifications”; the
  English closure board also adds a model-authored `crack` label.

The examples remain structurally useful, but exact supplied copy, spelling,
extra model-authored labels, and semantic visual quality are not guaranteed by
image generation. Provider transport failures remain an operational concern;
the renderer deliberately has no automatic paid replay. Human review remains
mandatory, posting remains disabled, and the separate Psychology qualification
work is not resolved by this visual acceptance.

## Evidence locations

Ignored local workspaces retain immutable plans, prompts, raw provider boards,
manifests, final PNGs, SQLite ledgers and galleries; no provider assets,
databases, or credentials are committed.

- `data/acceptance/20260924T141256-927001fb/` — completed 2×2 + 1×1 / 4+1 fixture
- `data/acceptance/20260924T141553-3b7bc0af/` — completed frozen-Detection 3×2 journey
- `data/acceptance/20260924T233110-3dc0c5e2/cases/pass3_english_adaptive_grid_6/attempt-01/` — English adaptive fallback evidence
- `data/acceptance/20260924T233110-3dc0c5e2/cases/pass3_psychology_grid_6_plus_6_plus_2/attempt-01/` — completed 6+6+2 and 2×1 evidence

## Decision and next move

**PASS 3 ACCEPTED — VISUAL RENDERING CONTRACT VALIDATED.**

The next recommended work is **Visual Quality / Text Fidelity Strategy**:
decide whether Gemini should continue rendering both visuals and critical text,
or whether Gemini composition should be combined with deterministic rendering
for critical copy. Do not implement that strategy as part of Pass 3 closure.
