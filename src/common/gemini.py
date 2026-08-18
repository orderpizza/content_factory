"""Small, isolated Vertex Gemini client used by AI-owned phases only."""

import json
import os
from dataclasses import dataclass
from typing import Any


class GeminiConfigurationError(RuntimeError):
    """Raised when the local Vertex configuration is incomplete."""


def configured_model() -> str:
    """Return the configured model name."""
    return os.getenv("GEMINI_MODEL") or os.getenv("VERTEX_AI_MODEL") or "gemini-2.5-flash"


@dataclass(frozen=True)
class GeminiUsage:
    input_tokens: int
    output_tokens: int
    total_tokens: int
    model: str


def estimated_cost_usd(usage: GeminiUsage) -> float | None:
    """Estimate cost from explicitly configured per-million-token rates."""
    input_rate = os.getenv("GEMINI_INPUT_COST_PER_MILLION_USD")
    output_rate = os.getenv("GEMINI_OUTPUT_COST_PER_MILLION_USD")
    if input_rate is None or output_rate is None:
        return None
    return ((usage.input_tokens * float(input_rate)) + (usage.output_tokens * float(output_rate))) / 1_000_000


class VertexGeminiClient:
    """Generate validated JSON without leaking Vertex SDK calls across modules."""

    def __init__(self, *, project: str | None = None, location: str | None = None, model: str | None = None):
        self.project = project or os.getenv("GOOGLE_CLOUD_PROJECT")
        self.location = location or os.getenv("GOOGLE_CLOUD_LOCATION", "us-central1")
        self.model = model or configured_model()
        self.last_usage: GeminiUsage | None = None
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
        usage = response.usage_metadata
        self.last_usage = GeminiUsage(
            input_tokens=int(getattr(usage, "prompt_token_count", 0) or 0),
            output_tokens=int(getattr(usage, "candidates_token_count", 0) or 0),
            total_tokens=int(getattr(usage, "total_token_count", 0) or 0),
            model=self.model,
        )
        return value
