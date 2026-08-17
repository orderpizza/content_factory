"""Metadata generation boundary for the Bluesky POC pipeline."""

from dataclasses import dataclass
import json
from typing import Protocol

from common.gemini import VertexGeminiClient


@dataclass(frozen=True)
class GeneratedMetadata:
    caption: str
    tags: list[str]
    hashtags: list[str]
    model: str


class MetadataGenerator(Protocol):
    def generate(self, *, topic: str, body: str, audience: str, objective: str) -> GeneratedMetadata:
        """Return Gemini-generated platform metadata for one content package."""


class GeminiMetadataGenerator:
    """Gemini metadata generation boundary for the legacy Bluesky POC pipeline."""

    def __init__(self, client: VertexGeminiClient | None = None):
        self.client = client or VertexGeminiClient()

    def generate(self, *, topic: str, body: str, audience: str, objective: str) -> GeneratedMetadata:
        prompt = """Generate metadata for a social-media content package. Return only JSON matching the schema.
Recipe: """ + json.dumps({"topic": topic, "body": body, "audience": audience, "objective": objective})
        data = self.client.generate_json(prompt, _SCHEMA, temperature=0.45)
        hashtags = data["hashtags"]
        if not data["caption"].strip() or not hashtags or any(not value.startswith("#") for value in hashtags):
            raise ValueError("Gemini returned invalid social metadata")
        return GeneratedMetadata(data["caption"], data["tags"], hashtags, self.client.model)


_SCHEMA = {
    "type": "object",
    "required": ["caption", "tags", "hashtags"],
    "properties": {
        "caption": {"type": "string"},
        "tags": {"type": "array", "items": {"type": "string"}},
        "hashtags": {"type": "array", "minItems": 1, "maxItems": 8, "items": {"type": "string"}},
    },
}
