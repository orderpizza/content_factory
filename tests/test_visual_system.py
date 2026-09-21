"""Offline contract tests for deterministic archetype-first visual planning."""
from __future__ import annotations

import unittest

from workflow.visual_planner import choose_recipe
from workflow.visual_registry import ARCHETYPES, PRESETS, registry_fingerprint, validate_intent, validate_recipe


def intent(**overrides):
    return {"schema_version": "visual_intent_v1", "primary_structure": "dialogue", "tone": "friendly", "density": "medium", "emphasis_targets": ["target_expression"], "image_need": "none", **overrides}


class VisualRegistryTests(unittest.TestCase):
    def test_closed_intent_rejects_raw_rendering_input(self):
        with self.assertRaises(ValueError):
            validate_intent({**intent(), "css": "body { color: red }"})

    def test_unknown_or_incompatible_archetype_resolution_is_rejected(self):
        recipe, _ = choose_recipe(intent(primary_structure="editorial"), platform="instagram", pipeline="english", account="fixture", unit_count=5, production=False, history=[])
        recipe["archetype_id"] = "not_a_visual_system"
        with self.assertRaises(ValueError):
            validate_recipe(recipe, production=False)
        recipe, _ = choose_recipe(intent(primary_structure="editorial"), platform="instagram", pipeline="english", account="fixture", unit_count=5, production=False, history=[])
        recipe["theme_id"] = "soft_blue_v1"
        with self.assertRaises(ValueError):
            validate_recipe(recipe, production=False)

    def test_production_selects_only_fully_curated_recipe(self):
        recipe, _ = choose_recipe(intent(primary_structure="comparison", emphasis_targets=["difference"]), platform="instagram", pipeline="personal_finance", account="fixture", unit_count=5, production=True, history=[])
        self.assertIn(recipe["source"], {"curated_preset", "curated_archetype"})
        self.assertEqual(ARCHETYPES[recipe["archetype_id"]]["lifecycle"], "curated")
        validate_recipe(recipe, production=True)

    def test_complete_recipe_maturity_rejects_tested_token(self):
        recipe, _ = choose_recipe(intent(primary_structure="comparison", emphasis_targets=["difference"]), platform="instagram", pipeline="personal_finance", account="fixture", unit_count=5, production=True, history=[])
        recipe["theme_id"] = "soft_lilac_v1"
        with self.assertRaises(ValueError):
            validate_recipe(recipe, production=True)

    def test_experimental_dynamic_archetype_is_preview_only(self):
        recipe, _ = choose_recipe(intent(), platform="instagram", pipeline="english", account="fixture", unit_count=5, production=False, history=[])
        self.assertEqual(recipe["archetype_id"], "dialogue_modern_v1")
        self.assertEqual(recipe["source"], "experimental_dynamic")
        with self.assertRaises(ValueError):
            validate_recipe(recipe, production=True)

    def test_same_archetype_resolves_multiple_approved_variants(self):
        minimal, _ = choose_recipe(intent(primary_structure="editorial", tone="minimal", density="low", emphasis_targets=["takeaway"]), platform="instagram", pipeline="english", account="fixture", unit_count=5, production=False, history=[])
        serious, _ = choose_recipe(intent(primary_structure="editorial", tone="serious", density="low", emphasis_targets=["takeaway"]), platform="instagram", pipeline="english", account="fixture", unit_count=5, production=False, history=[])
        self.assertEqual(minimal["archetype_id"], serious["archetype_id"])
        self.assertNotEqual(minimal["theme_id"], serious["theme_id"])
        validate_recipe(minimal, production=False)
        validate_recipe(serious, production=False)

    def test_identical_input_selects_identical_recipe(self):
        first = choose_recipe(intent(), platform="instagram", pipeline="english", account="fixture", unit_count=5, production=False, history=[])
        second = choose_recipe(intent(), platform="instagram", pipeline="english", account="fixture", unit_count=5, production=False, history=[])
        self.assertEqual(first, second)
        self.assertEqual(first[0]["registry_fingerprint"], registry_fingerprint())

    def test_candidates_are_archetypes_not_primitive_cross_products(self):
        _, provenance = choose_recipe(intent(), platform="instagram", pipeline="english", account="fixture", unit_count=5, production=False, history=[])
        self.assertLessEqual(provenance["candidate_count"], len(ARCHETYPES) + len(PRESETS))

    def test_diversity_can_move_between_semantically_suitable_archetypes(self):
        base = intent(primary_structure="quote", emphasis_targets=["takeaway"])
        first, _ = choose_recipe(base, platform="instagram", pipeline="english", account="fixture", unit_count=5, production=False, history=[])
        history = [first] * 12
        second, provenance = choose_recipe(base, platform="instagram", pipeline="english", account="fixture", unit_count=5, production=False, history=history)
        self.assertNotEqual(first["archetype_id"], second["archetype_id"])
        self.assertGreater(provenance["score"]["semantic_fit"], 0)

    def test_platforms_plan_independently(self):
        instagram, _ = choose_recipe(intent(), platform="instagram", pipeline="english", account="fixture", unit_count=5, production=False, history=[])
        x, _ = choose_recipe(intent(), platform="x", pipeline="english", account="fixture", unit_count=1, production=False, history=[])
        self.assertNotEqual(instagram["archetype_id"], x["archetype_id"])

    def test_explicit_archetype_fallback_is_a_new_resolved_recipe(self):
        recipe, _ = choose_recipe(intent(primary_structure="quote"), platform="instagram", pipeline="english", account="fixture", unit_count=5, production=False, history=[], force_archetype="editorial_clean_v1", fallback=True)
        self.assertEqual(recipe["source"], "fallback")
        self.assertIsNone(recipe["preset_id"])
        validate_recipe(recipe, production=False)

    def test_curated_preset_is_an_exact_archetype_resolution(self):
        recipe, _ = choose_recipe(intent(primary_structure="comparison", emphasis_targets=["difference"]), platform="instagram", pipeline="personal_finance", account="fixture", unit_count=5, production=True, history=[])
        self.assertEqual(recipe["source"], "curated_preset")
        self.assertEqual(recipe["composition_id"], PRESETS[recipe["preset_id"]]["composition_id"])
