"""Structured, validated content contract for the fixed idiom carousel."""

from dataclasses import dataclass
import json
from typing import Literal, Protocol

from common.gemini import VertexGeminiClient
from common.models import ContentJob


SlideType = Literal["hook", "explanation", "use_case_monologue", "use_case_dialogue"]


@dataclass(frozen=True)
class CarouselSlide:
    slide_type: SlideType
    text: str | None = None
    messages: tuple[str, ...] = ()
    label: str | None = None

    def to_dict(self) -> dict:
        data = {"slide_type": self.slide_type}
        if self.text is not None:
            data["text"] = self.text
        if self.messages:
            data["messages"] = list(self.messages)
        if self.label:
            data["label"] = self.label
        return data


@dataclass(frozen=True)
class IdiomCarouselContent:
    teaching_target: str
    slides: tuple[CarouselSlide, ...]
    caption: str
    tags: tuple[str, ...]
    hashtags: tuple[str, ...]
    model: str


class IdiomContentGenerator(Protocol):
    def generate(self, job: ContentJob) -> IdiomCarouselContent:
        """Generate structured content from one persisted ContentJob."""


class GeminiIdiomContentGenerator:
    """Gemini-owned copy, tag, and hashtag generation for the fixed o2 format."""

    def __init__(self, client: VertexGeminiClient | None = None):
        self.client = client or VertexGeminiClient()

    def generate(self, job: ContentJob) -> IdiomCarouselContent:
        data = self.client.generate_json(
            _prompt_for(job),
            _SCHEMA,
            temperature=0.65,
        )
        slides = tuple(
            CarouselSlide(
                slide_type=item["slide_type"],
                text=item.get("text"),
                messages=tuple(item.get("messages", [])),
                label=item.get("label"),
            )
            for item in data["slides"]
        )
        content = IdiomCarouselContent(
            teaching_target=data["teaching_target"],
            slides=slides,
            caption=data["caption"],
            tags=tuple(data["tags"]),
            hashtags=tuple(data["hashtags"]),
            model=self.client.model,
        )
        validate_idiom_carousel(content)
        return content


_SCHEMA = {
    "type": "object",
    "required": ["teaching_target", "slides", "caption", "tags", "hashtags"],
    "properties": {
        "teaching_target": {"type": "string"},
        "slides": {
            "type": "array", "minItems": 5, "maxItems": 8,
            "items": {
                "type": "object", "required": ["slide_type"],
                "properties": {
                    "slide_type": {"type": "string", "enum": ["hook", "explanation", "use_case_monologue", "use_case_dialogue"]},
                    "text": {"type": "string"},
                    "messages": {"type": "array", "items": {"type": "string"}},
                    "label": {"type": "string"},
                },
            },
        },
        "caption": {"type": "string"},
        "tags": {"type": "array", "items": {"type": "string"}},
        "hashtags": {"type": "array", "minItems": 1, "maxItems": 8, "items": {"type": "string"}},
    },
}


def _prompt_for(job: ContentJob) -> str:
    recipe = {
        "topic": job.topic,
        "angle": job.angle,
        "audience": job.audience,
        "objective": job.objective,
        "key_points": job.key_points,
        "sources": job.sources,
    }
    return f"""Create an Instagram carousel teaching one useful English idiom for o2_english.
The ContentJob recipe is: {json.dumps(recipe, ensure_ascii=False)}

Return only JSON matching the supplied schema. Use 5–8 slides: first a hook, 1–2
explanations, then 3–5 concrete monologue or two-person dialogue use cases. Keep
copy within the schema's format constraints. Write an accurate caption for English
learners. Generate 2–6 relevant, specific tags and 3–8 relevant hashtags. Hashtags
must begin with # and must not contain spaces. Do not invent sources or claims."""


def validate_idiom_carousel(content: IdiomCarouselContent) -> None:
    slides = content.slides
    if not 5 <= len(slides) <= 8:
        raise ValueError("Idiom carousel must contain five to eight slides")
    if not slides or slides[0].slide_type != "hook":
        raise ValueError("Idiom carousel must begin with a hook slide")
    explanations = [slide for slide in slides if slide.slide_type == "explanation"]
    use_cases = [slide for slide in slides if slide.slide_type.startswith("use_case")]
    if len(explanations) not in {1, 2}:
        raise ValueError("Idiom carousel must contain one or two explanation slides")
    if not 3 <= len(use_cases) <= 5:
        raise ValueError("Idiom carousel must contain three to five use-case slides")
    for slide in slides:
        if slide.slide_type == "use_case_dialogue":
            if len(slide.messages) != 2:
                raise ValueError("Dialogue slides must contain exactly two messages")
            if any(_word_count(message) > 14 for message in slide.messages):
                raise ValueError("Dialogue messages must contain at most fourteen words")
        else:
            if not slide.text:
                raise ValueError(f"{slide.slide_type} slide must include text")
            limit = {"hook": 16, "explanation": 34, "use_case_monologue": 22}[slide.slide_type]
            if _word_count(slide.text) > limit:
                raise ValueError(f"{slide.slide_type} exceeds its word limit")
    if not content.caption.strip():
        raise ValueError("Generated caption must not be empty")
    if not content.hashtags or len(content.hashtags) > 8:
        raise ValueError("Generate one to eight hashtags")
    if len(set(content.tags)) != len(content.tags) or len(set(content.hashtags)) != len(content.hashtags):
        raise ValueError("Tags and hashtags must be unique")
    if any(not tag.startswith("#") or any(character.isspace() for character in tag) for tag in content.hashtags):
        raise ValueError("Hashtags must use # syntax and contain no whitespace")


def _word_count(value: str) -> int:
    return len(value.split())
