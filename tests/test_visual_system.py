"""Archetype, layout, and renderer contracts for the shared visual library."""
from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
import json

from workflow.static_renderer import _unit_html
from workflow.visual_primitives import EXPRESSION_RECOMPOSE_CSS, EXPRESSION_RECOMPOSE_FINAL_CSS
from workflow.visual_planner import choose_recipe
from workflow.visual_registry import ARCHETYPES, validate_intent, validate_recipe, validate_unit_layouts
from workflow.visual_expression import headline_scale, resolve_dialogue_avatars, validate_expression_units


def intent(**overrides):
    return {"schema_version": "visual_intent_v1", "primary_structure": "cards", "tone": "friendly", "density": "medium", "emphasis_targets": ["target_expression"], "image_need": "none", **overrides}


def recipe(archetype: str, *, platform: str = "instagram", roles: list[str] | None = None, production: bool = False):
    roles = roles or ["hook", "explanation", "example", "example", "takeaway"]
    return choose_recipe(intent(primary_structure=ARCHETYPES[archetype]["family_id"].replace("_v1", "")), platform=platform, pipeline="english", account="fixture", unit_count=len(roles), unit_roles=roles, production=production, history=[], force_archetype=archetype)[0]


EXPRESSION_ROLES = ["hook", "explanation", "explanation", "example", "example", "takeaway"]
EXPRESSION_UNITS = [
    {"role": "hook", "title": "Break the ice", "body": "Start a conversation and make people feel more comfortable.", "claim_ids": []},
    {"role": "explanation", "title": "What it means", "body": "To start a conversation and make people feel more comfortable, especially in a new situation.\nSimilar to: make people feel at ease.", "claim_ids": []},
    {"role": "explanation", "title": "When to use it", "body": "Meeting someone for the first time\nAn awkward or quiet atmosphere\nIncluding someone in a group\nEntering a new environment", "claim_ids": []},
    {"role": "example", "title": "Break the ice", "body": "She told a funny story to break the ice at the meeting.\nI asked a casual question to break the ice with new classmates.", "claim_ids": []},
    {"role": "example", "title": "Break the ice", "body": "Mia: It feels quiet in here.\nJay: I can break the ice with a question.\nMia: Great, ask about everyone's weekend.\nJay: That should help everyone relax.", "claim_ids": []},
    {"role": "takeaway", "title": "Remember this", "body": "Use it when a moment feels awkward\nStart with a friendly simple comment\nHelp people feel more comfortable", "claim_ids": []},
]


class VisualRegistryTests(unittest.TestCase):
    def test_closed_intent_rejects_raw_rendering_input(self):
        with self.assertRaises(ValueError):
            validate_intent({**intent(), "css": "body { color: red }"})

    def test_first_wave_archetypes_have_distinct_composition_implementations(self):
        identifiers = ["vocab_card_minimal_v1", "expression_breakdown_v1", "editorial_bold_cover_v1", "comparison_cover_bold_v1", "phrase_sheet_v1", "question_pattern_sheet_v1", "vocab_serif_elegant_v1", "dialogue_modern_v1", "scenario_explainer_v1", "process_steps_v1"]
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
        with self.assertRaises(ValueError):
            recipe("expression_breakdown_v1", roles=EXPRESSION_ROLES, production=True)
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

    def test_expression_breakdown_has_its_registered_six_layouts(self):
        value = recipe("expression_breakdown_v1", roles=EXPRESSION_ROLES)
        self.assertEqual([item["variant"] for item in value["unit_layouts"]], ["hook_hero", "meaning_definition", "use_case_checklist", "example_cards", "dialogue_bubbles", "takeaway_summary"])
        validate_unit_layouts(value, EXPRESSION_ROLES)
        value["unit_layouts"][4]["variant"] = "example_cards"
        with self.assertRaises(ValueError):
            validate_unit_layouts(value, EXPRESSION_ROLES)

    def test_expression_content_capacity_and_fixed_type_scales(self):
        validate_expression_units(EXPRESSION_UNITS)
        oversized = [dict(unit) for unit in EXPRESSION_UNITS]
        oversized[0]["title"] = "One two three four five six"
        with self.assertRaises(ValueError):
            validate_expression_units(oversized)
        self.assertEqual(headline_scale("Break the ice"), "headline_xl")
        self.assertEqual(headline_scale("How to make a natural first impression"), "headline_m")

    def test_expression_dispatches_real_primitives_and_uses_dev_placeholders(self):
        value = recipe("expression_breakdown_v1", roles=EXPRESSION_ROLES)
        spec = {"width": 1080, "height": 1350}
        markup = [_unit_html(unit, spec, value, number, 6) for number, unit in enumerate(EXPRESSION_UNITS, start=1)]
        for marker, html in zip(("hook-hero", "expression-definition", "expression-checklist", "expression-examples", "expression-dialogue", "expression-summary"), markup):
            self.assertIn(marker, html)
            self.assertIn("data-bound", html)
        self.assertIn("expression-topbar", markup[0])
        self.assertIn("1 / 6", markup[0])
        self.assertIn("expression-footer", markup[0])
        self.assertIn("Swipe →", markup[0])
        self.assertIn("Keep learning! →", markup[5])
        self.assertIn("marker-highlight", markup[0])
        self.assertIn("expression-emphasis", markup[3])
        self.assertIn("What does it mean?", markup[1])
        self.assertIn("MEANING", markup[1])
        self.assertIn("In a sentence", markup[3])
        self.assertIn("IN A CONVERSATION", markup[4])
        self.assertIn("Remember!", markup[5])
        self.assertIn("closing-lockup", markup[5])

    def test_expression_recomposition_uses_content_fitted_layout_rules(self):
        self.assertNotIn("flex:1", EXPRESSION_RECOMPOSE_CSS)
        for selector in ("meaning-definition", "use-case-checklist", "example-cards", "dialogue-bubbles", "takeaway-summary"):
            self.assertIn(selector, EXPRESSION_RECOMPOSE_CSS)
        for selector in ("expression-topbar", "expression-footer", "expression-emphasis", "expression-hero-title"):
            self.assertIn(selector, EXPRESSION_RECOMPOSE_FINAL_CSS)

    def test_avatar_manifest_is_safe_and_production_requires_assets(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            manifest = {"schema_version": "visual_avatar_manifest_v1", "avatars": {
                "speaker_01": {"file": "speaker_01.png", "orientation": "right", "mood": ["friendly"]},
                "speaker_02": {"file": "speaker_02.png", "orientation": "left", "mood": ["friendly"]},
            }}
            (root / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
            placeholders = resolve_dialogue_avatars(production=False, avatar_root=root)
            self.assertEqual([item["mode"] for item in placeholders], ["placeholder", "placeholder"])
            with self.assertRaises(ValueError):
                resolve_dialogue_avatars(production=True, avatar_root=root)
            manifest["avatars"]["speaker_01"]["file"] = "../escape.png"
            (root / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
            with self.assertRaises(ValueError):
                resolve_dialogue_avatars(production=False, avatar_root=root)

    def test_expression_resolves_approved_local_avatars_when_present(self):
        avatars = resolve_dialogue_avatars(production=True)
        self.assertEqual([item["mode"] for item in avatars], ["asset", "asset"])

    def test_local_icons_are_recolorable_svg_assets(self):
        root = Path(__file__).resolve().parents[1] / "assets" / "visual" / "icons"
        for name in ("lightbulb", "check", "target", "pin", "arrow_right"):
            self.assertIn("currentColor", (root / f"{name}.svg").read_text(encoding="utf-8"))
