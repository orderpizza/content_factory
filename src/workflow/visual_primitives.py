"""Escaped, deterministic HTML primitives for registered visual layouts."""
from __future__ import annotations

from html import escape
from typing import Any
import re

from .visual_expression import headline_scale


def _text(value: str) -> str:
    return escape(value).replace("\n", "<br>")


def _lines(value: str) -> list[str]:
    return [line.strip(" •-\t") for line in value.splitlines() if line.strip(" •-\t")] or [value]


def _split_vs(value: str) -> tuple[str, str]:
    for separator in ("\nVS\n", " vs ", " VS ", "\nvs\n"):
        if separator in value:
            left, right = value.split(separator, 1)
            return left.strip(), right.strip()
    lines = _lines(value)
    midpoint = max(1, len(lines) // 2)
    return " ".join(lines[:midpoint]), " ".join(lines[midpoint:])


def eyebrow(value: str) -> str:
    return f'<div class="eyebrow">{_text(value)}</div>'


def title_block(title: str, *, class_name: str = "") -> str:
    return f'<h1 class="title {class_name}">{_text(title)}</h1>'


def footer(ordinal: int, total: int, *, brand_name: str = "O2English") -> str:
    return f'<footer class="visual-footer"><span>{_text(brand_name)}</span><span>{ordinal:02d} / {total:02d}</span></footer>'


def icon(name: str) -> str:
    paths = {
        "lightbulb": '<path d="M9 18h6M10 22h4M8.2 14.4A6 6 0 1 1 15.8 14.4c-.8.7-1.3 1.5-1.5 2.6H9.7c-.2-1.1-.7-1.9-1.5-2.6Z"/>',
        "check": '<path d="m5 12 4 4L19 6"/>',
        "target": '<circle cx="12" cy="12" r="8"/><circle cx="12" cy="12" r="3"/><path d="m16 8 4-4"/>',
        "pin": '<path d="m14 4 6 6-3 1-3 5-1 4-2-4-5-3 4-2 1-3-6-6Z"/>',
        "arrow_right": '<path d="M5 12h14m-6-6 6 6-6 6"/>',
    }
    if name not in paths:
        raise ValueError("unknown local visual icon")
    return f'<svg class="icon icon-{name}" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">{paths[name]}</svg>'


def icon_badge(name: str) -> str:
    return f'<span class="icon-badge">{icon(name)}</span>'


def marker_highlight(text: str, *, variant: str = "marker_highlight_01") -> str:
    return f'<span class="marker-highlight {variant}">{_text(text)}</span>'


def underline_swash(*, variant: str = "underline_swash_01") -> str:
    return f'<svg class="underline-swash {variant}" viewBox="0 0 180 18" preserveAspectRatio="none" aria-hidden="true"><path d="M4 11 C48 3 106 17 176 7" fill="none" stroke="currentColor" stroke-width="7" stroke-linecap="round"/></svg>'


def accent_rays(*, variant: str = "accent_rays_01") -> str:
    return f'<svg class="accent-rays {variant}" viewBox="0 0 70 70" aria-hidden="true"><path d="M35 4v15M35 51v15M4 35h15M51 35h15M13 13l11 11M46 46l11 11M57 13 46 24M24 46 13 57" fill="none" stroke="currentColor" stroke-width="4" stroke-linecap="round"/></svg>'


def definition_card(body: str, *, pronunciation: bool = False) -> str:
    pronunciation_html = '<div class="pronunciation">/ learn · use · recall /</div>' if pronunciation else ""
    return f'<section class="definition-card">{pronunciation_html}<p>{_text(body)}</p></section>'


def highlight_strip(text: str) -> str:
    return f'<div class="highlight-strip">{_text(text)}</div>'


def bullet_list(body: str, *, class_name: str = "bullet-list") -> str:
    return '<ul class="%s">%s</ul>' % (class_name, "".join(f"<li>{_text(line)}</li>" for line in _lines(body)))


def phrase_groups(body: str) -> str:
    lines = _lines(body)
    groups: list[list[str]] = []
    current: list[str] = []
    for line in lines:
        if line.isupper() and current:
            groups.append(current); current = [line]
        else:
            current.append(line)
    if current: groups.append(current)
    output = []
    for group in groups[:3]:
        heading, *phrases = group
        phrase_text = "\n".join(phrases or [heading])
        output.append(f'<section class="phrase-group"><h2>{_text(heading)}</h2>{bullet_list(phrase_text, class_name="phrase-list")}</section>')
    return "".join(output)


def speech_bubbles(body: str) -> str:
    lines = _lines(body)
    if len(lines) == 1:
        lines = ["A", lines[0], "B", "Try it in a friendly tone."]
    output = []
    for index, line in enumerate(lines[:6]):
        side = "right" if index % 2 else "left"
        speaker = "YOU" if side == "right" else "PARTNER"
        output.append(f'<div class="bubble-row {side}"><span class="speaker">{speaker}</span><p class="speech-bubble">{_text(line)}</p></div>')
    return "".join(output)


def comparison_columns(title: str, body: str) -> str:
    left, right = _split_vs(title if "vs" in title.casefold() else body)
    return f'<section class="comparison-columns"><div><span>ONE</span><strong>{_text(left)}</strong></div><b>VS</b><div><span>TWO</span><strong>{_text(right)}</strong></div></section>'


def steps(body: str) -> str:
    values = _lines(body)[:5]
    return '<ol class="steps">' + ''.join(f'<li><span>{number}</span><p>{_text(value)}</p></li>' for number, value in enumerate(values, start=1)) + '</ol>'


def scenario_panels(body: str) -> str:
    values = _lines(body)
    labels = ("SCENARIO", "WHAT'S HAPPENING?", "TRY THIS")
    return ''.join(f'<section class="scenario-panel"><h2>{label}</h2><p>{_text(values[index] if index < len(values) else values[-1])}</p></section>' for index, label in enumerate(labels))


def _inline_emphasis(value: str, target: str) -> str:
    if not target.strip():
        return _text(value)
    pieces: list[str] = []
    cursor = 0
    for match in re.finditer(re.escape(target), value, flags=re.IGNORECASE):
        pieces.append(_text(value[cursor:match.start()]))
        pieces.append(marker_highlight(match.group(), variant="marker_highlight_02"))
        cursor = match.end()
    pieces.append(_text(value[cursor:]))
    return "".join(pieces)


def expression_definition_card(body: str) -> str:
    definition, *note = _lines(body)
    note_html = "" if not note else f'<aside class="support-note">{icon_badge("pin")}<p>{_text(" ".join(note))}</p></aside>'
    return f'<section class="expression-definition">{icon_badge("lightbulb")}<p>{_text(definition)}</p></section>{note_html}'


def expression_checklist(body: str) -> str:
    return '<section class="expression-checklist">' + ''.join(f'<div class="check-row">{icon_badge("check")}<p>{_text(line)}</p></div>' for line in _lines(body)) + '</section>'


def expression_examples(body: str, target: str) -> str:
    return '<section class="expression-examples">' + ''.join(f'<article class="example-card"><span>EXAMPLE {index}</span><p>{_inline_emphasis(line, target)}</p></article>' for index, line in enumerate(_lines(body), start=1)) + '</section>'


def avatar(asset: dict[str, str], *, side: str) -> str:
    visual = f'<img src="{asset["data_url"]}" alt=""/>' if asset.get("mode") == "asset" else f'<span class="avatar-placeholder">{_text(asset.get("initial", "?"))}</span>'
    return f'<span class="avatar avatar-{side}">{visual}</span>'


def expression_dialogue(body: str, target: str, avatars: list[dict[str, str]]) -> str:
    rows = []
    for index, line in enumerate(_lines(body)):
        side = "left" if index % 2 == 0 else "right"
        speaker = avatars[index % 2]
        raw = line.split(":", 1)
        label, copy = (raw[0].upper(), raw[1].strip()) if len(raw) == 2 else ("MIA" if side == "left" else "JAY", line)
        rows.append(f'<div class="expression-bubble-row {side}">{avatar(speaker, side=side)}<div><span class="bubble-label">{_text(label)}</span><p class="expression-bubble">{_inline_emphasis(copy, target)}</p></div></div>')
    return '<section class="expression-dialogue">' + ''.join(rows) + '</section>'


def expression_summary(body: str) -> str:
    return '<section class="expression-summary">' + ''.join(f'<div class="summary-row">{icon_badge("check")}<p>{_text(line)}</p></div>' for line in _lines(body)) + '</section>'


def expression_layout(unit: dict[str, Any], variant: str, *, avatars: list[dict[str, str]]) -> str:
    title, body = unit["title"], unit["body"]
    title_html = title_block(title, class_name=f"expression-title {headline_scale(title)}")
    if variant == "hook_hero":
        hero_title = f'<h1 class="title expression-title {headline_scale(title)}">{marker_highlight(title)}</h1>'
        return f'<main class="layout expression-layout hook-hero">{eyebrow("ENGLISH EXPRESSIONS")}{accent_rays()}{hero_title}<p class="hook-teaser">{_text(body)}</p><div class="swipe-cue">SWIPE {icon("arrow_right")}</div></main>'
    if variant == "meaning_definition":
        return f'<main class="layout expression-layout meaning-definition">{eyebrow("WHAT IT MEANS")}{title_html}<div class="definition-stack">{expression_definition_card(body)}</div></main>'
    if variant == "use_case_checklist":
        return f'<main class="layout expression-layout use-case-checklist">{eyebrow("WHEN TO USE IT")}{title_html}{expression_checklist(body)}<aside class="teaching-note">{icon_badge("pin")}<span>Natural, friendly and low-pressure.</span></aside></main>'
    if variant == "example_cards":
        return f'<main class="layout expression-layout example-cards">{eyebrow("IN A SENTENCE")}{title_html}{expression_examples(body, title)}{underline_swash()}</main>'
    if variant == "dialogue_bubbles":
        return f'<main class="layout expression-layout dialogue-bubbles">{eyebrow("HEAR IT NATURALLY")}{title_html}{expression_dialogue(body, title, avatars)}</main>'
    if variant == "takeaway_summary":
        return f'<main class="layout expression-layout takeaway-summary">{eyebrow("QUICK RECALL")}{icon_badge("target")}{title_html}{expression_summary(body)}<p class="closing-line">Use it to make a new moment feel easier.</p>{underline_swash(variant="underline_swash_02")}</main>'
    raise ValueError("unsupported expression breakdown layout")


def render_layout(unit: dict[str, Any], variant: str, *, avatars: list[dict[str, str]] | None = None) -> str:
    title, body = unit["title"], unit["body"]
    if variant in {"hook_hero", "meaning_definition", "use_case_checklist", "example_cards", "dialogue_bubbles", "takeaway_summary"}:
        return expression_layout(unit, variant, avatars=avatars or [])
    if variant in {"vocab_hero", "definition_card", "example_card", "recall_card"}:
        label = "VOCABULARY" if variant == "vocab_hero" else variant.replace("_", " ").upper()
        return f'<main class="layout vocab-layout">{eyebrow(label)}{title_block(title, class_name="word-title")}{definition_card(body, pronunciation=variant == "vocab_hero")}{highlight_strip("USE IT · NOTICE IT · REMEMBER IT")}</main>'
    if variant in {"bold_hook", "cover_detail", "cover_takeaway"}:
        label = "IDEA / " + variant.replace("_", " ").upper()
        return f'<main class="layout bold-cover">{eyebrow(label)}{title_block(title, class_name="poster-title")}{highlight_strip(body)}</main>'
    if variant in {"comparison_cover", "comparison_detail", "comparison_examples", "comparison_takeaway"}:
        return f'<main class="layout comparison-layout">{eyebrow("COMPARE THE DIFFERENCE")}{comparison_columns(title, body)}<p class="comparison-caption">{_text(body)}</p></main>'
    if variant in {"sheet_title", "phrase_groups", "sheet_recall"}:
        content = phrase_groups(body) if variant != "sheet_title" else definition_card(body)
        return f'<main class="layout sheet-layout">{eyebrow("PRACTICAL PHRASES")}{title_block(title)}{content}</main>'
    if variant in {"question_hero", "question_pattern", "question_examples", "question_recall"}:
        return f'<main class="layout question-layout">{eyebrow("QUESTION PATTERN")}{title_block(title, class_name="keyword-title")}{bullet_list(body, class_name="question-list")}</main>'
    if variant in {"serif_word", "serif_definition", "serif_example", "serif_takeaway"}:
        return f'<main class="layout serif-layout">{eyebrow("A WORD TO KEEP")}{title_block(title, class_name="serif-title")}<div class="serif-divider"></div><p class="serif-copy">{_text(body)}</p></main>'
    if variant in {"dialogue_hero", "dialogue_explanation", "dialogue_exchange", "dialogue_takeaway"}:
        content = speech_bubbles(body) if variant == "dialogue_exchange" else definition_card(body)
        return f'<main class="layout dialogue-layout">{eyebrow("SAY IT NATURALLY")}{title_block(title)}{content}</main>'
    if variant in {"scenario_hook", "scenario_analysis", "scenario_response", "scenario_takeaway"}:
        return f'<main class="layout scenario-layout">{title_block(title)}{scenario_panels(body)}</main>'
    if variant in {"process_hook", "numbered_steps", "step_cards", "process_recall"}:
        return f'<main class="layout process-layout">{eyebrow("STEP BY STEP")}{title_block(title)}{steps(body)}</main>'
    return f'<main class="layout default-layout">{eyebrow(unit["role"].upper())}{title_block(title)}{definition_card(body)}</main>'


EXPRESSION_CSS = """
.icon{width:1em;height:1em;display:block}.icon-badge{width:48px;height:48px;border-radius:50%;display:grid;place-items:center;background:var(--surface-secondary,var(--surface));color:var(--accent);flex:0 0 auto}.marker-highlight{display:inline;background:linear-gradient(transparent 48%,var(--highlight,#f6dc73) 48% 92%,transparent 92%);padding:0 .08em}.underline-swash{display:block;color:var(--accent);width:175px;height:17px}.accent-rays{position:absolute;color:var(--accent);width:70px;height:70px}.expression-layout{position:relative;min-height:0}.expression-title{font-size:72px;line-height:.98;margin-bottom:0;max-width:11ch}.headline_xl{font-size:100px}.headline_l{font-size:82px}.headline_m{font-size:66px}.hook-hero{display:flex;flex-direction:column;justify-content:center;padding:36px 0 58px}.hook-hero .eyebrow{position:absolute;top:0}.hook-hero .accent-rays{right:4%;top:14%}.hook-teaser{font-size:30px;line-height:1.26;max-width:18ch;margin:42px 0 0;color:var(--muted)}.swipe-cue{position:absolute;bottom:3px;right:0;font-size:14px;font-weight:800;letter-spacing:.1em;color:var(--accent);display:flex;align-items:center;gap:9px}.swipe-cue .icon{width:24px}.meaning-definition{display:grid;grid-template-rows:auto auto 1fr;gap:30px}.definition-stack{align-self:stretch;display:flex;flex-direction:column;justify-content:center;gap:24px}.expression-definition,.support-note{background:var(--surface);border-radius:32px;padding:32px;box-shadow:0 14px 34px #17212b12}.expression-definition{min-height:220px;display:flex;flex-direction:column;justify-content:space-between}.expression-definition p{font-size:31px;line-height:1.29;margin:28px 0 0;max-width:22ch}.support-note{display:flex;gap:16px;align-items:center;background:var(--surface-secondary,var(--surface));padding:20px 26px}.support-note .icon-badge,.teaching-note .icon-badge{width:36px;height:36px}.support-note p{font-size:20px;margin:0;color:var(--muted)}.use-case-checklist{display:flex;flex-direction:column;gap:24px}.expression-checklist{display:flex;flex-direction:column;gap:13px;flex:1;justify-content:center}.check-row,.summary-row{display:flex;align-items:center;gap:18px;background:var(--surface);border-radius:21px;padding:19px 22px}.check-row p,.summary-row p{font-size:26px;line-height:1.2;margin:0}.check-row .icon-badge,.summary-row .icon-badge{width:38px;height:38px;background:var(--accent);color:var(--surface)}.teaching-note{display:flex;align-items:center;gap:12px;padding:16px 18px;background:var(--surface-secondary,var(--surface));border-radius:17px;font-size:18px;color:var(--muted)}.example-cards{display:grid;grid-template-rows:auto auto 1fr auto;gap:28px}.expression-examples{display:grid;grid-template-rows:1fr 1fr;gap:22px;min-height:0}.example-card{background:var(--surface);border-radius:28px;padding:28px 31px;display:flex;flex-direction:column;justify-content:center;box-shadow:0 14px 34px #17212b12}.example-card span{font-size:13px;font-weight:800;letter-spacing:.12em;color:var(--accent);margin-bottom:17px}.example-card p{font-size:28px;line-height:1.27;margin:0}.dialogue-bubbles{display:grid;grid-template-rows:auto auto 1fr;gap:19px}.expression-dialogue{display:flex;flex-direction:column;justify-content:center;gap:14px}.expression-bubble-row{display:flex;align-items:flex-end;gap:13px}.expression-bubble-row.right{flex-direction:row-reverse}.avatar{width:58px;height:58px;border-radius:50%;background:var(--accent-secondary,var(--accent));display:grid;place-items:end;overflow:hidden;flex:0 0 auto;border:4px solid var(--surface)}.avatar img{width:100%;height:100%;object-fit:contain}.avatar-placeholder{width:78%;height:78%;border-radius:50% 50% 38% 38%;background:var(--surface);color:var(--accent);display:grid;place-items:center;font-weight:900;font-size:22px}.expression-bubble-row>div{max-width:75%}.bubble-label{display:block;font-size:11px;letter-spacing:.1em;font-weight:800;margin:0 0 4px 9px;color:var(--muted)}.right .bubble-label{text-align:right;margin-right:9px}.expression-bubble{margin:0;padding:16px 19px;background:var(--surface);border-radius:21px 21px 21px 6px;font-size:23px;line-height:1.27}.right .expression-bubble{background:var(--accent);color:var(--surface);border-radius:21px 21px 6px 21px}.takeaway-summary{display:flex;flex-direction:column;gap:22px;padding-top:4px}.takeaway-summary>.icon-badge{width:60px;height:60px}.expression-summary{display:flex;flex-direction:column;gap:12px;flex:1;justify-content:center;background:var(--surface);border-radius:31px;padding:26px}.closing-line{font-size:21px;line-height:1.25;color:var(--muted);margin:0}.takeaway-summary .underline-swash{margin-left:auto}
"""

PRIMITIVE_CSS = """
*{box-sizing:border-box} html,body{margin:0;width:100%;height:100%;overflow:hidden} body{font-family:var(--font);background:var(--bg);color:var(--text)}
.frame{height:100%;padding:clamp(38px,7vw,86px);display:grid;grid-template-rows:1fr auto;gap:22px;background-image:var(--decoration)}
.layout{min-height:0;overflow:hidden}.eyebrow{font-size:15px;font-weight:800;letter-spacing:.14em;color:var(--accent);margin-bottom:18px}.title{font-size:clamp(44px,6.8vw,82px);line-height:.98;letter-spacing:var(--tracking);margin:0 0 24px;font-weight:800}.visual-footer{display:flex;justify-content:space-between;font-size:13px;font-weight:800;letter-spacing:.11em;color:var(--muted)}
.definition-card{background:var(--surface);border:1px solid color-mix(in srgb,var(--accent) 22%,transparent);border-radius:28px;padding:24px 27px;box-shadow:0 14px 35px #17212b12}.definition-card p,.serif-copy,.comparison-caption{font-size:clamp(19px,2.25vw,31px);line-height:1.35;margin:0}.pronunciation{font-size:14px;letter-spacing:.08em;color:var(--accent);font-weight:800;margin-bottom:13px}.highlight-strip{display:inline-block;background:var(--accent);color:var(--surface);font-weight:800;font-size:14px;letter-spacing:.08em;padding:10px 14px;margin-top:18px}.word-title{font-size:clamp(56px,9vw,110px)}
.bold-cover{display:flex;flex-direction:column;justify-content:center}.poster-title{font-size:clamp(68px,11vw,144px);text-transform:uppercase;max-width:10ch}.comparison-layout{display:grid;grid-template-rows:auto 1fr auto}.comparison-columns{display:grid;grid-template-columns:1fr auto 1fr;gap:15px;align-items:stretch}.comparison-columns div{background:var(--surface);border-radius:22px;padding:25px 18px;display:flex;flex-direction:column;justify-content:center}.comparison-columns div:last-child{background:var(--text);color:var(--bg)}.comparison-columns span{font-size:12px;letter-spacing:.14em;font-weight:800;color:var(--accent)}.comparison-columns strong{font-size:clamp(30px,4.5vw,58px);line-height:1.02;margin-top:12px}.comparison-columns b{align-self:center;background:var(--accent);color:var(--surface);border-radius:50%;padding:12px 8px;font-size:17px}.comparison-caption{margin-top:18px;color:var(--muted)}
.sheet-layout,.question-layout{display:flex;flex-direction:column}.phrase-group{padding:13px 0;border-top:1px solid color-mix(in srgb,var(--accent) 40%,transparent)}.phrase-group h2{margin:0 0 8px;font-size:16px;letter-spacing:.08em;color:var(--accent)}.phrase-list,.question-list{margin:0;padding:0;list-style:none}.phrase-list li,.question-list li{font-size:clamp(17px,2vw,27px);line-height:1.28;padding:7px 0;border-bottom:1px solid #62707b26}.question-list li::before{content:"•";color:var(--accent);font-weight:900;margin-right:10px}.keyword-title{font-size:clamp(64px,10vw,128px);color:var(--accent)}
.serif-layout{padding:7% 4%;display:flex;flex-direction:column;justify-content:center}.serif-title{font-family:Georgia,Times,serif;font-size:clamp(65px,10vw,126px);font-weight:500}.serif-divider{width:96px;height:3px;background:var(--accent);margin:8px 0 26px}.serif-copy{max-width:24ch;color:var(--muted)}
.dialogue-layout{display:flex;flex-direction:column}.bubble-row{display:flex;align-items:flex-end;gap:10px;margin:7px 0}.bubble-row.right{flex-direction:row-reverse}.speaker{font-size:10px;letter-spacing:.08em;font-weight:800;color:var(--muted)}.speech-bubble{margin:0;max-width:73%;background:var(--surface);padding:14px 18px;border-radius:20px 20px 20px 5px;font-size:clamp(17px,2vw,27px);line-height:1.28}.right .speech-bubble{background:var(--accent);color:var(--surface);border-radius:20px 20px 5px 20px}.scenario-layout{display:grid;grid-template-rows:auto 1fr;gap:14px}.scenario-panel{padding:14px 18px;border-left:8px solid var(--accent);background:var(--surface);margin:8px 0}.scenario-panel h2{font-size:13px;letter-spacing:.1em;margin:0 0 5px;color:var(--accent)}.scenario-panel p{margin:0;font-size:clamp(16px,1.9vw,25px);line-height:1.25}.steps{margin:0;padding:0;list-style:none}.steps li{display:grid;grid-template-columns:42px 1fr;gap:14px;align-items:center;padding:10px 0;border-bottom:1px solid color-mix(in srgb,var(--accent) 36%,transparent)}.steps span{width:34px;height:34px;display:grid;place-items:center;border-radius:50%;background:var(--accent);color:var(--surface);font-weight:800}.steps p{margin:0;font-size:clamp(18px,2.2vw,28px);line-height:1.2}
"""
