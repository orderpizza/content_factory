"""Small, isolated Vertex Gemini client used by AI-owned phases only."""

import json
import os
from dataclasses import dataclass
from typing import Any
from importlib.metadata import PackageNotFoundError, version as package_version


class GeminiConfigurationError(RuntimeError):
    """Raised when the local Vertex configuration is incomplete."""


# Text calls are one provider attempt. A finite deadline leaves an uncertain
# ledger reservation rather than letting a claimed worker wait indefinitely.
DEFAULT_TEXT_TIMEOUT_SECONDS = 180
MAX_TEXT_TIMEOUT_SECONDS = 300
TEXT_CLAIM_LEASE_SECONDS = 600
SDK_RETRY_ATTEMPTS = 1
GLOBAL_TEXT_MODELS = {"gemini-3.7-flash", "gemini-3-flash-preview"}


def text_timeout_seconds(value: str | None = None) -> int:
    """Resolve the finite Gemini text request deadline in seconds."""
    raw = os.getenv("GEMINI_TEXT_TIMEOUT_SECONDS") if value is None else value
    if raw is None or raw == "":
        return DEFAULT_TEXT_TIMEOUT_SECONDS
    try:
        result = int(raw)
    except (TypeError, ValueError) as error:
        raise GeminiConfigurationError(
            "GEMINI_TEXT_TIMEOUT_SECONDS must be a whole number from 1 to "
            f"{MAX_TEXT_TIMEOUT_SECONDS} seconds"
        ) from error
    if not 1 <= result <= MAX_TEXT_TIMEOUT_SECONDS:
        raise GeminiConfigurationError(
            "GEMINI_TEXT_TIMEOUT_SECONDS must be a whole number from 1 to "
            f"{MAX_TEXT_TIMEOUT_SECONDS} seconds"
        )
    return result


def configured_location(model: str | None = None) -> str:
    """Keep operator routing; recommend global by default for known support."""
    selected_model = model or configured_model()
    location = os.getenv("GOOGLE_CLOUD_LOCATION")
    if location:
        return location
    return "global" if selected_model in GLOBAL_TEXT_MODELS else "us-central1"


def configured_api_version(model: str | None = None) -> str:
    """Use stable v1 for GA model IDs and beta routing for preview model IDs."""
    selected_model = model or configured_model()
    explicit = os.getenv("GEMINI_API_VERSION")
    if explicit:
        if explicit not in {"v1", "v1beta"}:
            raise GeminiConfigurationError(
                "GEMINI_API_VERSION must be v1 or v1beta"
            )
        if "preview" in selected_model.casefold() and explicit == "v1":
            raise GeminiConfigurationError(
                f"{selected_model} is a preview model; GEMINI_API_VERSION=v1 may be incompatible"
            )
        return explicit
    return "v1beta" if "preview" in selected_model.casefold() else "v1"


def retryable_provider_error(error):
    """Only completed, explicit provider rejections; never ambiguous local timeouts."""
    try:
        from google.genai.errors import APIError
    except ImportError:
        return False
    if not isinstance(error, APIError):
        return False
    code = getattr(error, 'code', None)
    if callable(code): code = code()
    return type(code) is int and code in {429, 500, 502, 503, 504}


def configured_model() -> str:
    """Return the configured model name."""
    return os.getenv("GEMINI_MODEL") or os.getenv("VERTEX_AI_MODEL") or "gemini-3.7-flash"


def _vertex_response_schema(schema: dict[str, Any]) -> dict[str, Any]:
    """Keep the wire grammar small; callers enforce original list bounds locally.

    Nested array cardinalities in the canonical schema exceed Vertex's grammar
    complexity limit. Describe those bounds to the model without expanding them
    into its constrained decoder. Preserve names, types, required fields and enums.
    """
    result: dict[str, Any] = {}
    for key, value in schema.items():
        if key in {"minItems", "maxItems"} and not schema.get("description", "").startswith("Visible body lines"):
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
    """Generate JSON without leaking Vertex SDK calls across modules.

    Only max_output_tokens is a provider cap. Input reservations belong to the
    ledger, not this transport; no count-tokens preflight request is performed.
    """

    def __init__(
        self,
        *,
        project: str | None = None,
        location: str | None = None,
        model: str | None = None,
        max_output_tokens: int | None = None,
        thinking_level: str | None = None,
        _text_transport: bool = True,
    ):
        self.project = project or os.getenv("GOOGLE_CLOUD_PROJECT")
        self.model = model or configured_model()
        if _text_transport:
            self.location = location or configured_location(self.model)
            self.api_version = configured_api_version(self.model)
            self.timeout_seconds = text_timeout_seconds()
            self.timeout_ms = self.timeout_seconds * 1000
        else:
            # The shared image adapter keeps its independent transport policy.
            self.location = location or os.getenv("GOOGLE_CLOUD_LOCATION", "us-central1")
            self.api_version = None
            self.timeout_seconds = None
            self.timeout_ms = None
        self.sdk_retry_attempts = SDK_RETRY_ATTEMPTS
        try:
            self.google_genai_version = package_version("google-genai")
        except PackageNotFoundError:
            self.google_genai_version = None
        if max_output_tokens is not None and (
            type(max_output_tokens) is not int or max_output_tokens < 1
        ):
            raise GeminiConfigurationError("Gemini max output tokens must be a positive integer")
        self.max_output_tokens = max_output_tokens
        self.thinking_level = thinking_level
        self.last_usage: GeminiUsage | None = None
        self.last_raw_response: str | None = None
        if not self.project:
            raise GeminiConfigurationError("GOOGLE_CLOUD_PROJECT must be configured for Vertex Gemini")

    def generate_json(self, prompt: str, schema: dict[str, Any], *, temperature: float = 0.2) -> dict[str, Any]:
        self.last_usage = None
        self.last_raw_response = None
        try:
            from google import genai
            from google.genai import types
        except ImportError as error:
            raise GeminiConfigurationError(
                "google-genai is not installed; install the project dependencies before using Gemini"
            ) from error

        client = genai.Client(
            vertexai=True,
            project=self.project,
            location=self.location,
            http_options=types.HttpOptions(
                timeout=self.timeout_ms,
                api_version=self.api_version,
                retry_options=types.HttpRetryOptions(attempts=self.sdk_retry_attempts),
            ),
        )
        try:
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
        finally:
            client.close()
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
        self.last_raw_response = response.text
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
