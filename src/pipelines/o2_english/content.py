"""Structured content and metadata contracts for the fixed idiom carousel."""

from dataclasses import dataclass
import json
from typing import Literal, Protocol

from common.gemini import GeminiUsage, VertexGeminiClient
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
class IdiomCarouselDraft:
    teaching_target: str
    slides: tuple[CarouselSlide, ...]
    model: str


@dataclass(frozen=True)
class IdiomCarouselMetadata:
    caption: str
    tags: tuple[str, ...]
    hashtags: tuple[str, ...]
    model: str


@dataclass(frozen=True)
class IdiomCarouselContent:
    teaching_target: str
    slides: tuple[CarouselSlide, ...]
    caption: str
    tags: tuple[str, ...]
    hashtags: tuple[str, ...]
    model: str


class IdiomContentGenerator(Protocol):
    def generate(self, job: ContentJob) -> IdiomCarouselDraft:
        """Generate structured slide content from one persisted ContentJob."""


class IdiomMetadataGenerator(Protocol):
    def generate(self, draft: IdiomCarouselDraft, job: ContentJob) -> IdiomCarouselMetadata:
        """Generate native caption, tags, and hashtags for validated slide content."""


class GeminiIdiomContentGenerator:
    """Gemini-owned structured slide generation, separate from posting metadata."""

    def __init__(self, client: VertexGeminiClient | None = None):
        self.client = client or VertexGeminiClient()
        self.last_usage: GeminiUsage | None = None

    def generate(self, job: ContentJob) -> IdiomCarouselDraft:
        data = self.client.generate_json(_content_prompt(job), _CONTENT_SCHEMA, temperature=0.65)
        self.last_usage = getattr(self.client, "last_usage", None)
        draft = IdiomCarouselDraft(
            teaching_target=data["teaching_target"],
            slides=tuple(_slide(item) for item in data["slides"]),
            model=self.client.model,
        )
        validate_idiom_carousel(draft)
        return draft


class GeminiIdiomMetadataGenerator:
    """Gemini-owned caption, tag, and hashtag generation for validated slides."""

    def __init__(self, client: VertexGeminiClient | None = None):
        self.client = client or VertexGeminiClient()
        self.last_usage: GeminiUsage | None = None

    def generate(self, draft: IdiomCarouselDraft, job: ContentJob) -> IdiomCarouselMetadata:
        data = self.client.generate_json(_metadata_prompt(draft, job), _METADATA_SCHEMA, temperature=0.45)
        self.last_usage = getattr(self.client, "last_usage", None)
        metadata = IdiomCarouselMetadata(
            caption=data["caption"], tags=tuple(data["tags"]), hashtags=tuple(data["hashtags"]), model=self.client.model,
        )
        validate_metadata(metadata)
        return metadata


def _slide(item: dict) -> CarouselSlide:
    return CarouselSlide(
        slide_type=item["slide_type"], text=item.get("text"),
        messages=tuple(item.get("messages", [])), label=item.get("label"),
    )


_CONTENT_SCHEMA = {
    "type": "object", "required": ["teaching_target", "slides"],
    "properties": {
        "teaching_target": {"type": "string"},
        "slides": {"type": "array", "minItems": 5, "maxItems": 8, "items": {
            "type": "object", "required": ["slide_type"], "properties": {
                "slide_type": {"type": "string", "enum": ["hook", "explanation", "use_case_monologue", "use_case_dialogue"]},
                "text": {"type": "string"}, "messages": {"type": "array", "items": {"type": "string"}},
                "label": {"type": "string"},
            },
        }},
    },
}

_METADATA_SCHEMA = {
    "type": "object", "required": ["caption", "tags", "hashtags"],
    "properties": {
        "caption": {"type": "string"}, "tags": {"type": "array", "items": {"type": "string"}},
        "hashtags": {"type": "array", "minItems": 3, "maxItems": 8, "items": {"type": "string"}},
    },
}


def _content_prompt(job: ContentJob) -> str:
    recipe = {key: getattr(job, key) for key in ("topic", "angle", "audience", "objective", "key_points", "sources")}
    return f"""Create an Instagram carousel teaching one useful English idiom for o2_english.
The ContentJob recipe is: {json.dumps(recipe, ensure_ascii=False)}

Return only JSON matching the supplied schema. Use 5–8 slides: first a hook, 1–2
explanations, then 3–5 concrete monologue or two-person dialogue use cases. Keep
copy within the format constraints. Do not generate captions, tags, or hashtags.
Do not invent sources or claims."""


def _metadata_prompt(draft: IdiomCarouselDraft, job: ContentJob) -> str:
    slides = [slide.to_dict() for slide in draft.slides]
    return f"""Generate Instagram posting metadata for an English idiom carousel teaching
{json.dumps(draft.teaching_target, ensure_ascii=False)}.
Slides: {json.dumps(slides, ensure_ascii=False)}
Audience: {job.audience}. Objective: {job.objective}.

Return only JSON matching the supplied schema: an accurate caption, 2–6 specific
tags, and 3–8 relevant hashtags. Hashtags must start with # and contain no spaces."""


def validate_idiom_carousel(content: IdiomCarouselDraft | IdiomCarouselContent) -> None:
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
            if len(slide.messages) != 2 or any(_word_count(message) > 14 for message in slide.messages):
                raise ValueError("Dialogue slides require two messages of at most fourteen words")
        else:
            if not slide.text:
                raise ValueError(f"{slide.slide_type} slide must include text")
            limit = {"hook": 16, "explanation": 34, "use_case_monologue": 22}[slide.slide_type]
            if _word_count(slide.text) > limit:
                raise ValueError(f"{slide.slide_type} exceeds its word limit")


def validate_metadata(metadata: IdiomCarouselMetadata | IdiomCarouselContent) -> None:
    if not metadata.caption.strip():
        raise ValueError("Generated caption must not be empty")
    if not 2 <= len(metadata.tags) <= 6 or not 3 <= len(metadata.hashtags) <= 8:
        raise ValueError("Generate two to six tags and three to eight hashtags")
    if len(set(metadata.tags)) != len(metadata.tags) or len(set(metadata.hashtags)) != len(metadata.hashtags):
        raise ValueError("Tags and hashtags must be unique")
    if any(not tag.startswith("#") or any(character.isspace() for character in tag) for tag in metadata.hashtags):
        raise ValueError("Hashtags must use # syntax and contain no whitespace")


def _word_count(value: str) -> int:
    return len(value.split())
