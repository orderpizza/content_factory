"""Render first-wave shared visual archetypes locally; no database or provider is used."""
from __future__ import annotations

from argparse import ArgumentParser
from pathlib import Path
import sys

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from workflow.static_renderer import _unit_html
from workflow.visual_planner import choose_recipe


FIXTURES = {
    "vocab_card_minimal_v1": ("cards", ["Versatile", "Able to adapt or be used in many different ways.", "Try a versatile approach for different situations.", "Versatile means flexible and useful.", "Notice it, use it, remember it."]),
    "editorial_bold_cover_v1": ("editorial", ["50\nAMERICAN\nSLANG", "Useful informal expressions for everyday conversation.", "Keep the tone friendly and natural.", "Start with one phrase at a time.", "Use slang with context."]),
    "comparison_cover_bold_v1": ("comparison", ["NORMAL ENGLISH\nVS\nFINANCE ENGLISH", "One idea can sound different in a specialist setting.", "Plain language versus a precise finance term.", "Compare the purpose before choosing the words.", "Match language to the audience."]),
    "phrase_sheet_v1": ("cards", ["Offering help", "OFFERING HELP\nCan I help you?\nDo you need any help?\nCan I get you anything?\nREPLYING\nYes, please.\nThanks, I'd appreciate that.", "Could I give you a hand?\nThat would be helpful, thanks.", "Choose a phrase that fits the situation.", "Keep it practical and kind."]),
    "question_pattern_sheet_v1": ("cards", ["WHAT", "for things or information\nWhat is your favorite food?\nWhat time is it?\nWhat do you do on weekends?", "What would you like to know?\nWhat happened next?", "WHAT asks for information.", "Ask, listen, and follow up."]),
    "vocab_serif_elegant_v1": ("editorial", ["Ineffable", "Too great or intense to be expressed in words.", "The quiet view felt almost ineffable.", "A calm word for a powerful feeling.", "Keep a word that opens a thought."]),
    "dialogue_modern_v1": ("dialogue", ["A natural invitation", "Use a warm, direct phrase when you want to include someone.", "Would you like to join us?\nThat sounds great, thank you.\nWe are meeting after class.\nI'd love to come.", "Short exchanges make the pattern memorable.", "Invite clearly; reply warmly."]),
    "scenario_explainer_v1": ("scenario", ["A quiet reply", "Someone answers briefly in a meeting.\nThey may be thinking, not disagreeing.\nTry: Would you like a moment to add anything?", "A pause can mean reflection rather than rejection.", "Offer room without pressure.", "Interpret gently, then ask."]),
    "process_steps_v1": ("process", ["Learn a phrase", "Notice the phrase in context.\nSay it aloud twice.\nUse it in one short sentence.\nReview it tomorrow.", "Listen, repeat, and adapt the phrase.", "Small practice builds recall.", "Make the next use easy."]),
}

EXPRESSION_FIXTURE = {
    "structure": "cards",
    "roles": ["hook", "explanation", "explanation", "example", "example", "takeaway"],
    "units": [
        ("Break the ice", "Start a conversation and make people feel more comfortable."),
        ("What it means", "To start a conversation and make people feel more comfortable, especially in a new or awkward situation.\nSimilar to: make a friendly start to a conversation."),
        ("When to use it", "You meet someone for the first time\nThe atmosphere feels awkward or quiet\nYou want to include someone in a group\nYou’re in a new environment (e.g., work, school, event)"),
        ("Break the ice", "She told a funny story to break the ice at the meeting.\nI asked a casual question to break the ice with new classmates."),
        ("Break the ice", "A: It’s my first day here. I don’t really know anyone yet.\nB: No worries! Let’s break the ice. What do you like to do in your free time?\nA: I’m into hiking. How about you?"),
        ("Remember this", "Use it to start conversations and make others feel comfortable\nIt works well in new or awkward situations\nA simple question can help break the ice"),
    ],
}


def main() -> None:
    parser = ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=ROOT / "data" / "artifacts" / "visual-gallery")
    parser.add_argument("--archetype", choices=[*FIXTURES, "expression_breakdown_v1"], help="Render just one registered fixture.")
    args = parser.parse_args()
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    roles = ["hook", "explanation", "example", "example", "takeaway"]
    spec = {"width": 1080, "height": 1350}
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        try:
            page = browser.new_page(viewport={"width": 1080, "height": 1350}, device_scale_factor=1)
            fixtures = FIXTURES if args.archetype is None else {args.archetype: FIXTURES[args.archetype]} if args.archetype in FIXTURES else {"expression_breakdown_v1": None}
            for archetype_id, fixture in fixtures.items():
                if archetype_id == "expression_breakdown_v1":
                    structure, roles, units = EXPRESSION_FIXTURE["structure"], EXPRESSION_FIXTURE["roles"], EXPRESSION_FIXTURE["units"]
                else:
                    structure, copy = fixture
                    roles = ["hook", "explanation", "example", "example", "takeaway"]
                    units = []
                intent = {"schema_version": "visual_intent_v1", "primary_structure": structure, "tone": "friendly", "density": "medium", "emphasis_targets": ["takeaway"], "image_need": "none"}
                recipe, _ = choose_recipe(intent, platform="instagram", pipeline="english", account="gallery", unit_count=len(roles), unit_roles=roles, production=False, history=[], force_archetype=archetype_id)
                directory = output / archetype_id
                directory.mkdir(exist_ok=True)
                for ordinal, role in enumerate(roles, start=1):
                    if archetype_id == "expression_breakdown_v1":
                        title, body = units[ordinal - 1]
                    elif archetype_id == "dialogue_modern_v1":
                        dialogue_titles = ["A natural invitation", "What it means", "Listen and reply", "Your turn", "Takeaway"]
                        dialogue_bodies = [copy[1], copy[1], copy[2], copy[2], copy[4]]
                        title, body = dialogue_titles[ordinal - 1], dialogue_bodies[ordinal - 1]
                    else:
                        title = copy[ordinal - 1]
                        if ordinal == 1:
                            body = copy[1]
                        else:
                            title = {"explanation": "What it means", "example": "Try these", "takeaway": "Remember this"}[role]
                            body = copy[ordinal - 1]
                    unit = {"role": role, "title": title, "body": body, "claim_ids": []}
                    stem = f"slide-{ordinal:02d}-{recipe['unit_layouts'][ordinal - 1]['variant']}" if archetype_id == "expression_breakdown_v1" else f"instagram-{ordinal:02d}-{recipe['unit_layouts'][ordinal - 1]['variant']}"
                    path = directory / f"{stem}.html"
                    path.write_text(_unit_html(unit, spec, recipe, ordinal, len(roles)), encoding="utf-8")
                    page.goto(path.as_uri(), wait_until="load")
                    if not page.evaluate(
                        "document.body.scrollHeight <= document.body.clientHeight && "
                        "document.body.scrollWidth <= document.body.clientWidth && "
                        "Array.from(document.querySelectorAll('[data-bound]')).every("
                        "node => node.scrollHeight <= node.clientHeight && node.scrollWidth <= node.clientWidth)"
                    ):
                        raise RuntimeError(f"gallery layout overflow: {archetype_id} unit {ordinal}")
                    page.screenshot(path=str(path.with_suffix(".png")), type="png")
        finally:
            browser.close()
    print(output)


if __name__ == "__main__":
    main()
