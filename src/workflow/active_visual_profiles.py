"""Closed visual contracts for the three active Gemini review profiles.

This module deliberately contains no HTML layouts, generic archetype selection,
or fallback behavior.  It owns only the persisted semantic recipe envelope that
the active Gemini storyboard renderer needs.
"""
from __future__ import annotations

from collections.abc import Mapping
from hashlib import sha256
from typing import Any
import json


ACTIVE_VISUAL_PROFILE_RELEASE = "gemini_visual_profiles_v1"
INTENT_STRUCTURES = {"editorial", "dialogue", "comparison", "cards", "process", "scenario", "data", "quote"}
INTENT_TONES = {"friendly", "analytical", "professional", "playful", "serious", "minimal"}
INTENT_DENSITIES = {"low", "medium", "high"}
EMPHASIS_TARGETS = {"target_expression", "numbers", "difference", "steps", "quote", "takeaway"}
DOMAIN_ARCHETYPES = {
    "english": "expression_breakdown_v1",
    "ai_tech": "ai_tech_explainer_v1",
    "psychology": "psychology_explainer_v1",
}
EXPRESSION_ROLES = ("hook", "explanation", "explanation", "example", "example", "takeaway")
EXPLAINER_ROLES = ("hook", "explanation", "explanation", "example", "explanation", "takeaway")
EXPRESSION_LABELS = ("ENGLISH EXPRESSIONS", "MEANING", "WHEN TO USE IT", "EXAMPLE", "IN A CONVERSATION", "KEY TAKEAWAY")


EXPRESSION_ADAPTATION_GUIDANCE = """English expression Instagram grammar overrides the
generic 5-8 unit range. Return exactly six visual units in this order:
1. hook: a title of at most 5 words and a body of at most 20 words.
2. meaning / definition: first body line at most 35 words; every later line at
most 18 words.
3. when to use it / use cases: exactly 3-4 body lines, each at most 14 words.
4. examples: exactly 2 body lines, each at most 22 words.
5. short dialogue: exactly 3-4 body lines, each at most 16 words. Each line is
one speaker turn, formatted like `A: ...` or `B: ...`; never return a two-turn dialogue.
For example: `A: ...\nB: ...\nA: ...`.
6. takeaway / reminder: exactly 2-3 body lines, each at most 16 words.
Use roles hook, explanation, explanation, example, example, takeaway in that
same order. Preserve the target expression, meaning, usage and claim mappings,
but write compact slide-ready copy rather than paragraphs. Check every position
and line limit before returning JSON.
"""


def _lines(value: str) -> list[str]:
    return [line.strip(" •-\t") for line in value.splitlines() if line.strip(" •-\t")]


def _word_count(value: str) -> int:
    return len(value.split())


def validate_expression_units(units: list[Mapping[str, Any]]) -> None:
    """Validate the accepted English six-slide capacity contract."""
    if [unit.get("role") for unit in units] != list(EXPRESSION_ROLES):
        raise ValueError("expression breakdown requires its registered six-slide role sequence")
    hook, meaning, checklist, examples, dialogue, takeaway = units
    if _word_count(str(hook["title"])) > 5 or _word_count(str(hook["body"])) > 20:
        raise ValueError("expression hook exceeds its readable content capacity")
    meaning_lines = _lines(str(meaning["body"]))
    if not meaning_lines or _word_count(meaning_lines[0]) > 35 or any(_word_count(item) > 18 for item in meaning_lines[1:]):
        raise ValueError("expression definition exceeds its readable content capacity")
    checklist_lines = _lines(str(checklist["body"]))
    if not 3 <= len(checklist_lines) <= 4 or any(_word_count(item) > 14 for item in checklist_lines):
        raise ValueError("expression checklist must contain three or four concise rows")
    example_lines = _lines(str(examples["body"]))
    if len(example_lines) != 2 or any(_word_count(item) > 22 for item in example_lines):
        raise ValueError("expression examples require exactly two concise primary examples")
    dialogue_lines = _lines(str(dialogue["body"]))
    if not 3 <= len(dialogue_lines) <= 4 or any(_word_count(item) > 16 for item in dialogue_lines):
        raise ValueError("expression dialogue requires three or four concise turns")
    takeaway_lines = _lines(str(takeaway["body"]))
    if not 2 <= len(takeaway_lines) <= 3 or any(_word_count(item) > 16 for item in takeaway_lines):
        raise ValueError("expression takeaway requires two or three concise recap points")


_PROFILE_LAYOUTS = {
    "english": ("hook", "meaning", "use_cases", "examples", "dialogue", "takeaway"),
    "ai_tech": ("hook", "what_it_is", "how_it_works", "example", "limitations", "takeaway"),
    "psychology": ("hook", "concept", "mechanism", "example", "response", "takeaway"),
}


def profile_fingerprint() -> str:
    value = {"release": ACTIVE_VISUAL_PROFILE_RELEASE, "archetypes": DOMAIN_ARCHETYPES,
             "layouts": _PROFILE_LAYOUTS, "roles": {"english": EXPRESSION_ROLES, "explainer": EXPLAINER_ROLES}}
    return sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def validate_intent(value: Any) -> dict[str, Any]:
    expected = {"schema_version", "primary_structure", "tone", "density", "emphasis_targets", "image_need"}
    if not isinstance(value, Mapping) or set(value) != expected or value["schema_version"] != "visual_intent_v1":
        raise ValueError("visual intent has an invalid closed shape")
    if value["primary_structure"] not in INTENT_STRUCTURES or value["tone"] not in INTENT_TONES or value["density"] not in INTENT_DENSITIES:
        raise ValueError("visual intent has unsupported semantic values")
    emphasis = value["emphasis_targets"]
    if value["image_need"] not in {"none", "optional", "required"} or not isinstance(emphasis, list):
        raise ValueError("visual intent image or emphasis values are invalid")
    if len(emphasis) > 4 or len(set(emphasis)) != len(emphasis) or any(item not in EMPHASIS_TARGETS for item in emphasis):
        raise ValueError("visual intent emphasis targets are invalid")
    return dict(value)


def active_recipe(pipeline_id: str, roles: list[str]) -> dict[str, Any]:
    archetype_id = DOMAIN_ARCHETYPES.get(pipeline_id)
    expected_roles = EXPRESSION_ROLES if pipeline_id == "english" else EXPLAINER_ROLES
    if archetype_id is None or roles != list(expected_roles):
        raise ValueError("active Gemini profile does not support this package shape")
    return {
        "schema_version": "visual_recipe_v4",
        "registry_release": ACTIVE_VISUAL_PROFILE_RELEASE,
        "registry_fingerprint": profile_fingerprint(),
        "source": "gemini_domain_profile",
        "archetype_id": archetype_id,
        "preset_id": None,
        "family_id": "gemini_storyboard_v1",
        "composition_id": f"{pipeline_id}_storyboard_v1",
        "theme_id": "renderer_owned_v1",
        "typography_id": "renderer_owned_v1",
        "density": "medium",
        "components": {},
        "decorations": [],
        "image_treatment": "gemini_storyboard_v1",
        "unit_layouts": [
            {"ordinal": ordinal, "variant": variant}
            for ordinal, variant in enumerate(_PROFILE_LAYOUTS[pipeline_id], start=1)
        ],
    }


def validate_unit_layouts(recipe: Mapping[str, Any], roles: list[str]) -> None:
    pipeline_id = next((key for key, value in DOMAIN_ARCHETYPES.items() if value == recipe.get("archetype_id")), None)
    if pipeline_id is None:
        raise ValueError("visual recipe archetype is unavailable")
    expected_roles = EXPRESSION_ROLES if pipeline_id == "english" else EXPLAINER_ROLES
    expected_layouts = _PROFILE_LAYOUTS[pipeline_id]
    layouts = recipe.get("unit_layouts")
    if roles != list(expected_roles) or not isinstance(layouts, list):
        raise ValueError("visual recipe package roles do not match its active profile")
    if layouts != [{"ordinal": ordinal, "variant": variant} for ordinal, variant in enumerate(expected_layouts, start=1)]:
        raise ValueError("visual recipe layouts do not match its active profile")


def validate_recipe(value: Any, *, production: bool) -> dict[str, Any]:
    expected = {"schema_version", "registry_release", "registry_fingerprint", "source", "archetype_id", "preset_id", "family_id", "composition_id", "theme_id", "typography_id", "density", "components", "decorations", "image_treatment", "unit_layouts"}
    if not isinstance(value, Mapping) or set(value) != expected or value["schema_version"] != "visual_recipe_v4":
        raise ValueError("visual recipe has an invalid closed shape")
    if value["registry_release"] != ACTIVE_VISUAL_PROFILE_RELEASE or value["registry_fingerprint"] != profile_fingerprint():
        raise ValueError("active visual profile release is unavailable")
    pipeline_id = next((key for key, item in DOMAIN_ARCHETYPES.items() if item == value["archetype_id"]), None)
    if pipeline_id is None or value["source"] != "gemini_domain_profile" or value["preset_id"] is not None:
        raise ValueError("visual recipe is not an active Gemini domain profile")
    expected_recipe = active_recipe(pipeline_id, list(EXPRESSION_ROLES if pipeline_id == "english" else EXPLAINER_ROLES))
    if dict(value) != expected_recipe:
        raise ValueError("visual recipe differs from its active Gemini profile")
    return dict(value)
