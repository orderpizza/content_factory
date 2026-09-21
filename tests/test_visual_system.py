"""Archetype, layout, and renderer contracts for the shared visual library."""
from __future__ import annotations

import unittest

from workflow.static_renderer import _unit_html
from workflow.visual_planner import choose_recipe
from workflow.visual_registry import ARCHETYPES, validate_intent, validate_recipe, validate_unit_layouts


def intent(**overrides):
    return {"schema_version": "visual_intent_v1", "primary_structure": "cards", "tone": "friendly", "density": "medium", "emphasis_targets": ["target_expression"], "image_need": "none", **overrides}


def recipe(archetype: str, *, platform: str = "instagram", roles: list[str] | None = None, production: bool = False):
    roles = roles or ["hook", "explanation", "example", "example", "takeaway"]
    return choose_recipe(intent(primary_structure=ARCHETYPES[archetype]["family_id"].replace("_v1", "")), platform=platform, pipeline="english", account="fixture", unit_count=len(roles), unit_roles=roles, production=production, history=[], force_archetype=archetype)[0]


class VisualRegistryTests(unittest.TestCase):
    def test_closed_intent_rejects_raw_rendering_input(self):
        with self.assertRaises(ValueError):
            validate_intent({**intent(), "css": "body { color: red }"})

    def test_first_wave_archetypes_have_distinct_composition_implementations(self):
        identifiers = ["vocab_card_minimal_v1", "editorial_bold_cover_v1", "comparison_cover_bold_v1", "phrase_sheet_v1", "question_pattern_sheet_v1", "vocab_serif_elegant_v1", "dialogue_modern_v1", "scenario_explainer_v1", "process_steps_v1"]
        compositions = {ARCHETYPES[item]["default_composition_id"] for item in identifiers}
        self.assertEqual(len(compositions), len(identifiers))

    def test_required_and_incompatible_component_variants_are_rejected(self):
        value = recipe("dialogue_modern_v1")
        del value["components"]["speech_bubble"]
        with self.assertRaises(ValueError):
            validate_recipe(value, production=False)
        value = recipe("dialogue_modern_v1")
        value["components"]["speech_bubble"] = "filled_v1"
        with self.assertRaises(ValueError):
            validate_recipe(value, production=False)

    def test_per_unit_layouts_are_role_aware_and_closed(self):
        roles = ["hook", "explanation", "example", "takeaway", "takeaway"]
        value = recipe("dialogue_modern_v1", roles=roles)
        self.assertEqual([item["variant"] for item in value["unit_layouts"]], ["dialogue_hero", "dialogue_explanation", "dialogue_exchange", "dialogue_takeaway", "dialogue_takeaway"])
        validate_unit_layouts(value, roles)
        value["unit_layouts"][2]["variant"] = "comparison_cover"
        with self.assertRaises(ValueError):
            validate_unit_layouts(value, roles)

    def test_x_rejects_multi_slide_archetypes_but_keeps_shared_cards(self):
        with self.assertRaises(ValueError):
            recipe("phrase_sheet_v1", platform="x", roles=["hook"])
        value = recipe("vocab_card_minimal_v1", platform="x", roles=["hook"])
        self.assertEqual(value["archetype_id"], "vocab_card_minimal_v1")

    def test_production_filters_experimental_and_accepts_complete_curated_recipe(self):
        with self.assertRaises(ValueError):
            recipe("category_badge_minimal_v1", production=True)
        value = recipe("comparison_cover_bold_v1", production=True)
        self.assertIn(value["source"], {"curated_preset", "curated_archetype"})
        validate_recipe(value, production=True)

    def test_renderer_dispatches_distinct_real_layout_primitives_and_escapes_input(self):
        spec = {"width": 1080, "height": 1350}
        unit = {"role": "example", "title": "NORMAL <ENGLISH> VS FINANCE", "body": "One <safe> example\nTwo & only", "claim_ids": []}
        comparison = recipe("comparison_cover_bold_v1")
        dialogue = recipe("dialogue_modern_v1")
        comparison_html = _unit_html(unit, spec, comparison, 3, 5)
        dialogue_html = _unit_html(unit, spec, dialogue, 3, 5)
        self.assertIn("comparison-columns", comparison_html)
        self.assertIn("speech-bubble", dialogue_html)
        self.assertIn("&lt;ENGLISH&gt;", comparison_html)
        self.assertNotIn("<ENGLISH>", comparison_html)

    def test_semantic_fit_outranks_diversity_for_dialogue(self):
        roles = ["hook", "explanation", "example", "example", "takeaway"]
        first = recipe("dialogue_modern_v1", roles=roles)
        selected, provenance = choose_recipe(intent(primary_structure="dialogue"), platform="instagram", pipeline="english", account="fixture", unit_count=5, unit_roles=roles, production=False, history=[first] * 12)
        self.assertEqual(selected["archetype_id"], "dialogue_modern_v1")
        self.assertGreater(provenance["score"]["semantic_fit"], 0)
