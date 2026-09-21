"""Version-controlled visual primitives, curated archetypes, and recipe validation.

Low-level primitives are authoring building blocks. Runtime production planning
selects a coherent archetype (or one of its exact presets), then resolves only
the variants that that archetype explicitly permits.
"""

from __future__ import annotations

from hashlib import sha256
from typing import Any, Mapping
import json


REGISTRY_RELEASE = "visual_registry_release_v2"
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
    family_components = {"dialogue_v1": {"speech_bubble", "speaker_label"}, "comparison_v1": {"callout"}, "process_v1": {"step_marker"}, "data_v1": {"number_marker"}}
    return {"family_id": family, "engine": "html_playwright_v1", "features": features, "densities": densities, "lifecycle": lifecycle, "platforms": platforms, "fallback": fallback, "components": {"section_label", "footer", "highlight"} | family_components.get(family, set())}


COMPOSITIONS = {
    "editorial_title_body_v1": _composition("editorial_v1", features={"takeaway", "quote"}, lifecycle="curated"), "editorial_centered_statement_v1": _composition("editorial_v1", features={"takeaway"}, lifecycle="curated"), "editorial_asymmetric_v1": _composition("editorial_v1", features={"quote"}),
    "dialogue_alternating_bubbles_v1": _composition("dialogue_v1", features={"dialogue", "target_expression"}, densities={"low", "medium"}, lifecycle="curated"), "dialogue_stacked_transcript_v1": _composition("dialogue_v1", features={"dialogue", "quote"}, lifecycle="curated"), "dialogue_split_speakers_v1": _composition("dialogue_v1", features={"dialogue"}, densities={"low", "medium"}),
    "comparison_two_column_v1": _composition("comparison_v1", features={"comparison", "difference"}, lifecycle="curated"), "comparison_stacked_contrast_v1": _composition("comparison_v1", features={"comparison", "difference"}, lifecycle="curated"), "comparison_before_after_v1": _composition("comparison_v1", features={"comparison"}, densities={"low", "medium"}),
    "cards_feature_stack_v1": _composition("cards_v1", features={"cards", "takeaway"}, lifecycle="curated"), "cards_grid_v1": _composition("cards_v1", features={"cards"}, densities={"low", "medium"}),
    "process_vertical_steps_v1": _composition("process_v1", features={"process", "steps"}, lifecycle="curated"), "process_numbered_sequence_v1": _composition("process_v1", features={"process", "steps"}),
    "scenario_response_v1": _composition("scenario_v1", features={"scenario", "quote"}, lifecycle="curated"), "scenario_problem_reaction_v1": _composition("scenario_v1", features={"scenario"}),
    "data_number_context_v1": _composition("data_v1", features={"data", "numbers"}, lifecycle="curated"), "data_metric_cards_v1": _composition("data_v1", features={"data", "numbers", "difference"}), "quote_centered_focus_v1": _composition("quote_v1", features={"quote", "takeaway"}, lifecycle="curated"),
}

COMPONENTS = {"speech_bubble": {"rounded_v1", "border_only_v1", "filled_v1"}, "speaker_label": {"initials_v1", "filled_v1"}, "highlight": {"marker_v1", "underline_v1", "pill_v1", "accent_text_v1"}, "callout": {"filled_v1", "outlined_v1", "subtle_surface_v1"}, "step_marker": {"numbered_v1", "minimal_v1"}, "number_marker": {"large_v1", "pill_v1"}, "section_label": {"compact_v1"}, "footer": {"compact_brand_v1"}}
COMPONENT_LIFECYCLES = {"speech_bubble": {"rounded_v1": "tested", "border_only_v1": "tested", "filled_v1": "tested"}, "speaker_label": {"initials_v1": "tested", "filled_v1": "tested"}, "highlight": {"marker_v1": "curated", "underline_v1": "curated", "pill_v1": "tested", "accent_text_v1": "curated"}, "callout": {"filled_v1": "curated", "outlined_v1": "curated", "subtle_surface_v1": "tested"}, "step_marker": {"numbered_v1": "tested", "minimal_v1": "tested"}, "number_marker": {"large_v1": "tested", "pill_v1": "tested"}, "section_label": {"compact_v1": "curated"}, "footer": {"compact_brand_v1": "curated"}}
DECORATIONS = {"subtle_dots_v1", "subtle_grid_v1", "corner_accent_v1", "none_v1"}
DECORATION_LIFECYCLES = {"subtle_dots_v1": "curated", "subtle_grid_v1": "tested", "corner_accent_v1": "tested", "none_v1": "curated"}
IMAGE_TREATMENTS = {"none_v1", "framed_image_v1", "split_image_text_v1"}
IMAGE_TREATMENT_LIFECYCLES = {"none_v1": "curated", "framed_image_v1": "experimental", "split_image_text_v1": "experimental"}


def _archetype(family: str, compositions: list[str], *, default_composition: str, themes: list[str], default_theme: str, typography: list[str], default_typography: str, densities: list[str], default_density: str, required_components: dict[str, str], optional_components: dict[str, list[str]], decorations: list[str], default_decorations: list[str], platforms: set[str], lifecycle: str, fallback: str | None, features: set[str]) -> dict[str, Any]:
    return {"family_id": family, "composition_ids": compositions, "default_composition_id": default_composition, "theme_ids": themes, "default_theme_id": default_theme, "typography_ids": typography, "default_typography_id": default_typography, "density_ids": densities, "default_density": default_density, "required_components": required_components, "optional_components": optional_components, "decoration_ids": decorations, "default_decorations": default_decorations, "image_treatment_ids": ["none_v1"], "default_image_treatment": "none_v1", "platforms": platforms, "semantic_features": features, "lifecycle": lifecycle, "fallback_archetype_id": fallback}


# Runtime selection units. Tested archetypes remain preview/authoring material
# until their distinct component grammar is visibly implemented by the renderer.
ARCHETYPES = {
    "editorial_clean_v1": _archetype("editorial_v1", ["editorial_title_body_v1", "editorial_centered_statement_v1"], default_composition="editorial_title_body_v1", themes=["minimal_white_v1", "dark_neutral_v1"], default_theme="minimal_white_v1", typography=["friendly_sans_v1", "bold_display_v1"], default_typography="friendly_sans_v1", densities=["low", "medium", "high"], default_density="medium", required_components={"footer": "compact_brand_v1"}, optional_components={"highlight": ["underline_v1", "accent_text_v1"]}, decorations=["none_v1", "subtle_dots_v1"], default_decorations=["none_v1"], platforms={"instagram", "x"}, lifecycle="curated", fallback="quote_focus_v1", features={"takeaway", "quote", "editorial"}),
    "dialogue_modern_v1": _archetype("dialogue_v1", ["dialogue_alternating_bubbles_v1", "dialogue_stacked_transcript_v1"], default_composition="dialogue_alternating_bubbles_v1", themes=["soft_blue_v1", "minimal_white_v1", "dark_neutral_v1"], default_theme="soft_blue_v1", typography=["friendly_sans_v1", "compact_sans_v1"], default_typography="friendly_sans_v1", densities=["low", "medium"], default_density="medium", required_components={"speech_bubble": "rounded_v1", "speaker_label": "initials_v1", "footer": "compact_brand_v1"}, optional_components={"highlight": ["marker_v1", "underline_v1"]}, decorations=["none_v1", "subtle_dots_v1"], default_decorations=["subtle_dots_v1"], platforms={"instagram"}, lifecycle="tested", fallback="editorial_clean_v1", features={"dialogue", "target_expression", "quote"}),
    "comparison_clean_v1": _archetype("comparison_v1", ["comparison_two_column_v1", "comparison_stacked_contrast_v1"], default_composition="comparison_two_column_v1", themes=["warm_cream_v1", "minimal_white_v1", "dark_neutral_v1"], default_theme="warm_cream_v1", typography=["compact_sans_v1", "bold_display_v1"], default_typography="compact_sans_v1", densities=["low", "medium", "high"], default_density="medium", required_components={"callout": "outlined_v1", "footer": "compact_brand_v1"}, optional_components={"highlight": ["accent_text_v1", "underline_v1"]}, decorations=["none_v1"], default_decorations=["none_v1"], platforms={"instagram", "x"}, lifecycle="curated", fallback="editorial_clean_v1", features={"comparison", "difference", "numbers"}),
    "cards_modular_v1": _archetype("cards_v1", ["cards_feature_stack_v1", "cards_grid_v1"], default_composition="cards_feature_stack_v1", themes=["minimal_white_v1", "soft_lilac_v1"], default_theme="minimal_white_v1", typography=["friendly_sans_v1", "compact_sans_v1"], default_typography="friendly_sans_v1", densities=["low", "medium"], default_density="medium", required_components={"footer": "compact_brand_v1"}, optional_components={"highlight": ["marker_v1", "pill_v1"]}, decorations=["none_v1", "subtle_dots_v1"], default_decorations=["none_v1"], platforms={"instagram", "x"}, lifecycle="tested", fallback="editorial_clean_v1", features={"cards", "takeaway"}),
    "process_steps_v1": _archetype("process_v1", ["process_vertical_steps_v1", "process_numbered_sequence_v1"], default_composition="process_vertical_steps_v1", themes=["minimal_white_v1", "soft_green_v1"], default_theme="minimal_white_v1", typography=["friendly_sans_v1", "compact_sans_v1"], default_typography="friendly_sans_v1", densities=["low", "medium", "high"], default_density="medium", required_components={"step_marker": "numbered_v1", "footer": "compact_brand_v1"}, optional_components={}, decorations=["none_v1", "subtle_grid_v1"], default_decorations=["none_v1"], platforms={"instagram"}, lifecycle="tested", fallback="editorial_clean_v1", features={"process", "steps"}),
    "scenario_soft_v1": _archetype("scenario_v1", ["scenario_response_v1", "scenario_problem_reaction_v1"], default_composition="scenario_response_v1", themes=["minimal_white_v1", "soft_lilac_v1"], default_theme="minimal_white_v1", typography=["friendly_sans_v1"], default_typography="friendly_sans_v1", densities=["low", "medium", "high"], default_density="medium", required_components={"footer": "compact_brand_v1"}, optional_components={"highlight": ["marker_v1", "pill_v1"]}, decorations=["none_v1"], default_decorations=["none_v1"], platforms={"instagram"}, lifecycle="tested", fallback="editorial_clean_v1", features={"scenario", "quote"}),
    "data_number_v1": _archetype("data_v1", ["data_number_context_v1", "data_metric_cards_v1"], default_composition="data_number_context_v1", themes=["minimal_white_v1", "dark_neutral_v1"], default_theme="minimal_white_v1", typography=["bold_display_v1", "compact_sans_v1"], default_typography="bold_display_v1", densities=["low", "medium", "high"], default_density="medium", required_components={"number_marker": "large_v1", "footer": "compact_brand_v1"}, optional_components={"highlight": ["accent_text_v1"]}, decorations=["none_v1"], default_decorations=["none_v1"], platforms={"instagram", "x"}, lifecycle="tested", fallback="comparison_clean_v1", features={"data", "numbers", "difference"}),
    "quote_focus_v1": _archetype("quote_v1", ["quote_centered_focus_v1"], default_composition="quote_centered_focus_v1", themes=["minimal_white_v1", "dark_neutral_v1"], default_theme="minimal_white_v1", typography=["bold_display_v1", "friendly_sans_v1"], default_typography="bold_display_v1", densities=["low", "medium", "high"], default_density="medium", required_components={"footer": "compact_brand_v1"}, optional_components={"highlight": ["underline_v1", "accent_text_v1"]}, decorations=["none_v1", "subtle_dots_v1"], default_decorations=["none_v1"], platforms={"instagram", "x"}, lifecycle="curated", fallback="editorial_clean_v1", features={"quote", "takeaway"}),
}

PRESETS = {
    "editorial_clean_01": {"archetype_id": "editorial_clean_v1", "family_id": "editorial_v1", "composition_id": "editorial_title_body_v1", "theme_id": "minimal_white_v1", "typography_id": "friendly_sans_v1", "density": "medium", "components": {"highlight": "underline_v1", "footer": "compact_brand_v1"}, "decorations": ["none_v1"], "image_treatment": "none_v1", "lifecycle": "curated"},
    "comparison_clean_01": {"archetype_id": "comparison_clean_v1", "family_id": "comparison_v1", "composition_id": "comparison_two_column_v1", "theme_id": "warm_cream_v1", "typography_id": "compact_sans_v1", "density": "medium", "components": {"callout": "outlined_v1", "highlight": "accent_text_v1", "footer": "compact_brand_v1"}, "decorations": ["none_v1"], "image_treatment": "none_v1", "lifecycle": "curated"},
    "quote_focus_01": {"archetype_id": "quote_focus_v1", "family_id": "quote_v1", "composition_id": "quote_centered_focus_v1", "theme_id": "minimal_white_v1", "typography_id": "bold_display_v1", "density": "medium", "components": {"highlight": "underline_v1", "footer": "compact_brand_v1"}, "decorations": ["none_v1"], "image_treatment": "none_v1", "lifecycle": "curated"},
}

DOMAIN_AFFINITY = {"english": {"dialogue_v1": 12, "cards_v1": 10, "comparison_v1": 6, "editorial_v1": 5}, "ai_tools": {"process_v1": 10, "cards_v1": 8, "comparison_v1": 7, "editorial_v1": 5}, "personal_finance": {"comparison_v1": 12, "data_v1": 10, "editorial_v1": 6}, "business_side_hustle": {"scenario_v1": 10, "process_v1": 8, "comparison_v1": 7}, "psychology_behavior": {"scenario_v1": 12, "dialogue_v1": 8, "comparison_v1": 7, "editorial_v1": 5}}
PLATFORM_POLICY = {"instagram": {"minimum": 5, "maximum": 8, "families": set(FAMILIES)}, "x": {"minimum": 1, "maximum": 1, "families": {"editorial_v1", "comparison_v1", "data_v1", "quote_v1", "cards_v1"}}}
BRAND_POLICIES = {"default": {"themes": set(THEMES), "typography": set(TYPOGRAPHY), "decorations": set(DECORATIONS), "footer": "compact_brand_v1"}}
ACCOUNT_BRAND_POLICY = {}


def brand_policy_for_account(account: str) -> tuple[str, dict[str, Any]]:
    policy_id = ACCOUNT_BRAND_POLICY.get(account, "default")
    return policy_id, BRAND_POLICIES[policy_id]


def registry_fingerprint() -> str:
    value = {"release": REGISTRY_RELEASE, "families": FAMILIES, "compositions": COMPOSITIONS, "themes": THEMES, "typography": TYPOGRAPHY, "components": COMPONENT_LIFECYCLES, "decorations": DECORATION_LIFECYCLES, "image_treatments": IMAGE_TREATMENT_LIFECYCLES, "archetypes": ARCHETYPES, "presets": PRESETS, "brand_policies": BRAND_POLICIES, "account_brand_policy": ACCOUNT_BRAND_POLICY}
    return sha256(json.dumps(value, sort_keys=True, default=sorted, separators=(",", ":")).encode()).hexdigest()


def validate_intent(value: Any) -> dict[str, Any]:
    expected = {"schema_version", "primary_structure", "tone", "density", "emphasis_targets", "image_need"}
    if not isinstance(value, Mapping) or set(value) != expected or value["schema_version"] != "visual_intent_v1": raise ValueError("visual intent has an invalid closed shape")
    if value["primary_structure"] not in INTENT_STRUCTURES or value["tone"] not in INTENT_TONES or value["density"] not in INTENT_DENSITIES: raise ValueError("visual intent has unsupported semantic values")
    if value["image_need"] not in {"none", "optional", "required"} or not isinstance(value["emphasis_targets"], list): raise ValueError("visual intent image or emphasis values are invalid")
    if len(value["emphasis_targets"]) > 4 or any(item not in EMPHASIS_TARGETS for item in value["emphasis_targets"]): raise ValueError("visual intent emphasis target is unsupported")
    if len(set(value["emphasis_targets"])) != len(value["emphasis_targets"]): raise ValueError("visual intent emphasis targets must be unique")
    return dict(value)


def _validate_archetype_resolution(value: Mapping[str, Any], archetype: Mapping[str, Any]) -> None:
    composition_id, family = value["composition_id"], value["family_id"]
    composition = COMPOSITIONS.get(composition_id)
    if family != archetype["family_id"] or composition is None or composition["family_id"] != family or composition_id not in archetype["composition_ids"] or composition["engine"] not in ENGINES: raise ValueError("visual recipe composition is outside its archetype")
    if value["theme_id"] not in archetype["theme_ids"] or value["typography_id"] not in archetype["typography_ids"] or value["density"] not in archetype["density_ids"] or value["density"] not in composition["densities"]: raise ValueError("visual recipe token is outside its archetype")
    if not isinstance(value["components"], Mapping): raise ValueError("visual recipe components are invalid")
    permitted = set(archetype["required_components"]) | set(archetype["optional_components"])
    if not set(value["components"]).issubset(permitted): raise ValueError("visual recipe component is outside its archetype")
    for name, variant in archetype["required_components"].items():
        if value["components"].get(name) != variant: raise ValueError("visual recipe misses an archetype-required component")
    for name, variant in value["components"].items():
        allowed = [archetype["required_components"][name]] if name in archetype["required_components"] else archetype["optional_components"][name]
        if name not in COMPONENTS or name not in composition["components"] or variant not in allowed: raise ValueError("visual recipe component variant is outside its archetype")
    if not isinstance(value["decorations"], list) or len(set(value["decorations"])) != len(value["decorations"]) or any(item not in archetype["decoration_ids"] for item in value["decorations"]): raise ValueError("visual recipe decoration is outside its archetype")
    if value["image_treatment"] not in archetype["image_treatment_ids"]: raise ValueError("visual recipe image treatment is outside its archetype")


def is_production_eligible(value: Mapping[str, Any]) -> bool:
    archetype, composition = ARCHETYPES.get(value.get("archetype_id")), COMPOSITIONS.get(value.get("composition_id"))
    if archetype is None or composition is None or archetype["lifecycle"] != "curated" or composition["lifecycle"] != "curated": return False
    if THEMES[value["theme_id"]]["lifecycle"] != "curated" or TYPOGRAPHY[value["typography_id"]]["lifecycle"] != "curated": return False
    return all(COMPONENT_LIFECYCLES[name][variant] == "curated" for name, variant in value["components"].items()) and all(DECORATION_LIFECYCLES[item] == "curated" for item in value["decorations"]) and IMAGE_TREATMENT_LIFECYCLES[value["image_treatment"]] == "curated"


def validate_recipe(value: Any, *, production: bool) -> dict[str, Any]:
    expected = {"schema_version", "registry_release", "registry_fingerprint", "source", "archetype_id", "preset_id", "family_id", "composition_id", "theme_id", "typography_id", "density", "components", "decorations", "image_treatment", "unit_layouts"}
    if not isinstance(value, Mapping) or set(value) != expected or value["schema_version"] != "visual_recipe_v2": raise ValueError("visual recipe has an invalid closed shape")
    if value["registry_release"] != REGISTRY_RELEASE or value["registry_fingerprint"] != registry_fingerprint(): raise ValueError("visual recipe registry release is unavailable")
    archetype = ARCHETYPES.get(value["archetype_id"])
    if archetype is None: raise ValueError("visual recipe archetype is unavailable")
    source, preset_id = value["source"], value["preset_id"]
    if source not in {"curated_preset", "curated_archetype", "experimental_dynamic", "fallback"} or (source == "curated_preset") != bool(preset_id): raise ValueError("visual recipe source is invalid")
    if preset_id:
        preset = PRESETS.get(preset_id); resolved = {key: value[key] for key in ("archetype_id", "family_id", "composition_id", "theme_id", "typography_id", "density", "components", "decorations", "image_treatment")}
        if preset is None or {key: preset[key] for key in resolved} != resolved: raise ValueError("visual recipe does not exactly match its preset")
    _validate_archetype_resolution(value, archetype)
    if source == "curated_preset" and PRESETS[preset_id]["lifecycle"] != "curated": raise ValueError("visual recipe preset is not curated")
    if source == "curated_archetype" and archetype["lifecycle"] != "curated": raise ValueError("visual recipe archetype is not curated")
    if production and (source == "experimental_dynamic" or not is_production_eligible(value)): raise ValueError("visual recipe is not eligible for this renderer mode")
    if not isinstance(value["unit_layouts"], list): raise ValueError("visual recipe layouts are invalid")
    for item in value["unit_layouts"]:
        if not isinstance(item, Mapping) or set(item) != {"ordinal", "variant"} or type(item["ordinal"]) is not int or item["ordinal"] < 1 or not isinstance(item["variant"], str): raise ValueError("visual recipe unit layout is invalid")
    return dict(value)
