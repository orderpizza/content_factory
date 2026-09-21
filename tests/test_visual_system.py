"""Offline contract tests for deterministic shared visual planning."""
from __future__ import annotations

import unittest

from workflow.visual_planner import choose_recipe
from workflow.visual_registry import PRESETS, registry_fingerprint, validate_intent, validate_recipe


def intent(**overrides):
    return {"schema_version": "visual_intent_v1", "primary_structure": "dialogue",
            "tone": "friendly", "density": "medium", "emphasis_targets": ["target_expression"],
            "image_need": "none", **overrides}


class VisualRegistryTests(unittest.TestCase):
    def test_closed_intent_rejects_raw_rendering_input(self):
        with self.assertRaises(ValueError):
            validate_intent({**intent(), "css": "body { color: red }"})

    def test_unknown_recipe_capability_is_rejected(self):
        recipe, _ = choose_recipe(intent(), platform="instagram", pipeline="english", account="fixture", unit_count=5, production=False, history=[])
        recipe["theme_id"] = "#EEF5FA"
        with self.assertRaises(ValueError):
            validate_recipe(recipe, production=False)

    def test_production_rejects_tested_recipe(self):
        recipe, _ = choose_recipe(intent(primary_structure="cards"), platform="instagram", pipeline="english", account="fixture", unit_count=5, production=False, history=[])
        recipe["theme_id"] = "soft_lilac_v1"
        with self.assertRaises(ValueError):
            validate_recipe(recipe, production=True)

    def test_identical_input_selects_identical_recipe(self):
        first = choose_recipe(intent(), platform="instagram", pipeline="english", account="fixture", unit_count=5, production=False, history=[])
        second = choose_recipe(intent(), platform="instagram", pipeline="english", account="fixture", unit_count=5, production=False, history=[])
        self.assertEqual(first, second)
        self.assertEqual(first[0]["registry_fingerprint"], registry_fingerprint())

    def test_platforms_can_choose_different_recipes(self):
        instagram, _ = choose_recipe(intent(), platform="instagram", pipeline="english", account="fixture", unit_count=5, production=False, history=[])
        x, _ = choose_recipe(intent(), platform="x", pipeline="english", account="fixture", unit_count=1, production=False, history=[])
        self.assertNotEqual(instagram["composition_id"], x["composition_id"])

    def test_semantic_fit_outranks_recent_use_penalty(self):
        history = [{"composition_id": "dialogue_alternating_bubbles_v1", "family_id": "dialogue_v1"}] * 4
        recipe, provenance = choose_recipe(intent(), platform="instagram", pipeline="english", account="fixture", unit_count=5, production=False, history=history)
        self.assertEqual(recipe["family_id"], "dialogue_v1")
        self.assertGreater(provenance["score"]["semantic_fit"], 0)

    def test_explicit_fallback_composition_is_honored(self):
        recipe, _ = choose_recipe(intent(), platform="instagram", pipeline="english", account="fixture", unit_count=5, production=False, history=[], force_composition="dialogue_stacked_transcript_v1")
        self.assertEqual(recipe["composition_id"], "dialogue_stacked_transcript_v1")

    def test_curated_preset_resolves_to_recipe(self):
        recipe, _ = choose_recipe(intent(), platform="instagram", pipeline="english", account="fixture", unit_count=5, production=False, history=[])
        self.assertEqual(recipe["preset_id"], "conversational_blue_01")
        self.assertEqual(recipe["composition_id"], PRESETS[recipe["preset_id"]]["composition_id"])
