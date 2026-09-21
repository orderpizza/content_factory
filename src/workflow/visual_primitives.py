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


def expression_footer(ordinal: int, total: int, *, brand_name: str = "O2English") -> str:
    """The expression carousel has an editorial footer, not the shared UI footer."""
    action = "Swipe →" if ordinal == 1 else "Keep learning! →" if ordinal == total else ""
    return (
        '<footer class="expression-footer">'
        f'<div class="expression-brand"><strong>{_text(brand_name)}</strong><span>Small Steps. A Bigger You.</span></div>'
        f'<span class="expression-action">{_text(action)}</span>'
        '</footer>'
    )


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
    path = "M3 14 C28 7 59 12 82 9 S135 13 177 7 L176 17 C135 20 102 15 73 18 S27 14 4 20 Z" if variant == "marker_highlight_01" else "M3 13 C27 9 48 14 76 10 S132 14 177 8 L176 17 C136 19 105 15 76 18 S28 15 4 19 Z"
    return f'<span class="marker-highlight {variant}"><svg viewBox="0 0 180 24" preserveAspectRatio="none" aria-hidden="true"><path d="{path}"/></svg><span>{_text(text)}</span></span>'


def underline_swash(*, variant: str = "underline_swash_01") -> str:
    return f'<svg class="underline-swash {variant}" viewBox="0 0 180 18" preserveAspectRatio="none" aria-hidden="true"><path d="M4 11 C48 3 106 17 176 7" fill="none" stroke="currentColor" stroke-width="7" stroke-linecap="round"/></svg>'


def accent_rays(*, variant: str = "accent_rays_01") -> str:
    return f'<svg class="accent-rays {variant}" viewBox="0 0 70 70" aria-hidden="true"><path d="M8 58 28 38M39 10v27M51 24 67 15" fill="none" stroke="currentColor" stroke-width="5" stroke-linecap="round"/></svg>'


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


def expression_emphasis(value: str, target: str) -> str:
    """Use a blue editorial marker for the expression in examples and dialogue."""
    if not target.strip():
        return _text(value)
    pieces: list[str] = []
    cursor = 0
    for match in re.finditer(re.escape(target), value, flags=re.IGNORECASE):
        pieces.append(_text(value[cursor:match.start()]))
        pieces.append(f'<span class="expression-emphasis">{_text(match.group())}</span>')
        cursor = match.end()
    pieces.append(_text(value[cursor:]))
    return "".join(pieces)


def expression_definition_card(body: str) -> str:
    definition, *note = _lines(body)
    note_html = "" if not note else f'<aside class="support-note">{icon_badge("check")}<p>{_text(" ".join(note))}</p></aside>'
    return f'<section class="expression-definition"><p>{_text(definition)}</p></section>{note_html}'


def expression_checklist(body: str) -> str:
    return '<section class="expression-checklist">' + ''.join(f'<div class="check-row">{icon_badge("check")}<p>{_text(line)}</p></div>' for line in _lines(body)) + '</section>'


def expression_examples(body: str, target: str) -> str:
    return '<section class="expression-examples">' + ''.join(f'<article class="example-card"><p>{expression_emphasis(line, target)}</p></article>' for line in _lines(body)) + '</section>'


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
        rows.append(f'<div class="expression-bubble-row {side}">{avatar(speaker, side=side)}<div><p class="expression-bubble">{expression_emphasis(copy, target)}</p></div></div>')
    return '<section class="expression-dialogue">' + ''.join(rows) + '</section>'


def expression_summary(body: str) -> str:
    return '<section class="expression-summary">' + ''.join(f'<div class="summary-row">{icon_badge("check")}<p>{_text(line)}</p></div>' for line in _lines(body)) + '</section>'


def expression_heading(value: str, layout: str, *, icon_name: str | None = None) -> str:
    heading = title_block(value, class_name=f"expression-title {layout}-title {headline_scale(value)}")
    return heading if icon_name is None else f'<div class="expression-heading {layout}-heading">{icon_badge(icon_name)}{heading}</div>'


def expression_topbar(label: str) -> str:
    return f'<header class="expression-topbar">{eyebrow(label)}<span class="expression-page">{{page}}</span></header>'


def expression_hero_title(value: str) -> str:
    """Split the expression deterministically to preserve the cover's two-line grammar."""
    words = value.split(maxsplit=1)
    if len(words) == 2:
        return f'<h1 class="title expression-title expression-hero-title {headline_scale(value)}">{marker_highlight(words[0])}<span class="hero-title-rest">{_text(words[1])}</span></h1>'
    return f'<h1 class="title expression-title expression-hero-title {headline_scale(value)}">{marker_highlight(value)}</h1>'


def expression_layout(unit: dict[str, Any], variant: str, *, avatars: list[dict[str, str]]) -> str:
    title, body = unit["title"], unit["body"]
    if variant == "hook_hero":
        return f'<main class="layout expression-layout hook-hero">{expression_topbar("ENGLISH EXPRESSIONS")}{accent_rays()}{expression_hero_title(title)}<p class="hook-teaser">{_text(body)}</p></main>'
    if variant == "meaning_definition":
        return f'<main class="layout expression-layout meaning-definition">{expression_topbar("MEANING")}{expression_heading("What does it mean?", "meaning", icon_name="lightbulb")}<div class="definition-stack">{expression_definition_card(body)}</div></main>'
    if variant == "use_case_checklist":
        return f'<main class="layout expression-layout use-case-checklist">{expression_topbar("WHEN TO USE IT")}{expression_heading("Use it when…", "checklist")}{expression_checklist(body)}<aside class="teaching-note">{icon_badge("pin")}<span>It’s a great way to create a friendly and relaxed atmosphere.</span></aside></main>'
    if variant == "example_cards":
        return f'<main class="layout expression-layout example-cards">{expression_topbar("EXAMPLE")}{expression_heading("In a sentence", "examples")}{expression_examples(body, title)}{accent_rays()}</main>'
    if variant == "dialogue_bubbles":
        return f'<main class="layout expression-layout dialogue-bubbles">{expression_topbar("IN A CONVERSATION")}{expression_dialogue(body, title, avatars)}{accent_rays()}</main>'
    if variant == "takeaway_summary":
        return f'<main class="layout expression-layout takeaway-summary">{expression_topbar("KEY TAKEAWAY")}{expression_heading("Remember!", "summary", icon_name="target")}{expression_summary(body)}<div class="closing-lockup"><p class="closing-line">Small conversations<br>can lead to big opportunities!</p>{underline_swash(variant="underline_swash_02")}</div>{accent_rays()}</main>'
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

EXPRESSION_RECOMPOSE_CSS = """
/* Expression breakdown: content-fitted, layout-specific teaching compositions. */
.expression-layout{--space-16:16px;--space-24:24px;--space-32:32px;--space-48:48px;--space-64:64px;--space-80:80px}.expression-layout .eyebrow{margin-bottom:var(--space-16)}.expression-layout .expression-title{margin:0;letter-spacing:-.055em;line-height:1.02;max-width:12ch}.expression-heading{display:flex;align-items:center;gap:var(--space-16)}.expression-heading .icon-badge{width:56px;height:56px;box-shadow:none}.expression-heading .title{margin:0}.meaning-title.headline_xl,.checklist-title.headline_xl,.examples-title.headline_xl,.dialogue-title.headline_xl,.summary-title.headline_xl{font-size:64px}.meaning-title.headline_l,.checklist-title.headline_l,.examples-title.headline_l,.dialogue-title.headline_l,.summary-title.headline_l{font-size:58px}.meaning-title.headline_m,.checklist-title.headline_m,.examples-title.headline_m,.dialogue-title.headline_m,.summary-title.headline_m{font-size:52px}.marker-highlight{position:relative;display:inline-block;background:none;padding:0 .04em;isolation:isolate}.marker-highlight svg{position:absolute;z-index:-1;left:-2%;bottom:1%;width:104%;height:48%;overflow:visible;fill:var(--highlight,#f6dc73);opacity:.92}.marker-highlight span{position:relative}.underline-swash{width:142px;height:14px}.underline-swash path{stroke-width:6}.accent-rays{width:58px;height:58px}.hook-hero{display:block;padding:330px 0 0}.hook-hero .eyebrow{top:0}.hook-hero .expression-title{max-width:9ch}.hook-hero .expression-title.headline_xl{font-size:94px}.hook-hero .expression-title.headline_l{font-size:82px}.hook-hero .expression-title.headline_m{font-size:70px}.hook-hero .accent-rays{top:35%;right:3%}.hook-teaser{font-size:33px;line-height:1.24;max-width:17ch;margin:var(--space-24) 0 0}.swipe-cue{bottom:6px}.meaning-definition{display:block;padding-top:8px}.meaning-heading{margin-top:var(--space-24)}.definition-stack{display:flex;align-items:stretch;gap:12px;margin:var(--space-32) 0 0}.expression-definition{min-height:0;padding:var(--space-32);border-radius:26px;box-shadow:0 8px 20px #17212b0a}.expression-definition p{font-size:31px;line-height:1.27;max-width:24ch;margin:0}.support-note{padding:14px 18px;border-radius:16px;box-shadow:none}.support-note .icon-badge{width:30px;height:30px}.support-note p{font-size:19px;line-height:1.25}.use-case-checklist{display:block;padding-top:8px}.use-case-checklist .expression-title{max-width:10ch}.expression-checklist{display:flex;gap:10px;margin:var(--space-32) 0 0}.check-row{gap:14px;border-radius:16px;padding:15px 18px;box-shadow:none}.check-row p{font-size:25px;line-height:1.2}.check-row .icon-badge{width:34px;height:34px}.teaching-note{margin-top:14px;padding:14px 16px;border-radius:14px;font-size:18px}.example-cards{display:block;padding-top:8px}.examples-heading{margin-top:var(--space-24)}.expression-examples{display:flex;gap:16px;margin:var(--space-32) 0 0}.example-card{min-height:0;padding:23px 25px;border-radius:22px;box-shadow:0 7px 18px #17212b08}.example-card span{margin-bottom:10px}.example-card p{font-size:27px;line-height:1.3}.example-card .marker-highlight svg{height:52%;opacity:1}.example-cards .underline-swash{margin:18px 0 0 10px}.dialogue-bubbles{display:block;padding-top:8px}.dialogue-heading{margin-top:var(--space-24)}.expression-dialogue{display:flex;gap:10px;margin:var(--space-32) 0 0}.expression-bubble-row{gap:12px}.avatar{width:70px;height:70px;border-width:4px}.expression-bubble-row>div{max-width:80%}.expression-bubble{padding:17px 21px;font-size:25px;line-height:1.25}.bubble-label{margin-bottom:3px}.takeaway-summary{display:block;padding-top:8px}.summary-heading{margin-top:var(--space-24)}.summary-heading .icon-badge{width:58px;height:58px}.expression-summary{display:flex;gap:14px;margin:var(--space-32) 0 0;padding:24px 26px;border-radius:25px;box-shadow:0 7px 18px #17212b08}.summary-row{gap:14px;padding:0;background:transparent;border-radius:0}.summary-row p{font-size:25px;line-height:1.25}.summary-row .icon-badge{width:34px;height:34px}.closing-line{font-size:21px;margin:var(--space-24) 0 0}.takeaway-summary .underline-swash{margin:12px 0 0 auto}
"""

EXPRESSION_RECOMPOSE_FINAL_CSS = """
/* The six expression units share tokens, but each owns its composition. */
.frame:has(.expression-layout){padding:56px 64px 42px;gap:14px;background:linear-gradient(145deg,color-mix(in srgb,var(--bg) 88%,white),var(--bg) 64%,color-mix(in srgb,var(--bg) 82%,var(--surface-secondary)))}
.expression-layout{font-family:"Avenir Next","Arial Rounded MT Bold",Arial,sans-serif;color:var(--text);overflow:hidden}
.expression-topbar{position:absolute;inset:0 0 auto;display:flex;align-items:center;justify-content:space-between;height:34px}.expression-topbar .eyebrow{position:static;margin:0;color:var(--text);font-size:15px;letter-spacing:.18em;font-weight:800}.expression-page{font-size:16px;letter-spacing:.08em;font-weight:800;color:var(--text)}
.expression-footer{height:58px;display:flex;align-items:end;justify-content:space-between;color:var(--text)}.expression-brand{display:flex;flex-direction:column;gap:2px}.expression-brand strong{font-size:18px;line-height:1;font-weight:900;letter-spacing:-.04em}.expression-brand span{font-size:11px;line-height:1.1;font-weight:600}.expression-action{min-width:180px;text-align:right;font-size:15px;font-weight:800;color:var(--text)}
.expression-layout .expression-title{font-family:"Avenir Next","Arial Rounded MT Bold",Arial,sans-serif;font-weight:900;letter-spacing:-.075em;color:var(--text)}.expression-heading{gap:24px}.expression-heading .icon-badge{width:100px;height:100px;background:color-mix(in srgb,var(--highlight) 45%,white);color:var(--text)}.expression-heading .icon{width:55px;height:55px;stroke-width:1.8}.meaning-title.headline_xl,.checklist-title.headline_xl,.examples-title.headline_xl,.summary-title.headline_xl{font-size:62px;line-height:.98}.meaning-title.headline_l,.checklist-title.headline_l,.examples-title.headline_l,.summary-title.headline_l{font-size:58px;line-height:.98}.meaning-title.headline_m,.checklist-title.headline_m,.examples-title.headline_m,.summary-title.headline_m{font-size:52px;line-height:1}
.expression-emphasis,.example-card .expression-emphasis{display:inline;color:#075da9;font-size:inherit;font-weight:900;line-height:1.04;letter-spacing:normal;margin:0;background:#afd8f5;border-radius:5px;padding:0 .08em;white-space:nowrap;box-decoration-break:clone;-webkit-box-decoration-break:clone}
.hook-hero{display:block;padding:206px 0 0}.hook-hero .expression-topbar{top:0}.expression-hero-title{display:flex;flex-direction:column;align-items:flex-start;gap:20px;max-width:7ch!important;margin:0}.expression-hero-title.headline_xl{font-size:230px;line-height:.72}.expression-hero-title.headline_l{font-size:192px;line-height:.76}.expression-hero-title.headline_m{font-size:154px;line-height:.82}.expression-hero-title .marker-highlight{line-height:.8;padding:0 .03em}.expression-hero-title .marker-highlight svg{left:-7%;bottom:-10%;width:114%;height:80%;fill:var(--highlight);opacity:1}.hero-title-rest{padding-left:.02em}.hook-hero .accent-rays{top:388px;right:36px;width:102px;height:102px;color:var(--text)}.hook-teaser{font-size:45px;line-height:1.22;font-weight:500;color:var(--text);max-width:15ch;margin:76px 0 0}
.meaning-definition{display:block;padding-top:142px}.meaning-heading{margin:0}.meaning-definition .expression-heading .icon-badge{width:138px;height:138px}.meaning-definition .expression-heading .icon{width:68px;height:68px}.meaning-definition .meaning-title{font-size:78px!important}.meaning-definition .definition-stack{display:flex;flex-direction:column;gap:32px;margin:82px 0 0}.meaning-definition .expression-definition{min-height:350px;background:linear-gradient(145deg,#f2f3f4,#f7f7f8);padding:52px 52px;border-radius:42px;box-shadow:none}.meaning-definition .expression-definition p{margin:0;font-size:42px;line-height:1.3;color:var(--text);max-width:20ch}.meaning-definition .support-note{display:flex;align-items:center;gap:25px;background:linear-gradient(100deg,#d9efdf,#d1ead8);padding:31px 34px;border-radius:34px;box-shadow:none}.meaning-definition .support-note .icon-badge{width:66px;height:66px;background:#2b9066;color:white}.meaning-definition .support-note .icon{width:38px;height:38px}.meaning-definition .support-note p{font-size:27px;line-height:1.28;font-weight:600;color:var(--text)}
.use-case-checklist{display:block;padding-top:128px}.use-case-checklist .expression-heading{margin:0}.use-case-checklist .expression-title{font-size:94px;line-height:.91;max-width:7ch}.use-case-checklist .expression-checklist{display:flex;flex-direction:column;gap:46px;margin:78px 0 0}.use-case-checklist .check-row{display:grid;grid-template-columns:68px 1fr;align-items:start;gap:26px;padding:0;background:transparent;border-radius:0}.use-case-checklist .check-row .icon-badge{width:64px;height:64px;background:#2e9364;color:#fff}.use-case-checklist .check-row .icon{width:36px;height:36px;stroke-width:2.5}.use-case-checklist .check-row p{font-size:37px;line-height:1.2;font-weight:500;color:var(--text);max-width:19ch}.use-case-checklist .teaching-note{display:flex;align-items:center;gap:24px;margin:74px 0 0;padding:32px 34px;background:linear-gradient(100deg,#ccebd7,#d9f2df);border-radius:34px;color:var(--text);font-size:27px;line-height:1.25;font-weight:600}.use-case-checklist .teaching-note .icon-badge{width:62px;height:62px;background:transparent;color:#267a52}.use-case-checklist .teaching-note .icon{width:54px;height:54px}
.example-cards{display:block;padding-top:132px}.example-cards .examples-heading{margin:0}.example-cards .expression-title{font-size:92px}.example-cards .expression-examples{display:flex;flex-direction:column;gap:40px;margin:78px 0 0}.example-cards .example-card{min-height:290px;width:100%;display:flex;align-items:flex-start;background:rgba(255,255,255,.88);border-radius:42px;padding:50px 52px;box-shadow:none}.example-cards .example-card p{width:100%;margin:0;font-size:42px;line-height:1.25;font-weight:500;color:var(--text);max-width:18ch;text-align:left}.example-cards .accent-rays{position:absolute;width:86px;height:86px;right:34px;top:1050px;color:#f2bd22}
.dialogue-bubbles{display:block;padding-top:98px}.dialogue-bubbles .expression-dialogue{display:flex;flex-direction:column;gap:42px;margin:105px 0 0}.dialogue-bubbles .expression-bubble-row{gap:24px;align-items:center}.dialogue-bubbles .expression-bubble-row.right{padding-left:40px}.dialogue-bubbles .avatar{width:156px;height:156px;border:0;background:linear-gradient(145deg,#c9ddff,#b8b8ef);padding:8px;box-shadow:none}.dialogue-bubbles .avatar-right{background:linear-gradient(145deg,#ffd3df,#f1bad0)}.dialogue-bubbles .avatar img{border-radius:50%;object-fit:contain}.dialogue-bubbles .avatar-placeholder{font-size:46px;background:white;color:var(--text)}.dialogue-bubbles .expression-bubble-row>div{max-width:575px}.dialogue-bubbles .expression-bubble{margin:0;padding:32px 34px;background:#fff;border-radius:36px 36px 36px 10px;font-size:34px;line-height:1.24;font-weight:500;color:var(--text);box-shadow:none}.dialogue-bubbles .right .expression-bubble{background:#ffe2e9;color:var(--text);border-radius:36px 36px 10px 36px}.dialogue-bubbles .accent-rays{position:absolute;right:22px;top:760px;width:74px;height:74px;color:var(--text)}
.takeaway-summary{display:block;padding-top:136px}.takeaway-summary .summary-heading{margin:0}.takeaway-summary .summary-heading .icon-badge{width:138px;height:138px;background:color-mix(in srgb,var(--highlight) 50%,white);color:#d94745}.takeaway-summary .summary-heading .icon{width:78px;height:78px;stroke-width:1.8}.takeaway-summary .expression-title{font-size:92px}.takeaway-summary .expression-summary{display:flex;flex-direction:column;gap:36px;margin:80px 0 0;padding:48px 46px;background:linear-gradient(145deg,#fff1c9,#ffedbc);border-radius:42px;box-shadow:none}.takeaway-summary .summary-row{display:grid;grid-template-columns:66px 1fr;align-items:start;gap:24px;padding:0;background:transparent}.takeaway-summary .summary-row .icon-badge{width:62px;height:62px;background:#f3b318;color:#fff}.takeaway-summary .summary-row .icon{width:35px;height:35px;stroke-width:2.7}.takeaway-summary .summary-row p{font-size:31px;line-height:1.25;font-weight:500;color:var(--text)}.closing-lockup{margin:78px 0 0 35px;position:relative;display:inline-block}.closing-line{font-family:"Snell Roundhand","Bradley Hand",cursive;font-size:47px;line-height:1.11;font-style:italic;font-weight:600;color:var(--text);margin:0}.closing-lockup .underline-swash{width:455px;height:30px;color:#f0be19;margin:14px 0 0 -8px}.closing-lockup .underline-swash path{stroke-width:8}.takeaway-summary .accent-rays{position:absolute;right:0;bottom:66px;width:70px;height:70px;color:#efb917}
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
