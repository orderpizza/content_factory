"""Single-attempt Vertex storyboard-image transport; no JSON generation."""
from __future__ import annotations

from dataclasses import dataclass
import os
from common.gemini import GeminiUsage, VertexGeminiClient


# Closed capability subset used by the current storyboard renderer contract.
SUPPORTED_STORYBOARD_ASPECT_RATIOS = frozenset({'4:5', '3:2', '5:4'})


def validate_provider_aspect_ratio(value: str) -> str:
    if not isinstance(value, str) or value not in SUPPORTED_STORYBOARD_ASPECT_RATIOS:
        raise ValueError('unsupported storyboard provider aspect ratio')
    return value


def configured_image_model() -> str:
    return os.getenv("GEMINI_IMAGE_MODEL") or "gemini-3.1-flash-image"


def configured_image_size() -> str:
    """Return the requested Gemini image resolution for review assets."""
    return os.getenv("GEMINI_IMAGE_SIZE") or "2K"


@dataclass(frozen=True)
class GeneratedImage:
    """One provider image, preserving its bytes and declared media type."""

    data: bytes
    mime_type: str

    @property
    def extension(self) -> str:
        return {"image/png": ".png", "image/jpeg": ".jpg"}[self.mime_type]


class VertexGeminiImageClient(VertexGeminiClient):
    def __init__(self, **kwargs):
        kwargs.setdefault("model", configured_image_model())
        kwargs["_text_transport"] = False
        super().__init__(**kwargs)

    def generate_image(self, prompt: str, *, aspect_ratio: str = "5:4") -> GeneratedImage:
        validate_provider_aspect_ratio(aspect_ratio)
        from google import genai
        from google.genai import types

        self.last_usage = None
        parts = [types.Part.from_text(text=prompt)]
        client = genai.Client(
            vertexai=True, project=self.project, location=self.location,
            http_options=types.HttpOptions(
                timeout=240_000, retry_options=types.HttpRetryOptions(attempts=1),
            ),
        )
        try:
            response = client.models.generate_content(
                model=self.model, contents=types.Content(role="user", parts=parts),
                config=types.GenerateContentConfig(
                    response_modalities=["TEXT", "IMAGE"], candidate_count=1,
                    image_config=types.ImageConfig(
                        aspect_ratio=aspect_ratio, image_size=configured_image_size(),
                    ),
                    max_output_tokens=self.max_output_tokens,
                ),
            )
        finally:
            client.close()
        usage = response.usage_metadata
        if usage is not None:
            self.last_usage = GeminiUsage(
                int(getattr(usage, "prompt_token_count", 0) or 0),
                int(getattr(usage, "candidates_token_count", 0) or 0)
                + int(getattr(usage, "thoughts_token_count", 0) or 0),
                int(getattr(usage, "total_token_count", 0) or 0), self.model,
            )
        images = []
        for candidate in response.candidates or []:
            if getattr(candidate.finish_reason, "value", candidate.finish_reason) != "STOP":
                raise ValueError("image generation did not finish successfully")
            for part in getattr(candidate.content, "parts", None) or []:
                inline = part.inline_data
                if inline is not None and not getattr(part, "thought", False):
                    if inline.mime_type not in {"image/png", "image/jpeg"} or not inline.data:
                        raise ValueError("image generation returned an unsupported image")
                    images.append(GeneratedImage(inline.data, inline.mime_type))
        if len(images) != 1:
            raise ValueError("image generation must return exactly one storyboard")
        return images[0]
