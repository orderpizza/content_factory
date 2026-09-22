"""Source-controlled visual primitives, coherent archetypes, and closed recipes."""
from __future__ import annotations

from hashlib import sha256
from typing import Any, Mapping
import json

from .visual_explainers import EXPLAINER_ROLES


REGISTRY_RELEASE = "visual_registry_release_v5"
ENGINES = {"html_playwright_v1"}
LIFECYCLES = {"experimental", "tested", "curated", "deprecated"}
INTENT_STRUCTURES = {"editorial", "dialogue", "comparison", "cards", "process", "scenario", "data", "quote"}
INTENT_TONES = {"friendly", "analytical", "professional", "playful", "serious", "minimal"}
INTENT_DENSITIES = {"low", "medium", "high"}
EMPHASIS_TARGETS = {"target_expression", "numbers", "difference", "steps", "quote", "takeaway"}
UNIT_ROLES = {"hook", "explanation", "example", "takeaway"}

THEMES = {
    "minimal_white_v1": {"lifecycle": "curated", "background": "#f8f9fb", "surface": "#ffffff", "text": "#18212b", "muted": "#62707b", "accent": "#3f7fae"},
    "warm_cream_v1": {"lifecycle": "curated", "background": "#f3eee3", "surface": "#fffdf8", "text": "#222a33", "muted": "#64635d", "accent": "#c65b41"},
    "soft_blue_v1": {"lifecycle": "curated", "background": "#dfeefa", "surface": "#fafdff", "text": "#142d43", "muted": "#547086", "accent": "#1976b9"},
    "soft_green_v1": {"lifecycle": "curated", "background": "#e7f2eb", "surface": "#fbfffc", "text": "#18372a", "muted": "#587065", "accent": "#34835d"},
    "soft_lilac_v1": {"lifecycle": "curated", "background": "#eee8f7", "surface": "#fcfaff", "text": "#2b243b", "muted": "#675e75", "accent": "#7655ad"},
    "dark_neutral_v1": {"lifecycle": "curated", "background": "#172028", "surface": "#27343d", "text": "#f7f8f5", "muted": "#c4cbd0", "accent": "#8fc7ed"},
    "paper_v1": {"lifecycle": "curated", "background": "#eee8dc", "surface": "#faf6ee", "text": "#302b24", "muted": "#6c6252", "accent": "#8e6840"},
    "blue_learning_v1": {"lifecycle": "curated", "background": "#dceeff", "surface": "#f8fcff", "surface_secondary": "#c8e4fb", "text": "#132d47", "muted": "#55738e", "accent": "#1c76c9", "accent_secondary": "#6baee6", "highlight": "#ffe584"},
    "cream_editorial_v1": {"lifecycle": "curated", "background": "#f5ede0", "surface": "#fffaf2", "surface_secondary": "#eadcc6", "text": "#2a2a29", "muted": "#70675d", "accent": "#c35e45", "accent_secondary": "#e0a083", "highlight": "#f6d770"},
    "green_friendly_v1": {"lifecycle": "curated", "background": "#e4f5e9", "surface": "#fbfffc", "surface_secondary": "#d0ead8", "text": "#18392a", "muted": "#557263", "accent": "#398c65", "accent_secondary": "#8bc49e", "highlight": "#f6dc73"},
    "blush_examples_v1": {"lifecycle": "curated", "background": "#fff0f0", "surface": "#fffafa", "surface_secondary": "#f9d8dc", "text": "#202b44", "muted": "#5d6577", "accent": "#e48691", "accent_secondary": "#eeb3bc", "highlight": "#a9d8f6"},
    "lavender_conversation_v1": {"lifecycle": "curated", "background": "#eee8fb", "surface": "#fcfaff", "surface_secondary": "#ddd0f3", "text": "#30254a", "muted": "#6a5e83", "accent": "#785ac0", "accent_secondary": "#ae93dd", "highlight": "#f8d97b"},
    "warm_takeaway_v1": {"lifecycle": "curated", "background": "#fff0dd", "surface": "#fffaf2", "surface_secondary": "#f9ddbb", "text": "#3d2a18", "muted": "#7b6045", "accent": "#cc7537", "accent_secondary": "#e8ad72", "highlight": "#f4d86e"},
}
TYPOGRAPHY = {
    "friendly_sans_v1": {"lifecycle": "curated", "family": "Arial, Helvetica, sans-serif", "title_scale": 1.0, "tracking": "-.035em"},
    "editorial_serif_v1": {"lifecycle": "curated", "family": "Georgia, Times, serif", "title_scale": .96, "tracking": "-.03em"},
    "bold_display_v1": {"lifecycle": "curated", "family": "Arial Black, Arial, sans-serif", "title_scale": 1.07, "tracking": "-.065em"},
    "compact_sans_v1": {"lifecycle": "curated", "family": "Arial, Helvetica, sans-serif", "title_scale": .9, "tracking": "-.025em"},
}
FAMILIES = {
    "editorial_v1": {"features": {"editorial", "takeaway", "quote"}}, "dialogue_v1": {"features": {"dialogue", "target_expression", "quote"}},
    "comparison_v1": {"features": {"comparison", "difference", "numbers"}}, "cards_v1": {"features": {"cards", "takeaway", "target_expression"}},
    "process_v1": {"features": {"process", "steps"}}, "scenario_v1": {"features": {"scenario", "quote"}},
    "data_v1": {"features": {"data", "numbers", "difference"}}, "quote_v1": {"features": {"quote", "takeaway"}},
}


def _composition(family: str, features: set[str], *, platforms: set[str] = {"instagram"}, densities: set[str] = {"low", "medium", "high"}) -> dict[str, Any]:
    components = {"section_label", "footer", "highlight", "divider"}
    components |= {"definition_card", "pronunciation_row", "progress_cue", "phrase_group", "question_list", "icon_badge", "checklist_row", "example_card", "avatar", "note_panel", "summary_card"} if family == "cards_v1" else set()
    components |= {"definition_card"} if family == "editorial_v1" else set()
    components |= {"speech_bubble", "speaker_label"} if family == "dialogue_v1" else set()
    components |= {"comparison_column", "callout"} if family == "comparison_v1" else set()
    components |= {"step_marker"} if family == "process_v1" else set()
    components |= {"scenario_panel"} if family == "scenario_v1" else set()
    return {"family_id": family, "engine": "html_playwright_v1", "features": features, "platforms": platforms, "densities": densities, "lifecycle": "curated", "components": components}


COMPOSITIONS = {
    "vocab_card_layout_v1": _composition("cards_v1", {"cards", "target_expression"}),
    "expression_breakdown_layout_v1": _composition("cards_v1", {"cards", "target_expression", "takeaway"}, platforms={"instagram"}),
    "editorial_bold_cover_layout_v1": _composition("editorial_v1", {"editorial", "takeaway"}),
    "comparison_cover_layout_v1": _composition("comparison_v1", {"comparison", "difference"}),
    "phrase_sheet_layout_v1": _composition("cards_v1", {"cards", "takeaway"}, platforms={"instagram"}),
    "question_pattern_layout_v1": _composition("cards_v1", {"cards", "target_expression"}, platforms={"instagram"}),
    "vocab_serif_layout_v1": _composition("editorial_v1", {"editorial", "quote"}),
    "dialogue_alternating_bubbles_v1": _composition("dialogue_v1", {"dialogue", "target_expression"}, platforms={"instagram"}, densities={"low", "medium"}),
    "dialogue_stacked_transcript_v1": _composition("dialogue_v1", {"dialogue", "quote"}, platforms={"instagram"}),
    "scenario_explainer_layout_v1": _composition("scenario_v1", {"scenario", "quote"}, platforms={"instagram"}),
    "process_steps_layout_v1": _composition("process_v1", {"process", "steps"}, platforms={"instagram"}),
    "editorial_title_body_v1": _composition("editorial_v1", {"editorial", "takeaway", "quote"}),
    "quote_centered_focus_v1": _composition("quote_v1", {"quote", "takeaway"}),
}

COMPONENTS = {
    "definition_card": {"rounded_v1"}, "pronunciation_row": {"compact_v1"}, "progress_cue": {"dots_v1"},
    "icon_badge": {"round_v1"}, "checklist_row": {"checked_v1"}, "example_card": {"stacked_v1"}, "avatar": {"halo_v1"}, "note_panel": {"pinned_v1"}, "summary_card": {"recall_v1"},
    "phrase_group": {"ruled_v1"}, "question_list": {"keyword_v1"}, "speech_bubble": {"rounded_v1", "border_only_v1"},
    "speaker_label": {"initials_v1", "filled_v1"}, "comparison_column": {"split_v1"}, "callout": {"outlined_v1"},
    "step_marker": {"numbered_v1", "minimal_v1"}, "scenario_panel": {"stacked_v1"}, "highlight": {"marker_v1", "underline_v1", "accent_text_v1"},
    "section_label": {"compact_v1"}, "divider": {"thin_v1"}, "footer": {"compact_brand_v1"},
}
COMPONENT_LIFECYCLES = {name: {variant: "curated" for variant in variants} for name, variants in COMPONENTS.items()}
DECORATIONS = {"subtle_dots_v1", "subtle_grid_v1", "corner_accent_v1", "none_v1", "paper_grain_v1", "soft_wave_v1"}
DECORATION_LIFECYCLES = {item: "curated" for item in DECORATIONS}
IMAGE_TREATMENTS = {"none_v1", "framed_image_v1", "split_image_text_v1"}
IMAGE_TREATMENT_LIFECYCLES = {"none_v1": "curated", "framed_image_v1": "experimental", "split_image_text_v1": "experimental"}


def _archetype(family: str, composition: str, *, themes: list[str], typography: list[str], components: dict[str, str], optional: dict[str, list[str]], layouts: dict[str, list[str]], platforms: set[str], features: set[str], fallback: str | None, lifecycle: str = "curated", expected_roles: list[str] | None = None, expected_layouts: list[str] | None = None, palette_sequence: list[str] | None = None) -> dict[str, Any]:
    value = {"family_id": family, "composition_ids": [composition], "default_composition_id": composition,
            "theme_ids": themes, "default_theme_id": themes[0], "typography_ids": typography,
            "default_typography_id": typography[0], "density_ids": ["low", "medium", "high"], "default_density": "medium",
            "required_components": components, "optional_components": optional, "decoration_ids": ["none_v1", "subtle_dots_v1", "paper_grain_v1", "soft_wave_v1"],
            "default_decorations": ["none_v1"], "image_treatment_ids": ["none_v1"], "default_image_treatment": "none_v1",
            "platforms": platforms, "semantic_features": features, "lifecycle": lifecycle, "fallback_archetype_id": fallback,
            "unit_layout_variants": layouts}
    if expected_roles is not None:
        value["expected_roles"] = expected_roles
    if expected_layouts is not None:
        value["expected_layouts"] = expected_layouts
    if palette_sequence is not None:
        value["palette_sequence"] = palette_sequence
    return value


# Preserved HTML capabilities plus explicit Gemini-only semantic archetypes.
ARCHETYPES = {
    "expression_breakdown_v1": _archetype("cards_v1", "expression_breakdown_layout_v1", themes=["blue_learning_v1", "cream_editorial_v1", "green_friendly_v1", "blush_examples_v1", "lavender_conversation_v1", "warm_takeaway_v1"], typography=["friendly_sans_v1", "compact_sans_v1"], components={"icon_badge": "round_v1", "checklist_row": "checked_v1", "example_card": "stacked_v1", "avatar": "halo_v1", "note_panel": "pinned_v1", "summary_card": "recall_v1", "footer": "compact_brand_v1"}, optional={"highlight": ["marker_v1", "underline_v1"]}, layouts={"hook": ["hook_hero"], "explanation": ["meaning_definition", "use_case_checklist"], "example": ["example_cards", "dialogue_bubbles"], "takeaway": ["takeaway_summary"]}, platforms={"instagram"}, features={"cards", "target_expression", "takeaway"}, fallback="vocab_card_minimal_v1", lifecycle="tested", expected_roles=["hook", "explanation", "explanation", "example", "example", "takeaway"], expected_layouts=["hook_hero", "meaning_definition", "use_case_checklist", "example_cards", "dialogue_bubbles", "takeaway_summary"], palette_sequence=["blue_learning_v1", "cream_editorial_v1", "green_friendly_v1", "blush_examples_v1", "lavender_conversation_v1", "warm_takeaway_v1"]),
    "vocab_card_minimal_v1": _archetype("cards_v1", "vocab_card_layout_v1", themes=["soft_blue_v1", "minimal_white_v1", "soft_green_v1"], typography=["friendly_sans_v1", "compact_sans_v1"], components={"definition_card": "rounded_v1", "pronunciation_row": "compact_v1", "footer": "compact_brand_v1"}, optional={"progress_cue": ["dots_v1"], "highlight": ["marker_v1"]}, layouts={"hook": ["vocab_hero"], "explanation": ["definition_card"], "example": ["example_card"], "takeaway": ["recall_card"]}, platforms={"instagram"}, features={"cards", "target_expression", "takeaway"}, fallback="editorial_bold_cover_v1"),
    "editorial_bold_cover_v1": _archetype("editorial_v1", "editorial_bold_cover_layout_v1", themes=["minimal_white_v1", "dark_neutral_v1", "warm_cream_v1"], typography=["bold_display_v1"], components={"section_label": "compact_v1", "footer": "compact_brand_v1"}, optional={"highlight": ["marker_v1", "accent_text_v1"]}, layouts={"hook": ["bold_hook"], "explanation": ["cover_detail"], "example": ["cover_detail"], "takeaway": ["cover_takeaway"]}, platforms={"instagram"}, features={"editorial", "takeaway", "numbers"}, fallback="vocab_card_minimal_v1"),
    "comparison_cover_bold_v1": _archetype("comparison_v1", "comparison_cover_layout_v1", themes=["warm_cream_v1", "dark_neutral_v1", "minimal_white_v1"], typography=["bold_display_v1", "compact_sans_v1"], components={"comparison_column": "split_v1", "callout": "outlined_v1", "footer": "compact_brand_v1"}, optional={"highlight": ["accent_text_v1"]}, layouts={"hook": ["comparison_cover"], "explanation": ["comparison_detail"], "example": ["comparison_examples"], "takeaway": ["comparison_takeaway"]}, platforms={"instagram"}, features={"comparison", "difference", "numbers"}, fallback="editorial_bold_cover_v1"),
    "phrase_sheet_v1": _archetype("cards_v1", "phrase_sheet_layout_v1", themes=["minimal_white_v1", "soft_green_v1"], typography=["friendly_sans_v1", "compact_sans_v1"], components={"phrase_group": "ruled_v1", "divider": "thin_v1", "footer": "compact_brand_v1"}, optional={"section_label": ["compact_v1"]}, layouts={"hook": ["sheet_title"], "explanation": ["phrase_groups"], "example": ["phrase_groups"], "takeaway": ["sheet_recall"]}, platforms={"instagram"}, features={"cards", "takeaway"}, fallback="vocab_card_minimal_v1"),
    "question_pattern_sheet_v1": _archetype("cards_v1", "question_pattern_layout_v1", themes=["minimal_white_v1", "soft_lilac_v1"], typography=["friendly_sans_v1", "compact_sans_v1"], components={"question_list": "keyword_v1", "divider": "thin_v1", "footer": "compact_brand_v1"}, optional={"highlight": ["underline_v1"]}, layouts={"hook": ["question_hero"], "explanation": ["question_pattern"], "example": ["question_examples"], "takeaway": ["question_recall"]}, platforms={"instagram"}, features={"cards", "target_expression"}, fallback="vocab_card_minimal_v1"),
    "vocab_serif_elegant_v1": _archetype("editorial_v1", "vocab_serif_layout_v1", themes=["paper_v1", "dark_neutral_v1", "minimal_white_v1"], typography=["editorial_serif_v1"], components={"definition_card": "rounded_v1", "divider": "thin_v1", "footer": "compact_brand_v1"}, optional={"highlight": ["underline_v1"]}, layouts={"hook": ["serif_word"], "explanation": ["serif_definition"], "example": ["serif_example"], "takeaway": ["serif_takeaway"]}, platforms={"instagram"}, features={"editorial", "quote", "target_expression"}, fallback="editorial_bold_cover_v1"),
    "dialogue_modern_v1": _archetype("dialogue_v1", "dialogue_alternating_bubbles_v1", themes=["soft_blue_v1", "minimal_white_v1", "dark_neutral_v1"], typography=["friendly_sans_v1", "compact_sans_v1"], components={"speech_bubble": "rounded_v1", "speaker_label": "initials_v1", "footer": "compact_brand_v1"}, optional={"highlight": ["marker_v1", "underline_v1"]}, layouts={"hook": ["dialogue_hero"], "explanation": ["dialogue_explanation"], "example": ["dialogue_exchange"], "takeaway": ["dialogue_takeaway"]}, platforms={"instagram"}, features={"dialogue", "target_expression", "quote"}, fallback="vocab_card_minimal_v1"),
    "scenario_explainer_v1": _archetype("scenario_v1", "scenario_explainer_layout_v1", themes=["soft_lilac_v1", "warm_cream_v1", "minimal_white_v1"], typography=["friendly_sans_v1", "compact_sans_v1"], components={"scenario_panel": "stacked_v1", "footer": "compact_brand_v1"}, optional={"highlight": ["marker_v1"]}, layouts={"hook": ["scenario_hook"], "explanation": ["scenario_analysis"], "example": ["scenario_response"], "takeaway": ["scenario_takeaway"]}, platforms={"instagram"}, features={"scenario", "quote", "takeaway"}, fallback="editorial_bold_cover_v1"),
    "process_steps_v1": _archetype("process_v1", "process_steps_layout_v1", themes=["soft_green_v1", "minimal_white_v1", "dark_neutral_v1"], typography=["friendly_sans_v1", "compact_sans_v1"], components={"step_marker": "numbered_v1", "footer": "compact_brand_v1"}, optional={"divider": ["thin_v1"]}, layouts={"hook": ["process_hook"], "explanation": ["numbered_steps"], "example": ["step_cards"], "takeaway": ["process_recall"]}, platforms={"instagram"}, features={"process", "steps", "takeaway"}, fallback="editorial_bold_cover_v1"),
    "editorial_clean_v1": _archetype("editorial_v1", "editorial_title_body_v1", themes=["minimal_white_v1", "dark_neutral_v1"], typography=["friendly_sans_v1"], components={"footer": "compact_brand_v1"}, optional={"highlight": ["underline_v1"]}, layouts={"hook": ["default_v1"], "explanation": ["default_v1"], "example": ["default_v1"], "takeaway": ["default_v1"]}, platforms={"instagram"}, features={"editorial", "takeaway"}, fallback="vocab_card_minimal_v1"),
    "category_badge_minimal_v1": _archetype("cards_v1", "vocab_card_layout_v1", themes=["minimal_white_v1"], typography=["friendly_sans_v1"], components={"definition_card": "rounded_v1", "footer": "compact_brand_v1"}, optional={}, layouts={"hook": ["default_v1"], "explanation": ["default_v1"], "example": ["default_v1"], "takeaway": ["default_v1"]}, platforms={"instagram"}, features={"cards"}, fallback="vocab_card_minimal_v1", lifecycle="experimental"),
}
# Reuse the smallest valid recipe envelope; these are semantic contracts, not HTML layouts.
for _domain, _theme in (("ai_tech", "minimal_white_v1"), ("psychology", "warm_cream_v1")):
    ARCHETYPES[f"{_domain}_explainer_v1"] = {
        **_archetype(
            "editorial_v1", "editorial_title_body_v1", themes=[_theme],
            typography=["friendly_sans_v1"], components={}, optional={},
            layouts={role: ["default_v1"] for role in set(EXPLAINER_ROLES)},
            platforms={"instagram"}, features={"editorial", "takeaway"}, fallback=None,
            expected_roles=list(EXPLAINER_ROLES),
        ),
        "gemini_domain": _domain,
    }

PRESETS = {
    "vocab_card_blue_01": {"archetype_id": "vocab_card_minimal_v1", "family_id": "cards_v1", "composition_id": "vocab_card_layout_v1", "theme_id": "soft_blue_v1", "typography_id": "friendly_sans_v1", "density": "medium", "components": {"definition_card": "rounded_v1", "pronunciation_row": "compact_v1", "footer": "compact_brand_v1"}, "decorations": ["none_v1"], "image_treatment": "none_v1", "lifecycle": "curated"},
    "editorial_bold_01": {"archetype_id": "editorial_bold_cover_v1", "family_id": "editorial_v1", "composition_id": "editorial_bold_cover_layout_v1", "theme_id": "minimal_white_v1", "typography_id": "bold_display_v1", "density": "medium", "components": {"section_label": "compact_v1", "footer": "compact_brand_v1"}, "decorations": ["none_v1"], "image_treatment": "none_v1", "lifecycle": "curated"},
    "comparison_bold_01": {"archetype_id": "comparison_cover_bold_v1", "family_id": "comparison_v1", "composition_id": "comparison_cover_layout_v1", "theme_id": "warm_cream_v1", "typography_id": "bold_display_v1", "density": "medium", "components": {"comparison_column": "split_v1", "callout": "outlined_v1", "footer": "compact_brand_v1"}, "decorations": ["none_v1"], "image_treatment": "none_v1", "lifecycle": "curated"},
}
DOMAIN_AFFINITY = {"english": {"cards_v1": 10, "dialogue_v1": 9, "comparison_v1": 8, "editorial_v1": 7, "process_v1": 6, "scenario_v1": 5}, "ai_tech": {"process_v1": 10, "cards_v1": 9, "comparison_v1": 8}, "psychology": {"scenario_v1": 12, "dialogue_v1": 8, "cards_v1": 7}}
PLATFORM_POLICY = {"instagram": {"minimum": 5, "maximum": 8, "families": set(FAMILIES)}}
BRAND_POLICIES = {"default": {"themes": set(THEMES), "typography": set(TYPOGRAPHY), "decorations": set(DECORATIONS), "footer": "compact_brand_v1", "brand_name": "O2English"}}
ACCOUNT_BRAND_POLICY: dict[str, str] = {}


def brand_policy_for_account(account: str) -> tuple[str, dict[str, Any]]:
    policy_id = ACCOUNT_BRAND_POLICY.get(account, "default")
    return policy_id, BRAND_POLICIES[policy_id]


def registry_fingerprint() -> str:
    value = {"release": REGISTRY_RELEASE, "families": FAMILIES, "compositions": COMPOSITIONS, "themes": THEMES, "typography": TYPOGRAPHY, "components": COMPONENT_LIFECYCLES, "decorations": DECORATION_LIFECYCLES, "images": IMAGE_TREATMENT_LIFECYCLES, "archetypes": ARCHETYPES, "presets": PRESETS, "brands": BRAND_POLICIES}
    return sha256(json.dumps(value, sort_keys=True, default=sorted, separators=(",", ":")).encode()).hexdigest()


def validate_intent(value: Any) -> dict[str, Any]:
    expected = {"schema_version", "primary_structure", "tone", "density", "emphasis_targets", "image_need"}
    if not isinstance(value, Mapping) or set(value) != expected or value["schema_version"] != "visual_intent_v1": raise ValueError("visual intent has an invalid closed shape")
    if value["primary_structure"] not in INTENT_STRUCTURES or value["tone"] not in INTENT_TONES or value["density"] not in INTENT_DENSITIES: raise ValueError("visual intent has unsupported semantic values")
    if value["image_need"] not in {"none", "optional", "required"} or not isinstance(value["emphasis_targets"], list): raise ValueError("visual intent image or emphasis values are invalid")
    if len(value["emphasis_targets"]) > 4 or any(item not in EMPHASIS_TARGETS for item in value["emphasis_targets"]) or len(set(value["emphasis_targets"])) != len(value["emphasis_targets"]): raise ValueError("visual intent emphasis targets are invalid")
    return dict(value)


def _validate_resolution(value: Mapping[str, Any], archetype: Mapping[str, Any]) -> None:
    composition = COMPOSITIONS.get(value["composition_id"])
    if composition is None or value["family_id"] != archetype["family_id"] or composition["family_id"] != value["family_id"] or value["composition_id"] not in archetype["composition_ids"]: raise ValueError("visual recipe composition is outside its archetype")
    if value["theme_id"] not in archetype["theme_ids"] or value["typography_id"] not in archetype["typography_ids"] or value["density"] not in archetype["density_ids"]: raise ValueError("visual recipe token is outside its archetype")
    if not isinstance(value["components"], Mapping): raise ValueError("visual recipe components are invalid")
    permitted = set(archetype["required_components"]) | set(archetype["optional_components"])
    if not set(value["components"]).issubset(permitted): raise ValueError("visual recipe component is outside its archetype")
    for name, variant in archetype["required_components"].items():
        if value["components"].get(name) != variant: raise ValueError("visual recipe misses an archetype-required component")
    for name, variant in value["components"].items():
        permitted_variants = [archetype["required_components"][name]] if name in archetype["required_components"] else archetype["optional_components"][name]
        if name not in composition["components"] or variant not in permitted_variants: raise ValueError("visual recipe component variant is outside its archetype")
    if not isinstance(value["decorations"], list) or len(set(value["decorations"])) != len(value["decorations"]) or any(item not in archetype["decoration_ids"] for item in value["decorations"]): raise ValueError("visual recipe decoration is outside its archetype")
    if value["image_treatment"] not in archetype["image_treatment_ids"]: raise ValueError("visual recipe image treatment is outside its archetype")


def is_production_eligible(value: Mapping[str, Any]) -> bool:
    archetype, composition = ARCHETYPES.get(value.get("archetype_id")), COMPOSITIONS.get(value.get("composition_id"))
    return bool(archetype and composition and archetype["lifecycle"] == composition["lifecycle"] == "curated" and THEMES[value["theme_id"]]["lifecycle"] == "curated" and TYPOGRAPHY[value["typography_id"]]["lifecycle"] == "curated" and all(COMPONENT_LIFECYCLES[name][variant] == "curated" for name, variant in value["components"].items()) and all(DECORATION_LIFECYCLES[item] == "curated" for item in value["decorations"]) and IMAGE_TREATMENT_LIFECYCLES[value["image_treatment"]] == "curated")


def validate_unit_layouts(recipe: Mapping[str, Any], roles: list[str]) -> None:
    archetype = ARCHETYPES[recipe["archetype_id"]]
    layouts = recipe["unit_layouts"]
    if len(layouts) != len(roles): raise ValueError("visual recipe unit layouts do not match package units")
    if "expected_roles" in archetype and roles != archetype["expected_roles"]:
        raise ValueError("visual recipe package roles do not match its registered slide grammar")
    if "expected_layouts" in archetype and [layout["variant"] for layout in layouts] != archetype["expected_layouts"]:
        raise ValueError("visual recipe layouts do not match its registered slide grammar")
    for ordinal, (layout, role) in enumerate(zip(layouts, roles), start=1):
        if role not in UNIT_ROLES or layout["ordinal"] != ordinal or layout["variant"] not in archetype["unit_layout_variants"][role]: raise ValueError("visual recipe layout variant is outside its archetype")


def validate_recipe(value: Any, *, production: bool) -> dict[str, Any]:
    expected = {"schema_version", "registry_release", "registry_fingerprint", "source", "archetype_id", "preset_id", "family_id", "composition_id", "theme_id", "typography_id", "density", "components", "decorations", "image_treatment", "unit_layouts"}
    if not isinstance(value, Mapping) or set(value) != expected or value["schema_version"] != "visual_recipe_v4": raise ValueError("visual recipe has an invalid closed shape")
    if value["registry_release"] != REGISTRY_RELEASE or value["registry_fingerprint"] != registry_fingerprint(): raise ValueError("visual recipe registry release is unavailable")
    archetype = ARCHETYPES.get(value["archetype_id"])
    if archetype is None: raise ValueError("visual recipe archetype is unavailable")
    source, preset_id = value["source"], value["preset_id"]
    if source not in {"curated_preset", "curated_archetype", "experimental_dynamic", "fallback"} or (source == "curated_preset") != bool(preset_id): raise ValueError("visual recipe source is invalid")
    if preset_id:
        preset = PRESETS.get(preset_id); keys = ("archetype_id", "family_id", "composition_id", "theme_id", "typography_id", "density", "components", "decorations", "image_treatment")
        if preset is None or {key: preset[key] for key in keys} != {key: value[key] for key in keys}: raise ValueError("visual recipe does not exactly match its preset")
    _validate_resolution(value, archetype)
    all_variants = {variant for variants in archetype["unit_layout_variants"].values() for variant in variants}
    if not isinstance(value["unit_layouts"], list) or any(not isinstance(item, Mapping) or set(item) != {"ordinal", "variant"} or type(item["ordinal"]) is not int or item["ordinal"] < 1 or item["variant"] not in all_variants for item in value["unit_layouts"]): raise ValueError("visual recipe unit layouts are invalid")
    if production and (source == "experimental_dynamic" or not is_production_eligible(value)): raise ValueError("visual recipe is not eligible for this renderer mode")
    return dict(value)
