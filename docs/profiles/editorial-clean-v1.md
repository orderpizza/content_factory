# Editorial Clean Profile — `editorial_clean_v1`

**Document role:** Versioned renderer-profile contract referenced by the
[Visual Rendering specification](../specs/visual-rendering.md). It defines the
tokens, templates, and regression protocol for this reusable profile.
**Owner:** Visual Rendering Layer.

## Maturity and current use

This immutable 1080×1920 profile is retained as a **legacy reference**. It is not
the Phase 1 Instagram or X delivery profile. Reuse its rendering approach and
compatible design tokens through a new version with independently validated
canvas geometry, bindings, and golden fixtures. Do not mutate old manifests or
resize old reviewed assets. The [output contract](../specs/platform-outputs.md)
owns the proposed platform canvas choices.

## Scope and frozen runtime

`editorial_clean_v1` is a light, typography-first profile for readable
educational, explanatory, announcement, and dialogue cards. It is pipeline
neutral. A package may use it only through a renderer profile/template mapping
materialized from its configuration release.

The initial runtime contract is `html_playwright_v1` with Python Playwright
`1.59.0`, Chromium/Chrome-for-Testing `147.0.7727.15`, Playwright browser
revision `1217`, a 1080×1920 CSS-pixel viewport, `device_scale_factor=1`,
`color_scheme=light`, locale `en-US`, timezone `UTC`, and headless mode. The
browser is launched with no external network access. A render records all of
those values, the operating-system platform, and the installed browser binary
hash in its manifest. A different value is a new renderer/profile version, not
a silent substitution.

The installed font manifest is part of the activated configuration release and
must contain these logical files with a nonempty SHA-256 for each byte file:

| Logical asset ID | Repository-relative path | Face / weight |
| --- | --- | --- |
| `noto_sans_regular_v1` | `assets/fonts/NotoSans-Regular.ttf` | Noto Sans Regular / 400 |
| `noto_sans_bold_v1` | `assets/fonts/NotoSans-Bold.ttf` | Noto Sans Bold / 700 |

The renderer verifies each declared file against the release's exact SHA-256
before creating a page. The profile is not ready if either file or hash is
absent; system fonts and synthetic bold are forbidden. The selected Noto Sans
files must retain their OFL license notice in the local asset bundle.

## Tokens

All values below are sRGB. No template accepts an inline color, font, spacing,
or geometry override from a package binding.

| Token | Value | Use / requirement |
| --- | --- | --- |
| `canvas` | `#FAF7F2` | Default full-canvas background. |
| `surface` | `#FFFFFF` | Raised text/dialogue card. |
| `ink` | `#1B1B1B` | Primary text; contrast ≥4.5:1 on `canvas` and `surface`. |
| `muted_ink` | `#54514D` | Supporting text; contrast ≥4.5:1 on `canvas` and `surface`. |
| `accent` | `#0B6E69` | Emphasis/rule/bubble; white text only at ≥4.5:1. |
| `accent_soft` | `#D9F0EC` | Non-text highlight; uses `ink` text. |
| `warm` | `#B64A2D` | Secondary emphasis; white text only at ≥4.5:1. |
| `border` | `#D6D0C8` | One-pixel rules and card borders; never sole semantic signal. |
| `shadow` | `#00000014` | 8px y-offset, 24px blur, zero spread. |

Text sizes are CSS pixels: `display=112/118/700`, `title=80/88/700`,
`body=52/68/400`, `body_strong=52/68/700`, `label=32/40/700`, and
`dialogue=46/60/400`, expressed as `size/line-height/weight`. Letter spacing
is `0` except uppercase labels at `0.08em`. Text is left aligned, uses normal
word breaking, `hyphens:none`, and does not justify. The renderer rejects a
unit whose measured content exceeds its declared box; it never shrinks type,
truncates, ellipsizes, or introduces a line break beyond normal wrapping.

## Canvas and templates

Every unit has a 1080×1920 canvas and an immutable 96px left/right safe area
with 120px top/bottom safe areas. Coordinates below are `(x, y, width, height)`
in CSS pixels. A 12px baseline grid applies; values are already grid-aligned.
Bindings are escaped plain strings or ordered typed arrays only.

| Template | Geometry and bindings |
| --- | --- |
| `headline_focus_v1` (`hook_emphasis_v1`) | `expression:string` in `(96, 318, 888, 250)` with `display`; `hook:string` in `(96, 630, 888, 390)` with `title`; accent rule `(96, 250, 144, 12)`. Capacity: expression one normal-wrapped line; hook ≤16 words. |
| `definition_stack_v1` (`concise_explainer_v1`) | `expression:string` `(96, 220, 888, 120)` label; `definition:string` `(96, 410, 888, 520)` body strong; optional `usage_note:string` `(96, 1050, 888, 210)` body. Capacity: definition ≤34 words; optional note ≤12 words. |
| `context_card_v1` (`monologue_card_v1`) | `context_label:string` `(144, 420, 792, 80)` label; raised card `(96, 560, 888, 700)`; `example:string` `(144, 680, 792, 460)` body. Capacity: label ≤8 words; example ≤22 words. |
| `two_bubble_v1` (`chat_dialogue_v1`) | `speaker_a:string`, `message_a:string`, `speaker_b:string`, `message_b:string`; A label `(120, 370, 600, 48)`, A bubble `(96, 438, 700, 330)`; B label `(360, 910, 600, 48)`, B bubble `(284, 978, 700, 330)`. Bubbles have 36px radius, 32px internal padding, A uses `accent_soft`, B uses `surface`/`border`. Capacity: each message ≤14 words; each speaker ≤3 words. |

Every template renders a small nonbinding profile mark `editorial_clean_v1` at
`(96, 1704, 888, 40)` in `muted_ink`; it is fixed renderer text and not
pipeline copy. No image, remote asset, HTML, CSS, URL, or file path is a valid
binding for this profile version.

## Deterministic screenshot and output protocol

Templates inject a reset that sets all animation, transition, caret, scrolling,
and smooth-scroll durations to zero. The renderer loads only a local `file:`
or isolated local server document, waits for `document.fonts.ready`, waits two
successive `requestAnimationFrame` callbacks, verifies zero pending local asset
requests, then captures a full-viewport PNG. It sets `animations="disabled"`,
hides the caret, and rejects any console error or external request.

The PNG is lossless sRGB. The delivery JPEG is derived only from that verified
PNG using a pinned encoder recorded in the configuration release, baseline
JPEG, sRGB, quality 90, 4:4:4 chroma sampling, and a maximum 10 MiB per slide.
The manifest records input hashes, font/template/profile/runtime IDs, PNG and
JPEG hashes, dimensions, MIME types, bytes, and conversion command/version.

## Visual regression protocol

Golden fixtures live at
`tests/fixtures/visual/editorial_clean_v1/<template>/<fixture_id>/`, each with
one binding JSON, expected PNG, expected manifest subset, and fixture note.
Required fixtures are one normal case per template plus: maximum valid copy,
accent/white contrast, safe-area edge, missing font, missing asset, overflow,
and dialogue-balance cases.

Comparison requires equal 1080×1920 dimensions and opaque pixels. Convert both
sRGB PNGs to CIE Lab using IEC 61966-2-1 transfer functions and D65 white point;
calculate CIEDE2000 for every corresponding pixel. A pixel differs when
`DeltaE00 > 2.0`. The fixture passes only when differing pixels are at most
`0.5%` of `1080 * 1920` (10,368 pixels), no dimension/alpha error occurs, and
the expected manifest fields match exactly. No masks or ignored regions exist.

Changing a golden requires a new profile/template/runtime version, regenerated
candidate PNG and manifest, automated comparison evidence, and explicit Visual
Rendering Operator approval recorded in a configuration release. Updating a
golden to conceal an unexplained difference is prohibited. A renderer upgrade
may keep a fixture only after it passes this procedure; otherwise it is a new
version and existing approved packages remain untouched.

## Validation categories

The renderer reports one or more typed categories: `profile_unregistered`,
`template_unregistered`, `binding_schema_invalid`, `binding_capacity_exceeded`,
`font_missing`, `font_hash_mismatch`, `asset_missing`, `asset_hash_mismatch`,
`runtime_version_mismatch`, `external_request_blocked`, `console_error`,
`layout_overflow`, `layout_clipping`, `safe_area_violation`, `output_dimensions_invalid`,
`output_format_invalid`, `jpeg_encoding_invalid`, `manifest_incomplete`, and
`visual_regression_failed`. Any category blocks review availability.
