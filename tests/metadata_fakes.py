from pipelines.poc.metadata import GeneratedMetadata
from pipelines.o2_english.content import CarouselSlide, IdiomCarouselContent


class FakeMetadataGenerator:
    def generate(self, *, topic: str, body: str, audience: str, objective: str) -> GeneratedMetadata:
        return GeneratedMetadata(
            caption=f"A concise explanation of {topic}.",
            tags=["education"],
            hashtags=["#ContentFactory"],
            model="fake-gemini",
        )


class FakeIdiomGenerator:
    def generate(self, job):
        return IdiomCarouselContent(
            teaching_target="break the ice",
            slides=(
                CarouselSlide("hook", "Break the ice before the meeting."),
                CarouselSlide("explanation", "It means making people feel comfortable and ready to talk."),
                CarouselSlide("use_case_monologue", "I told a small joke to break the ice."),
                CarouselSlide("use_case_dialogue", messages=("I broke the ice with a question.", "That made everyone relax.")),
                CarouselSlide("use_case_monologue", "Her smile helped break the ice."),
            ),
            caption="Learn how to use break the ice in a conversation.",
            tags=("English learning", "idioms"),
            hashtags=("#learnenglish", "#englishidioms"),
            model="fake-gemini",
        )
