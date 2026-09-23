"""Shared six-slide copy contracts for AI/Tech and Psychology archetypes.

These checks protect shape and readable capacity, not factual or editorial truth.
"""
from collections.abc import Mapping

from .active_visual_profiles import (EXPLAINER_ROLES,
                                     validate_expression_units)


AI_TECH_ADAPTATION_GUIDANCE = """AI/Tech Instagram grammar overrides the generic 5-8 unit range:
Return exactly six visual units, with these positions and generic roles:
1. hook: Hook, identifying the topic or change.
2. explanation: What changed / what it is.
3. explanation: Why it matters / how it works.
4. example: Practical use / example.
5. explanation: Limitations / caveats. Include meaningful limitation, availability,
uncertainty or tradeoff content from canonical limitations, availability_scope and
as_of_context; never a placeholder or another benefit in this position.
6. takeaway: One practical takeaway.
Use product_or_feature, change_summary, capabilities and use_cases without
inventing current product claims, benchmarks, prices or availability.
"""
PSYCHOLOGY_ADAPTATION_GUIDANCE = """Psychology Instagram grammar overrides the generic 5-8 unit range:
Return exactly six visual units, with these positions and generic roles:
1. hook: Hook / observed pattern, using observed_behavior and context.
2. explanation: What the pattern means, using concept.
3. explanation: Possible mechanism / why it may happen, using possible_mechanism.
4. example: Everyday example / scenario; identify hypothetical examples as such.
5. explanation: Practical implication / response, using practical_implications.
6. takeaway: Takeaway + qualification; preserve qualification and relevant
alternative_explanations rather than erasing nuance in the summary.
Keep observation, inference, alternative explanations, practical implication and
qualification distinct. Preserve uncertainty, avoid diagnostic language, asserted
private motives and medical advice. Do not turn an interpretation into proof.
"""
EXPLAINER_CAPACITY_GUIDANCE = """For this six-slide grammar, keep each title concise: at most 80 characters
and 12 words. Each body must fit a readable 4:5 Instagram slide: at most 360
characters, 60 words and 5 nonempty lines. Aim below 240 characters. The AI/Tech
slide 5 caveat and Psychology slide 6 qualification each need at least 20
characters of substantive body copy. Preserve all canonical claim mappings and
qualifications within these bounds; do not drop claims to shorten the copy.
"""


def _validate_units(units, domain):
    if (not isinstance(units, list) or any(not isinstance(unit, Mapping) for unit in units)
            or [unit.get("role") for unit in units] != list(EXPLAINER_ROLES)):
        raise ValueError(f"{domain} requires its ordered six-slide role sequence")
    for ordinal, unit in enumerate(units, 1):
        for field, characters, words in (("title", 80, 12), ("body", 360, 60)):
            value = unit.get(field)
            if (not isinstance(value, str) or not value.strip() or len(value) > characters
                    or len(value.split()) > words
                    or len([line for line in value.splitlines() if line.strip()]) > 5):
                raise ValueError(f"{domain} slide {ordinal} {field} exceeds readable capacity")


def validate_ai_tech_units(units):
    _validate_units(units, "ai_tech")
    # A nontrivial body is required; humans assess whether it is a meaningful caveat.
    if len(units[4]["body"].strip()) < 20:
        raise ValueError("ai_tech slide 5 requires substantive caveat copy")


def validate_psychology_units(units):
    _validate_units(units, "psychology")
    if len(units[5]["body"].strip()) < 20:
        raise ValueError("psychology slide 6 requires takeaway and qualification copy")


def validate_domain_units(units, pipeline_id, *, strict_english: bool = False):
    if pipeline_id == "english" and strict_english:
        validate_expression_units(units)
    elif pipeline_id == "ai_tech":
        validate_ai_tech_units(units)
    elif pipeline_id == "psychology":
        validate_psychology_units(units)
