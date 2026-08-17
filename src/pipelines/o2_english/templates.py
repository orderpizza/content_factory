"""Fixed idiom-carousel template catalog extracted from daily_expression."""

from dataclasses import dataclass


IDIOM_CAROUSEL_PROFILE = "o2_english_idiom_carousel_v1"


@dataclass(frozen=True)
class SlideTemplate:
    template_id: str
    slide_type: str
    description: str


TEMPLATES = {
    "hook": SlideTemplate("o2_hook_centered_v1", "hook", "Large centered hook with highlighted target phrase."),
    "explanation": SlideTemplate("o2_explanation_standard_v1", "explanation", "Teaching copy with heading and rule."),
    "use_case_monologue": SlideTemplate("o2_usecase_monologue_v1", "use_case_monologue", "Quote-style example in a soft card."),
    "use_case_dialogue": SlideTemplate("o2_usecase_dialogue_v1", "use_case_dialogue", "Two offset chat bubbles."),
}


def template_for_slide(slide_type: str) -> SlideTemplate:
    try:
        return TEMPLATES[slide_type]
    except KeyError as error:
        raise ValueError(f"Unsupported o2 English idiom slide type: {slide_type}") from error
