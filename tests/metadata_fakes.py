from pipelines.o2_english.content import CarouselSlide, IdiomCarouselDraft, IdiomCarouselMetadata


class FakeIdiomGenerator:
    def generate(self, job):
        return IdiomCarouselDraft(
            teaching_target="break the ice",
            slides=(
                CarouselSlide("hook", "Break the ice before the meeting."),
                CarouselSlide("explanation", "It means making people feel comfortable and ready to talk."),
                CarouselSlide("use_case_monologue", "I told a small joke to break the ice."),
                CarouselSlide("use_case_dialogue", messages=("I broke the ice with a question.", "That made everyone relax.")),
                CarouselSlide("use_case_monologue", "Her smile helped break the ice."),
            ),
            model="fake-gemini",
        )


class FakeIdiomMetadataGenerator:
    def generate(self, draft, job):
        return IdiomCarouselMetadata(
            caption="Learn how to use break the ice in a conversation.",
            tags=("English learning", "idioms"),
            hashtags=("#learnenglish", "#englishidioms", "#englishpractice"),
            model="fake-gemini",
        )
