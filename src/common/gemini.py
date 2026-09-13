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


def _vertex_response_schema(schema: dict[str, Any]) -> dict[str, Any]:
    """Keep the wire grammar small; callers enforce original list bounds locally.

    Nested array cardinalities in the canonical schema exceed Vertex's grammar
    complexity limit. Describe those bounds to the model without expanding them
    into its constrained decoder. Preserve names, types, required fields and enums.
    """
    result: dict[str, Any] = {}
    for key, value in schema.items():
        if key in {"minItems", "maxItems"}:
            continue
        if key in {"properties", "$defs", "definitions"} and isinstance(value, dict):
            result[key] = {name: _vertex_response_schema(child) for name, child in value.items()}
        elif isinstance(value, dict):
            result[key] = _vertex_response_schema(value)
        elif isinstance(value, list):
            result[key] = [_vertex_response_schema(child) if isinstance(child, dict) else child for child in value]
        else:
            result[key] = value
    bounds = []
    if "minItems" in schema:
        bounds.append(f"at least {schema['minItems']} items")
    if "maxItems" in schema:
        bounds.append(f"at most {schema['maxItems']} items")
    if bounds:
        result["description"] = (str(schema.get("description", "")) + " Return " + " and ".join(bounds) + ".").strip()
    return result


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

    def __init__(
        self,
        *,
        project: str | None = None,
        location: str | None = None,
        model: str | None = None,
        max_output_tokens: int | None = None,
        thinking_level: str | None = None,
    ):
        self.project = project or os.getenv("GOOGLE_CLOUD_PROJECT")
        self.location = location or os.getenv("GOOGLE_CLOUD_LOCATION", "us-central1")
        self.model = model or configured_model()
        if max_output_tokens is not None and (
            type(max_output_tokens) is not int or max_output_tokens < 1
        ):
            raise GeminiConfigurationError("Gemini max output tokens must be a positive integer")
        self.max_output_tokens = max_output_tokens
        self.thinking_level = thinking_level
        self.last_usage: GeminiUsage | None = None
        if not self.project:
            raise GeminiConfigurationError("GOOGLE_CLOUD_PROJECT must be configured for Vertex Gemini")

    def generate_json(self, prompt: str, schema: dict[str, Any], *, temperature: float = 0.2) -> dict[str, Any]:
        self.last_usage = None
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
                response_json_schema=_vertex_response_schema(schema),
                max_output_tokens=self.max_output_tokens,
                thinking_config=(
                    {"thinking_level": self.thinking_level}
                    if self.thinking_level is not None else None
                ),
            ),
        )
        # A malformed/empty creative response can still incur a provider charge.
        # Candidates exclude separately billed thinking tokens on Gemini models.
        usage = response.usage_metadata
        if usage is not None:
            self.last_usage = GeminiUsage(
                input_tokens=int(getattr(usage, "prompt_token_count", 0) or 0),
                output_tokens=(
                    int(getattr(usage, "candidates_token_count", 0) or 0)
                    + int(getattr(usage, "thoughts_token_count", 0) or 0)
                ),
                total_tokens=int(getattr(usage, "total_token_count", 0) or 0),
                model=self.model,
            )
        candidates = getattr(response, "candidates", None) or []
        if candidates:
            reason = getattr(candidates[0], "finish_reason", None)
            if getattr(reason, "value", reason) == "MAX_TOKENS":
                raise RuntimeError(
                    "Vertex Gemini output token limit reached before a complete JSON response; "
                    "review the phase output-token limit (including thinking tokens)"
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
