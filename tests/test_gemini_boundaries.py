import unittest

from common.models import ContentJob
from determination.service import GeminiCandidateEvaluator, POC_PIPELINE_CATALOG
from pipelines.o2_english.content import GeminiIdiomContentGenerator


class FakeGeminiClient:
    model = "test-gemini"

    def __init__(self, response):
        self.response = response
        self.calls = []

    def generate_json(self, prompt, schema, *, temperature):
        self.calls.append((prompt, schema, temperature))
        return self.response


class GeminiBoundaryTests(unittest.TestCase):
    def test_determination_can_select_only_a_catalog_capability(self):
        client = FakeGeminiClient({
            "should_create": True,
            "pipeline_id": "o2_english_instagram",
            "visual_profile_id": "o2_english_idiom_carousel_v1",
            "angle": "Teach the idiom in everyday context.",
            "audience": "English learners",
            "objective": "educate",
            "key_points": ["clear explanation"],
            "priority": 70,
            "reasoning": "Useful to the selected channel.",
        })
        result = GeminiCandidateEvaluator(client).evaluate(
            {"topic": "break the ice", "score": 0.8}, [], POC_PIPELINE_CATALOG,
        )
        self.assertTrue(result.should_create)
        self.assertEqual(result.pipeline.pipeline_id, "o2_english_instagram")
        self.assertEqual(client.calls[0][2], 0.2)

    def test_o2_generator_requires_valid_generated_hashtags(self):
        client = FakeGeminiClient({
            "teaching_target": "break the ice",
            "slides": [
                {"slide_type": "hook", "text": "Break the ice"},
                {"slide_type": "explanation", "text": "Make people feel relaxed when they first meet."},
                {"slide_type": "use_case_monologue", "text": "I told a joke to break the ice."},
                {"slide_type": "use_case_dialogue", "messages": ["The room feels quiet.", "I will break the ice."]},
                {"slide_type": "use_case_monologue", "text": "A friendly question can break the ice."},
            ],
            "caption": "Learn a useful idiom for starting conversations.",
            "tags": ["English idiom", "conversation"],
            "hashtags": ["#EnglishLearning", "#EnglishIdioms"],
        })
        job = ContentJob(1, "o2_english_instagram", "break the ice", "teach it", "learners", "educate",
                         target_platform="instagram", target_account="o2_english",
                         content_format="instagram_idiom_carousel", visual_profile_id="o2_english_idiom_carousel_v1")
        content = GeminiIdiomContentGenerator(client).generate(job)
        self.assertEqual(content.model, "test-gemini")
        self.assertEqual(content.hashtags[0], "#EnglishLearning")

