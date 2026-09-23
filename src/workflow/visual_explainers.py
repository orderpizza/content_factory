"""Bounded dynamic copy contracts for AI/Tech and Psychology archetypes.

These checks protect shape and readable capacity, not factual or editorial truth.
"""
from collections.abc import Mapping

from .active_visual_profiles import validate_expression_units


DYNAMIC_GUIDANCE = """Return 4–14 concise visual units, normally 4–8. Expand with more units
when necessary, never denser copy. Exactly one hook first and one takeaway last;
interior roles are explanation or example, with at least one of each. Preserve
all canonical claims and qualifications. If 14 readable units cannot contain the
content, fail rather than dropping meaning; narrower planning is required.
Archetype slide entries are role-specific composition examples, not fixed positions.
"""
AI_TECH_ADAPTATION_GUIDANCE = DYNAMIC_GUIDANCE + """Cover what changed, how it works,
practical uses and limitations. Preserve availability_scope, as_of_context and
limitations visibly in explanation copy. Never invent product claims or benchmarks.
"""
PSYCHOLOGY_ADAPTATION_GUIDANCE = DYNAMIC_GUIDANCE + """Keep observation, concept,
possible mechanism, example, alternative explanations and practical implications
distinct. Preserve uncertainty and qualification in the takeaway and relevant units.
Avoid diagnosis, asserted private motives and medical advice.
"""
EXPLAINER_CAPACITY_GUIDANCE = """Titles: at most 80 characters, 12 words, 2 lines.
Bodies: at most 280 characters, 45 words, 5 lines, 18 words per line.
Keep takeaway qualification and caveats substantive. Do not drop claim mappings.
"""


def validate_dynamic_roles(roles):
    if (not 4 <= len(roles) <= 14 or roles[0] != 'hook' or roles[-1] != 'takeaway'
        or any(r not in {'explanation', 'example'} for r in roles[1:-1])
        or not {'explanation', 'example'}.issubset(roles[1:-1])):
        raise ValueError('dynamic carousel requires hook, explanation/example interiors, takeaway; 4–14 units')


def _validate_units(units, domain):
    if (not isinstance(units, list) or any(not isinstance(unit, Mapping) for unit in units)
            or not 4 <= len(units) <= 14):
        raise ValueError(f"{domain} requires its bounded dynamic role sequence")
    validate_dynamic_roles([u.get("role") for u in units])
    for ordinal, unit in enumerate(units, 1):
        for field, characters, words in (("title", 80, 12), ("body", 280, 45)):
            value = unit.get(field)
            if (not isinstance(value, str) or not value.strip() or len(value) > characters
                    or len(value.split()) > words
                    or len([line for line in value.splitlines() if line.strip()]) > (2 if field == "title" else 5)
                    or (field == "body" and any(len(line.split()) > 18 for line in value.splitlines()))):
                raise ValueError(f"{domain} slide {ordinal} {field} exceeds readable capacity")


def validate_ai_tech_units(units):
    _validate_units(units, "ai_tech")
    # A nontrivial body is required; humans assess whether it is a meaningful caveat.
    if not any(len(u["body"].strip()) >= 20 for u in units if u["role"] == "explanation"):
        raise ValueError("ai_tech requires substantive explanation/caveat copy")


def validate_psychology_units(units):
    _validate_units(units, "psychology")
    if len(units[-1]["body"].strip()) < 20:
        raise ValueError("psychology final slide requires takeaway and qualification copy")


def validate_domain_units(units, pipeline_id, *, strict_english: bool = False):
    if pipeline_id == "english" and strict_english:
        validate_expression_units(units)
    elif pipeline_id == "ai_tech":
        validate_ai_tech_units(units)
    elif pipeline_id == "psychology":
        validate_psychology_units(units)
