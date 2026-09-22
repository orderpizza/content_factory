"""Single-attempt Vertex storyboard-image transport; no JSON generation."""
from __future__ import annotations

import os
from common.gemini import GeminiUsage, VertexGeminiClient


def configured_image_model() -> str:
    return os.getenv("GEMINI_IMAGE_MODEL") or "gemini-3.1-flash-image"


def configured_image_size() -> str:
    """Return the requested Gemini image resolution for review assets."""
    return os.getenv("GEMINI_IMAGE_SIZE") or "1K"


class VertexGeminiImageClient(VertexGeminiClient):
    def __init__(self, **kwargs):
        kwargs.setdefault("model", configured_image_model())
        super().__init__(**kwargs)

    def generate_image(self, prompt: str) -> bytes:
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
                        aspect_ratio="5:4", image_size=configured_image_size(),
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
                    images.append(inline.data)
        if len(images) != 1:
            raise ValueError("image generation must return exactly one slide")
        return images[0]
