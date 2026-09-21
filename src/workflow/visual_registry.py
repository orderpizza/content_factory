"""Version-controlled shared visual capabilities and closed recipe validation.

The registry is deliberately data, not prompt text or database-authored design.
Adding a visual normally means extending one of these bounded definitions and
the renderer primitive that declares support for it.
"""

from __future__ import annotations

from hashlib import sha256
from typing import Any, Mapping
import json


REGISTRY_RELEASE = "visual_registry_release_v1"
ENGINES = {"html_playwright_v1"}
LIFECYCLES = {"experimental", "tested", "curated", "deprecated"}
INTENT_STRUCTURES = {"editorial", "dialogue", "comparison", "cards", "process", "scenario", "data", "quote"}
INTENT_TONES = {"friendly", "analytical", "professional", "playful", "serious", "minimal"}
INTENT_DENSITIES = {"low", "medium", "high"}
EMPHASIS_TARGETS = {"target_expression", "numbers", "difference", "steps", "quote", "takeaway"}

THEMES = {
    "minimal_white_v1": {"lifecycle": "curated", "background": "#ffffff", "surface": "#f5f6f7", "text": "#17212b", "muted": "#53616d", "accent": "#487da6"},
    "warm_cream_v1": {"lifecycle": "curated", "background": "#f5f1e8", "surface": "#fffdf8", "text": "#1f2933", "muted": "#5e6871", "accent": "#c85a3f"},
    "soft_blue_v1": {"lifecycle": "curated", "background": "#eef5fa", "surface": "#ffffff", "text": "#17212b", "muted": "#53616d", "accent": "#487da6"},
    "soft_green_v1": {"lifecycle": "tested", "background": "#edf6ef", "surface": "#ffffff", "text": "#18352a", "muted": "#50665b", "accent": "#3e8b63"},
    "soft_lilac_v1": {"lifecycle": "tested", "background": "#f3effa", "surface": "#ffffff", "text": "#29223a", "muted": "#625b73", "accent": "#7256a8"},
    "dark_neutral_v1": {"lifecycle": "curated", "background": "#1e2429", "surface": "#2c353c", "text": "#f5f7f8", "muted": "#c1c8cd", "accent": "#8bc4ed"},
    "paper_v1": {"lifecycle": "tested", "background": "#f4eedf", "surface": "#fffaf0", "text": "#29251e", "muted": "#665f53", "accent": "#8a6534"},
}

TYPOGRAPHY = {
    "friendly_sans_v1": {"lifecycle": "curated", "family": "Arial, Helvetica, sans-serif", "title_scale": 1.0, "tracking": "-.035em"},
    "editorial_serif_v1": {"lifecycle": "tested", "family": "Georgia, serif", "title_scale": .94, "tracking": "-.025em"},
    "bold_display_v1": {"lifecycle": "curated", "family": "Arial Black, Arial, sans-serif", "title_scale": 1.05, "tracking": "-.05em"},
    "compact_sans_v1": {"lifecycle": "curated", "family": "Arial, Helvetica, sans-serif", "title_scale": .90, "tracking": "-.02em"},
}

FAMILIES = {
    "editorial_v1": {"features": {"takeaway", "quote"}, "fallback": "editorial_title_body_v1"},
    "dialogue_v1": {"features": {"dialogue", "target_expression", "quote"}, "fallback": "dialogue_stacked_transcript_v1"},
    "comparison_v1": {"features": {"comparison", "difference", "numbers"}, "fallback": "comparison_stacked_contrast_v1"},
    "cards_v1": {"features": {"cards", "takeaway"}, "fallback": "cards_feature_stack_v1"},
    "process_v1": {"features": {"process", "steps"}, "fallback": "process_vertical_steps_v1"},
    "scenario_v1": {"features": {"scenario", "quote"}, "fallback": "scenario_response_v1"},
    "data_v1": {"features": {"data", "numbers", "difference"}, "fallback": "data_number_context_v1"},
    "quote_v1": {"features": {"quote", "takeaway"}, "fallback": "quote_centered_focus_v1"},
}

def _composition(family: str, *, features: set[str], densities: set[str] = {"low", "medium", "high"}, lifecycle: str = "tested", platforms: set[str] = {"instagram", "x"}, fallback: str | None = None) -> dict[str, Any]:
    family_components = {
        "dialogue_v1": {"speech_bubble", "speaker_label"}, "comparison_v1": {"callout"},
        "process_v1": {"step_marker"}, "data_v1": {"number_marker"},
    }
    return {"family_id": family, "engine": "html_playwright_v1", "features": features,
            "densities": densities, "lifecycle": lifecycle, "platforms": platforms,
            "fallback": fallback, "components": {"section_label", "footer", "highlight"} | family_components.get(family, set())}


COMPOSITIONS = {
    "editorial_title_body_v1": _composition("editorial_v1", features={"takeaway", "quote"}, lifecycle="curated"),
    "editorial_centered_statement_v1": _composition("editorial_v1", features={"takeaway"}, lifecycle="curated"),
    "editorial_asymmetric_v1": _composition("editorial_v1", features={"quote"}),
    "dialogue_alternating_bubbles_v1": _composition("dialogue_v1", features={"dialogue", "target_expression"}, densities={"low", "medium"}, lifecycle="curated", fallback="dialogue_stacked_transcript_v1"),
    "dialogue_stacked_transcript_v1": _composition("dialogue_v1", features={"dialogue", "quote"}, lifecycle="curated", fallback="editorial_title_body_v1"),
    "dialogue_split_speakers_v1": _composition("dialogue_v1", features={"dialogue"}, densities={"low", "medium"}, fallback="dialogue_stacked_transcript_v1"),
    "comparison_two_column_v1": _composition("comparison_v1", features={"comparison", "difference"}, lifecycle="curated", fallback="comparison_stacked_contrast_v1"),
    "comparison_stacked_contrast_v1": _composition("comparison_v1", features={"comparison", "difference"}, lifecycle="curated", fallback="editorial_title_body_v1"),
    "comparison_before_after_v1": _composition("comparison_v1", features={"comparison"}, densities={"low", "medium"}),
    "cards_feature_stack_v1": _composition("cards_v1", features={"cards", "takeaway"}, lifecycle="curated"),
    "cards_grid_v1": _composition("cards_v1", features={"cards"}, densities={"low", "medium"}),
    "process_vertical_steps_v1": _composition("process_v1", features={"process", "steps"}, lifecycle="curated"),
    "process_numbered_sequence_v1": _composition("process_v1", features={"process", "steps"}, lifecycle="tested"),
    "scenario_response_v1": _composition("scenario_v1", features={"scenario", "quote"}, lifecycle="curated"),
    "scenario_problem_reaction_v1": _composition("scenario_v1", features={"scenario"}),
    "data_number_context_v1": _composition("data_v1", features={"data", "numbers"}, lifecycle="curated"),
    "data_metric_cards_v1": _composition("data_v1", features={"data", "numbers", "difference"}),
    "quote_centered_focus_v1": _composition("quote_v1", features={"quote", "takeaway"}, lifecycle="curated"),
}

COMPONENTS = {
    "speech_bubble": {"rounded_v1", "border_only_v1", "filled_v1"}, "speaker_label": {"initials_v1", "filled_v1"},
    "highlight": {"marker_v1", "underline_v1", "pill_v1", "accent_text_v1"}, "callout": {"filled_v1", "outlined_v1", "subtle_surface_v1"},
    "step_marker": {"numbered_v1", "minimal_v1"}, "number_marker": {"large_v1", "pill_v1"},
    "section_label": {"compact_v1"}, "footer": {"compact_brand_v1"},
}
DECORATIONS = {"subtle_dots_v1", "subtle_grid_v1", "corner_accent_v1", "none_v1"}
IMAGE_TREATMENTS = {"none_v1", "framed_image_v1", "split_image_text_v1"}

PRESETS = {
    "conversational_blue_01": {"family_id": "dialogue_v1", "composition_id": "dialogue_alternating_bubbles_v1", "theme_id": "soft_blue_v1", "typography_id": "friendly_sans_v1", "density": "medium", "components": {"speech_bubble": "rounded_v1", "speaker_label": "initials_v1", "highlight": "marker_v1", "footer": "compact_brand_v1"}, "decorations": ["subtle_dots_v1"], "image_treatment": "none_v1", "lifecycle": "curated"},
    "editorial_paper_01": {"family_id": "editorial_v1", "composition_id": "editorial_title_body_v1", "theme_id": "paper_v1", "typography_id": "editorial_serif_v1", "density": "medium", "components": {"highlight": "underline_v1", "footer": "compact_brand_v1"}, "decorations": ["corner_accent_v1"], "image_treatment": "none_v1", "lifecycle": "curated"},
    "analytic_cream_01": {"family_id": "comparison_v1", "composition_id": "comparison_two_column_v1", "theme_id": "warm_cream_v1", "typography_id": "compact_sans_v1", "density": "medium", "components": {"callout": "outlined_v1", "highlight": "accent_text_v1", "footer": "compact_brand_v1"}, "decorations": ["none_v1"], "image_treatment": "none_v1", "lifecycle": "curated"},
    "steps_green_01": {"family_id": "process_v1", "composition_id": "process_vertical_steps_v1", "theme_id": "soft_green_v1", "typography_id": "friendly_sans_v1", "density": "medium", "components": {"step_marker": "numbered_v1", "footer": "compact_brand_v1"}, "decorations": ["subtle_grid_v1"], "image_treatment": "none_v1", "lifecycle": "curated"},
}

DOMAIN_AFFINITY = {
    "english": {"dialogue_v1": 12, "cards_v1": 10, "comparison_v1": 6, "editorial_v1": 5},
    "ai_tools": {"process_v1": 10, "cards_v1": 8, "comparison_v1": 7, "editorial_v1": 5},
    "personal_finance": {"comparison_v1": 12, "data_v1": 10, "editorial_v1": 6},
    "business_side_hustle": {"scenario_v1": 10, "process_v1": 8, "comparison_v1": 7},
    "psychology_behavior": {"scenario_v1": 12, "dialogue_v1": 8, "comparison_v1": 7, "editorial_v1": 5},
}
PLATFORM_POLICY = {"instagram": {"minimum": 5, "maximum": 8, "families": set(FAMILIES)}, "x": {"minimum": 1, "maximum": 1, "families": {"editorial_v1", "comparison_v1", "data_v1", "quote_v1", "cards_v1"}}}
# Account/brand policy is source-controlled like the registry. New account
# policies constrain the shared pool; they never fork domain templates.
BRAND_POLICIES = {
    "default": {"themes": set(THEMES), "typography": set(TYPOGRAPHY),
                "decorations": set(DECORATIONS), "footer": "compact_brand_v1"},
}
ACCOUNT_BRAND_POLICY = {}


def brand_policy_for_account(account: str) -> tuple[str, dict[str, Any]]:
    policy_id = ACCOUNT_BRAND_POLICY.get(account, "default")
    return policy_id, BRAND_POLICIES[policy_id]


def registry_fingerprint() -> str:
    value = {"release": REGISTRY_RELEASE, "families": FAMILIES, "compositions": COMPOSITIONS,
             "themes": THEMES, "typography": TYPOGRAPHY, "presets": PRESETS,
             "brand_policies": BRAND_POLICIES, "account_brand_policy": ACCOUNT_BRAND_POLICY}
    return sha256(json.dumps(value, sort_keys=True, default=sorted, separators=(",", ":")).encode()).hexdigest()


def validate_intent(value: Any) -> dict[str, Any]:
    expected = {"schema_version", "primary_structure", "tone", "density", "emphasis_targets", "image_need"}
    if not isinstance(value, Mapping) or set(value) != expected or value["schema_version"] != "visual_intent_v1":
        raise ValueError("visual intent has an invalid closed shape")
    if value["primary_structure"] not in INTENT_STRUCTURES or value["tone"] not in INTENT_TONES or value["density"] not in INTENT_DENSITIES:
        raise ValueError("visual intent has unsupported semantic values")
    if value["image_need"] not in {"none", "optional", "required"} or not isinstance(value["emphasis_targets"], list):
        raise ValueError("visual intent image or emphasis values are invalid")
    if len(value["emphasis_targets"]) > 4 or any(item not in EMPHASIS_TARGETS for item in value["emphasis_targets"]):
        raise ValueError("visual intent emphasis target is unsupported")
    if len(set(value["emphasis_targets"])) != len(value["emphasis_targets"]):
        raise ValueError("visual intent emphasis targets must be unique")
    return dict(value)


def validate_recipe(value: Any, *, production: bool) -> dict[str, Any]:
    expected = {"schema_version", "registry_release", "registry_fingerprint", "source", "preset_id", "family_id", "composition_id", "theme_id", "typography_id", "density", "components", "decorations", "image_treatment", "unit_layouts"}
    if not isinstance(value, Mapping) or set(value) != expected or value["schema_version"] != "visual_recipe_v1":
        raise ValueError("visual recipe has an invalid closed shape")
    if value["registry_release"] != REGISTRY_RELEASE or value["registry_fingerprint"] != registry_fingerprint():
        raise ValueError("visual recipe registry release is unavailable")
    if value["source"] not in {"dynamic", "preset", "fallback"} or (value["source"] == "preset") != bool(value["preset_id"]):
        raise ValueError("visual recipe source is invalid")
    family, composition = value["family_id"], COMPOSITIONS.get(value["composition_id"])
    if family not in FAMILIES or composition is None or composition["family_id"] != family or composition["engine"] not in ENGINES:
        raise ValueError("visual family or composition is unsupported")
    ids = ((value["theme_id"], THEMES), (value["typography_id"], TYPOGRAPHY))
    if any(item not in collection for item, collection in ids) or value["density"] not in INTENT_DENSITIES:
        raise ValueError("visual recipe theme, typography, or density is unsupported")
    selected = [composition["lifecycle"], THEMES[value["theme_id"]]["lifecycle"], TYPOGRAPHY[value["typography_id"]]["lifecycle"]]
    if any(state == "deprecated" for state in selected) or (production and any(state != "curated" for state in selected)):
        raise ValueError("visual recipe is not eligible for this renderer mode")
    if value["density"] not in composition["densities"] or not isinstance(value["components"], Mapping):
        raise ValueError("visual recipe density or components are incompatible")
    for name, variant in value["components"].items():
        if name not in COMPONENTS or name not in composition["components"] or variant not in COMPONENTS[name]:
            raise ValueError("visual recipe component variant is unsupported")
    if not isinstance(value["decorations"], list) or any(item not in DECORATIONS for item in value["decorations"]):
        raise ValueError("visual recipe decoration is unsupported")
    if value["image_treatment"] not in IMAGE_TREATMENTS or not isinstance(value["unit_layouts"], list):
        raise ValueError("visual recipe image treatment or layouts are invalid")
    for item in value["unit_layouts"]:
        if not isinstance(item, Mapping) or set(item) != {"ordinal", "variant"} or type(item["ordinal"]) is not int or item["ordinal"] < 1 or not isinstance(item["variant"], str):
            raise ValueError("visual recipe unit layout is invalid")
    return dict(value)
