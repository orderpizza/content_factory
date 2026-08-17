"""Small, isolated Vertex Gemini client used by AI-owned phases only."""

import json
import os
from typing import Any


class GeminiConfigurationError(RuntimeError):
    """Raised when the local Vertex configuration is incomplete."""


def configured_model() -> str:
    """Return the configured model, accepting the historic misspelling temporarily."""
    return (
        os.getenv("GEMINI_MODEL")
        or os.getenv("GEMINI_MDOEL")
        or os.getenv("VERTEX_AI_MODEL")
        or "gemini-2.5-flash"
    )


class VertexGeminiClient:
    """Generate validated JSON without leaking Vertex SDK calls across modules."""

    def __init__(self, *, project: str | None = None, location: str | None = None, model: str | None = None):
        self.project = project or os.getenv("GOOGLE_CLOUD_PROJECT")
        self.location = location or os.getenv("GOOGLE_CLOUD_LOCATION", "us-central1")
        self.model = model or configured_model()
        if not self.project:
            raise GeminiConfigurationError("GOOGLE_CLOUD_PROJECT must be configured for Vertex Gemini")

    def generate_json(self, prompt: str, schema: dict[str, Any], *, temperature: float = 0.2) -> dict[str, Any]:
        try:
            from google import genai
            from google.genai import types
        except ImportError as error:
            raise GeminiConfigurationError(
                "google-genai is not installed; install the project dependencies before using Gemini"
            ) from error

        client = genai.Client(vertexai=True, project=self.project, location=self.location)
        response = client.models.generate_content(
            model=self.model,
            contents=prompt,
            config=types.GenerateContentConfig(
                temperature=temperature,
                response_mime_type="application/json",
                response_json_schema=schema,
            ),
        )
        if not response.text:
            raise RuntimeError("Vertex Gemini returned no JSON content")
        try:
            value = json.loads(response.text)
        except json.JSONDecodeError as error:
            raise RuntimeError("Vertex Gemini returned invalid JSON") from error
        if not isinstance(value, dict):
            raise RuntimeError("Vertex Gemini JSON response must be an object")
        return value
