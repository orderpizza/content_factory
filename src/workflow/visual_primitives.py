"""Escaped, deterministic HTML primitives for registered visual layouts."""
from __future__ import annotations

from html import escape
from typing import Any


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


def footer(ordinal: int, total: int) -> str:
    return f'<footer class="visual-footer"><span>CONTENT FACTORY</span><span>{ordinal:02d} / {total:02d}</span></footer>'


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


def render_layout(unit: dict[str, Any], variant: str) -> str:
    title, body = unit["title"], unit["body"]
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
