"""Gemini-backed Instagram adaptation for review or production."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any
import json
from copy import deepcopy
import re
import unicodedata

from .model_trace import generate_json
from common.gemini import VertexGeminiClient, configured_model

from .store import WorkflowStore
from .workers import local_operation
from .visual_explainers import validate_domain_units
from .active_visual_profiles import validate_recipe
from .content_contract import resolve_content_contract, semantic_qa
from .visual_cues import VISUAL_CUES_SCHEMA, validate_cues


ADAPTATION_PROMPT_VERSION = "workflow_gemini_adaptation_prompt_v12"
METADATA_RETRY_PROMPT_VERSION = "workflow_gemini_adaptation_metadata_retry_v2"
ADAPTATION_SCHEMA_VERSION = "output_adaptation_v4"
SUPPORTED_FORMATS = {
    ("instagram", "instagram_static_carousel_v2"),
}


def _string(maximum=None) -> dict[str, Any]:
    return {"type": "string", "minLength": 1, **({"maxLength": maximum} if maximum else {})}


_UNIT_SCHEMA = {
    "type": "object",
    "required": ["role", "title", "body", "claim_ids"],
    "additionalProperties": False,
    "properties": {
        "role": {
            "type": "string",
            "enum": ["hook", "explanation", "example", "takeaway"],
        },
        "title": _string(120),
        "body": _string(600),
        "claim_ids": {
            "type": "array", "maxItems": 30, "items": _string(120),
        },
    },
}

def adaptation_schema(platform: str, content_format: str, pipeline_id: str = "english") -> dict[str, Any]:
    if (platform, content_format) not in SUPPORTED_FORMATS:
        raise ValueError(f"unsupported review-only output: {platform}/{content_format}")
    from .storyboard_planner import slide_bounds
    minimum, maximum = slide_bounds(pipeline_id)
    cues_schema = deepcopy(VISUAL_CUES_SCHEMA)
    cues_schema['maxItems'] = maximum
    cues_schema['items']['properties']['slide']['maximum'] = maximum
    unit_schema = deepcopy(_UNIT_SCHEMA)
    unit_schema['properties']['title']['maxLength'] = 120 if pipeline_id == 'english' else 80
    unit_schema['properties']['body']['maxLength'] = 600 if pipeline_id == 'english' else 280
    unit_schema['properties']['title']['description'] = 'Use the resolved content contract title capacity.'
    unit_schema['properties']['body']['description'] = 'Use the resolved content contract body capacity.'
    common = {
        "private_tags": {
            "type": "array", "minItems": 2, "maxItems": 6, "items": _string(80),
        },
        "hashtags": {
            "type": "array", "maxItems": 8,
            "items": {**_string(49), "pattern": r"^#[a-z0-9_]{1,48}$"},
        },
        "alt_text": _string(1000),
        "public_text_claim_ids": {
            "type": "array", "maxItems": 30, "items": _string(120),
        },
    }
    properties = {
        **common,
        "visual_cues": cues_schema,
        "caption_summary": _string(1100),
        "cta": {"anyOf": [
            {**_string(), "maxLength": 120,
             "pattern": r"^\S+(?:\s+\S+){0,11}$",
             "description": "A short CTA, ideally 4-7 words; at most 12 words. Use null if unnecessary."},
            {"type": "null"},
        ]},
        "visual_units": {
            "type": "array", "minItems": minimum, "maxItems": maximum,
            "items": unit_schema,
        },
    }
    required = [
        "caption_summary", "cta", "private_tags", "hashtags", "alt_text",
        "public_text_claim_ids", "visual_units", "visual_cues",
    ]
    return {
        "type": "object",
        "required": required,
        "additionalProperties": False,
        "properties": properties,
    }


class GeminiAdaptationWorker:
    """Adapt canonical content for one frozen destination."""

    def __init__(
        self,
        store: WorkflowStore,
        client: Any | None = None,
        *,
        instance_id: str = "adaptation-gemini",
        production: bool = False,
        strict_english_capacity: bool = False,
    ):
        self.store = store
        maximum = None
        if store.model_budget_policy is not None:
            maximum = store.model_budget_policy.phase_limits["adaptation"][1]
        self.client = client or VertexGeminiClient(
            max_output_tokens=maximum,
            thinking_level="LOW" if configured_model().startswith("gemini-3") else None,
        )
        self.instance_id = instance_id
        self.production = production
        self.strict_english_capacity = strict_english_capacity

    def run_once(self) -> int | None:
        run = self.store.claim(
            "adaptation_runs", "adaptation_run_id", self.instance_id, lease_seconds=600
        )
        if run is None:
            return None
        return self._process(run)

    @local_operation("adaptation_runs", "adaptation_run_id")
    def _process(self, run: Any) -> int | None:
        output = self.store.connection.execute(
            "SELECT o.*,c.canonical_json,c.canonical_hash,j.pipeline_id "
            "FROM output_requests o "
            "JOIN canonical_contents c ON c.canonical_content_id=o.canonical_content_id "
            "JOIN content_jobs j ON j.content_job_id=c.content_job_id "
            "WHERE o.output_request_id=?",
            (run["output_request_id"],),
        ).fetchone()
        if output is None:
            raise ValueError("adaptation run references a missing OutputRequest")
        platform = output["platform"]
        content_format = output["content_format"]
        schema = adaptation_schema(platform, content_format, output["pipeline_id"])
        canonical = json.loads(output["canonical_json"])
        selected = self.store.connection.execute(
            "SELECT recipe_json FROM visual_recipes WHERE visual_recipe_id=? AND output_request_id=?",
            (run["visual_recipe_id"], output["output_request_id"])).fetchone()
        if selected is None:
            raise ValueError("adaptation requires a committed visual selection")
        recipe = validate_recipe(json.loads(selected[0]))
        archetype_id = recipe['archetype_id']
        request_value = {
            "pipeline_id": output["pipeline_id"],
            "canonical_content": canonical,
            "content_contract": resolve_content_contract(canonical, archetype_id),
            "destination": {
                "platform": platform,
                "account": output["account"],
                "content_format": content_format,
                "output_contract_version": output["output_contract_version"],
            },
            "safety_mode": (
                "production_destination_human_review_required"
                if self.production else "synthetic_destination_review_only"
            ),
        }
        contract = request_value['content_contract']
        schema['properties']['visual_units'].update(minItems=contract['minimum_units'], maxItems=contract['maximum_units'])
        if self.production and run["adapted_body_json"] is not None:
            body = json.loads(run["adapted_body_json"])
            metadata = self._retry_metadata(run, request_value, body)
            response = {**body, **metadata}
            package = _validate_package(
                response, canonical, platform=platform, account=output["account"],
                content_format=content_format, production=True, pipeline_id=output["pipeline_id"],
                strict_english_capacity=self.strict_english_capacity, archetype_id=archetype_id,
            )
            self.store.checkpoint_adaptation(run, metadata=metadata)
            return self.store.create_package(run, package)
        invocation_id = self.store.begin_model_invocation(
            phase="adaptation",
            table="adaptation_runs",
            key="adaptation_run_id",
            row=run,
            request_version=str(output["output_contract_version"]),
            prompt_version=ADAPTATION_PROMPT_VERSION,
            schema_version=ADAPTATION_SCHEMA_VERSION,
            request_value=request_value,
            model_id=str(getattr(self.client, "model", "gemini")),
        )
        try:
            response = generate_json(self.store, invocation_id, self.client,
                _adaptation_prompt(request_value), schema,
                temperature=(0.3 if self.strict_english_capacity else 1.0)
                if str(getattr(self.client, "model", "")).startswith("gemini-3") else 0.3,
            )
        except Exception as error:
            outcome = "parse_failed" if "json" in str(error).casefold() else "transport_failed"
            self.store.finish_model_invocation(
                invocation_id,
                outcome=outcome,
                usage=getattr(self.client, "last_usage", None),
                error=str(error),
            )
            raise

        try:
            package = _validate_package(
                response,
                canonical,
                platform=platform,
                account=output["account"],
                content_format=content_format,
                production=self.production,
                pipeline_id=output["pipeline_id"],
                strict_english_capacity=self.strict_english_capacity, archetype_id=archetype_id,
            )
        except Exception as error:
            body = None
            if self.production:
                try:
                    body = _validated_body_checkpoint(
                        response, canonical, platform=platform, pipeline_id=output["pipeline_id"],
                        strict_english_capacity=self.strict_english_capacity, archetype_id=archetype_id,
                    )
                except ValueError:
                    body = None
            self.store.finish_model_invocation(
                invocation_id,
                outcome="schema_failed",
                usage=getattr(self.client, "last_usage", None),
                response_value=response,
                error=str(error),
            )
            if body is None:
                raise
            self.store.checkpoint_adaptation(run, body=body)
            metadata = self._retry_metadata(run, request_value, body)
            response = {**body, **metadata}
            package = _validate_package(
                response, canonical, platform=platform, account=output["account"],
                content_format=content_format, production=True, pipeline_id=output["pipeline_id"],
                strict_english_capacity=self.strict_english_capacity, archetype_id=archetype_id,
            )
            self.store.checkpoint_adaptation(run, metadata=metadata)
            return self.store.create_package(run, package)

        if self.production:
            self.store.checkpoint_adaptation(
                run,
                body=_validated_body_checkpoint(
                    response, canonical, platform=platform, pipeline_id=output["pipeline_id"],
                    strict_english_capacity=self.strict_english_capacity, archetype_id=archetype_id,
                ),
                metadata=_validated_metadata(response, platform=platform),
            )
        self.store.finish_model_invocation(
            invocation_id,
            outcome="succeeded",
            usage=getattr(self.client, "last_usage", None),
            response_value=response,
        )
        return self.store.create_package(run, package)

    def _retry_metadata(
        self, run: Any, request_value: dict[str, Any], body: dict[str, Any]
    ) -> dict[str, Any]:
        platform = request_value["destination"]["platform"]
        schema = metadata_schema(platform)
        retry_value = {"checkpointed_adapted_body": body}
        invocation_id = self.store.begin_model_invocation(
            phase="adaptation", table="adaptation_runs", key="adaptation_run_id", row=run,
            request_version=str(request_value["destination"]["output_contract_version"]),
            prompt_version=METADATA_RETRY_PROMPT_VERSION,
            schema_version="output_metadata_v1", request_value=retry_value,
            model_id=str(getattr(self.client, "model", "gemini")),
        )
        try:
            response = generate_json(self.store, invocation_id, self.client,
                _metadata_retry_prompt(retry_value), schema,
                temperature=1.0 if str(getattr(self.client, "model", "")).startswith("gemini-3") else 0.2,
            )
            if not isinstance(response, Mapping) or set(response) != {
                "private_tags", "hashtags", "alt_text"
            }:
                raise ValueError("metadata retry returned missing or unknown fields")
            metadata = _validated_metadata(response, platform=platform)
        except Exception as error:
            self.store.finish_model_invocation(
                invocation_id,
                outcome="schema_failed" if isinstance(error, ValueError) else "transport_failed",
                usage=getattr(self.client, "last_usage", None),
                response_value=response if "response" in locals() else None,
                error=str(error),
            )
            raise
        self.store.finish_model_invocation(
            invocation_id, outcome="succeeded", usage=getattr(self.client, "last_usage", None),
            response_value=response,
        )
        return metadata


def metadata_schema(platform: str) -> dict[str, Any]:
    return {
        "type": "object",
        "required": ["private_tags", "hashtags", "alt_text"],
        "additionalProperties": False,
        "properties": {
            "private_tags": {"type": "array", "minItems": 2, "maxItems": 6,
                             "items": _string(80)},
            "hashtags": {"type": "array", "maxItems": 8,
                         "items": {**_string(49), "pattern": r"^#[a-z0-9_]{1,48}$"}},
            "alt_text": _string(1000),
        },
    }


def _validated_body_checkpoint(
    value: Any, canonical: Mapping[str, Any], *, platform: str, pipeline_id: str | None = None,
    strict_english_capacity: bool = False, archetype_id: str | None = None,
) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise ValueError("adapted body must be an object")
    canonical_claims = canonical.get("claims")
    if not isinstance(canonical_claims, list):
        raise ValueError("canonical claims are missing")
    allowed = {item.get("claim_id") for item in canonical_claims if isinstance(item, Mapping)}
    if None in allowed or len(allowed) != len(canonical_claims):
        raise ValueError("canonical claim identities are invalid")
    public = sorted(_claim_ids(value.get("public_text_claim_ids"), allowed))
    from .storyboard_planner import slide_bounds
    units = _visual_units(value.get("visual_units"), allowed, *slide_bounds(pipeline_id or canonical.get("pipeline_id", "english")))
    if units[0]["role"] != "hook" or units[-1]["role"] != "takeaway":
        raise ValueError("Instagram units must start with hook and end with takeaway")
    if archetype_id is not None:
        semantic_qa(units, canonical, resolve_content_contract(canonical, archetype_id),
                    value.get('caption_summary', ''), value['public_text_claim_ids'])
    else:
        validate_domain_units(units, pipeline_id or canonical.get("pipeline_id"),
                              strict_english=strict_english_capacity)
    cta = value.get("cta")
    if cta is not None:
        cta = _bounded_text(cta, "cta", 1, 120)
        if len(cta.split()) > 12:
            raise ValueError("Instagram CTA exceeds the 12-word local bound")
    body = {"caption_summary": _bounded_text(value.get("caption_summary"),
                                              "caption_summary", 1, 1100),
            "cta": cta, "public_text_claim_ids": public, "visual_units": units,
            "visual_cues": validate_cues(value.get("visual_cues"), allowed, units)}
    mapped = set(public) | {
        claim for unit in body["visual_units"]
        for claim in unit["claim_ids"]
    }
    if mapped != allowed:
        raise ValueError("checkpointed body must map every canonical claim")
    return body


def _validated_metadata(value: Any, *, platform: str) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise ValueError("adaptation metadata must be an object")
    expected = {"private_tags", "hashtags", "alt_text"}
    selected = {key: value.get(key) for key in expected}
    if any(key not in value for key in expected):
        raise ValueError("adaptation metadata is incomplete")
    return {
        "private_tags": _normalized_tags(selected["private_tags"]),
        "hashtags": _hashtags(selected["hashtags"], maximum=8),
        "alt_text": _bounded_text(selected["alt_text"], "alt_text", 1, 1000),
    }


def _validate_package(
    value: Any,
    canonical: Mapping[str, Any],
    *,
    platform: str,
    account: str,
    content_format: str,
    production: bool = False,
    pipeline_id: str | None = None,
    strict_english_capacity: bool = False, archetype_id: str | None = None,
) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise ValueError("Gemini adaptation response must be an object")
    expected = set(adaptation_schema(platform, content_format)["required"])
    if set(value) != expected:
        raise ValueError("adaptation response has missing or unknown fields")

    tags = _normalized_tags(value["private_tags"])
    hashtags = _hashtags(value["hashtags"], maximum=8)
    alt_text = _bounded_text(value["alt_text"], "alt_text", 1, 1000)
    canonical_claims = canonical.get("claims")
    if not isinstance(canonical_claims, list):
        raise ValueError("canonical claims are missing")
    canonical_claim_ids = {
        item.get("claim_id") for item in canonical_claims if isinstance(item, Mapping)
    }
    if None in canonical_claim_ids or len(canonical_claim_ids) != len(canonical_claims):
        raise ValueError("canonical claim identities are invalid")
    public_claims = _claim_ids(value["public_text_claim_ids"], canonical_claim_ids)

    from .storyboard_planner import slide_bounds
    units = _visual_units(value["visual_units"], canonical_claim_ids, *slide_bounds(pipeline_id or canonical.get("pipeline_id", "english")))
    if units[0]["role"] != "hook" or units[-1]["role"] != "takeaway":
        raise ValueError("Instagram units must start with hook and end with takeaway")
    if archetype_id is None:
        validate_domain_units(units, pipeline_id or canonical.get("pipeline_id"),
                              strict_english=strict_english_capacity)
    cta = value["cta"]
    if cta is not None:
        cta = _bounded_text(cta, "cta", 1, 120)
        if len(cta.split()) > 12:
            raise ValueError("Instagram CTA exceeds the 12-word local bound")
    summary = _bounded_text(value["caption_summary"], "caption_summary", 1, 1100)
    pieces = [canonical["hook"], summary]
    if cta:
        pieces.append(cta)
    if hashtags:
        pieces.append(" ".join(hashtags))
    public_text = "\n\n".join(pieces)
    if len(public_text) > 1500:
        raise ValueError("Instagram caption exceeds the 1,500-code-point local bound")
    mapped = public_claims | {
        claim_id for unit in units for claim_id in unit["claim_ids"]
    }
    if mapped != canonical_claim_ids:
        raise ValueError("every canonical claim must be mapped exactly within the package")
    claim_mappings = [
        {
            "claim_id": claim_id,
            "placements": (
                (["public_text"] if claim_id in public_claims else [])
                + [f"visual_unit:{index}" for index, unit in enumerate(units, start=1)
                   if claim_id in unit["claim_ids"]]
            ),
        }
        for claim_id in sorted(canonical_claim_ids)
    ]
    visual_cues = validate_cues(value["visual_cues"], canonical_claim_ids, units)
    package = {
        "schema_version": ADAPTATION_SCHEMA_VERSION,
        "platform": platform,
        "account": account,
        "format": content_format,
        "public_text": public_text,
        "private_tags": tags,
        "hashtags": hashtags,
        "alt_text": alt_text,
        "claim_mappings": claim_mappings,
        "visual_units": units,
        "visual_cues": visual_cues,
        "archetype_id": archetype_id,
        "delivery_ready": production,
    }
    if archetype_id is not None:
        package['content_contract'] = resolve_content_contract(canonical, archetype_id)
        package['semantic_qa'] = semantic_qa(units, canonical, package['content_contract'], public_text, public_claims)
    package["caption"] = public_text
    package["cta"] = cta
    return package


def _bounded_text(value: Any, field: str, minimum: int, maximum: int) -> str:
    if not isinstance(value, str):
        raise ValueError(f"{field} must be a string")
    text = unicodedata.normalize("NFKC", value).strip()
    if not minimum <= len(text) <= maximum:
        raise ValueError(f"{field} must contain {minimum}-{maximum} code points")
    return text


def _normalized_tags(value: Any) -> list[str]:
    if not isinstance(value, list) or not 2 <= len(value) <= 6:
        raise ValueError("private_tags must contain 2-6 strings")
    normalized = sorted({" ".join(_bounded_text(item, "private tag", 1, 80).casefold().split()) for item in value})
    if len(normalized) != len(value):
        raise ValueError("private_tags must be unique after normalization")
    return normalized


def _hashtags(value: Any, *, maximum: int) -> list[str]:
    if not isinstance(value, list) or len(value) > maximum:
        raise ValueError(f"hashtags must contain at most {maximum} entries")
    normalized = sorted(value)
    if len(set(normalized)) != len(normalized) or any(
        not isinstance(item, str) or not re.fullmatch(r"#[a-z0-9_]{1,48}", item)
        for item in normalized
    ):
        raise ValueError("hashtags must be unique lowercase ASCII tags")
    return normalized


def _claim_ids(value: Any, allowed: set[str]) -> set[str]:
    if not isinstance(value, list) or len(value) > 30 or any(
        not isinstance(item, str) for item in value
    ):
        raise ValueError("claim mappings must be a bounded string list")
    result = set(value)
    if len(result) != len(value) or not result.issubset(allowed):
        raise ValueError("claim mappings contain duplicate or unknown claim IDs")
    return result


def _visual_units(value: Any, allowed_claims: set[str], minimum: int, maximum: int) -> list[dict[str, Any]]:
    if not isinstance(value, list) or not minimum <= len(value) <= maximum:
        raise ValueError(f"visual_units must contain {minimum}-{maximum} units")
    return [_visual_unit(item, allowed_claims) for item in value]


def _visual_unit(value: Any, allowed_claims: set[str]) -> dict[str, Any]:
    if not isinstance(value, Mapping) or set(value) != {"role", "title", "body", "claim_ids"}:
        raise ValueError("visual unit has an invalid closed shape")
    role = value["role"]
    if role not in {"hook", "explanation", "example", "takeaway"}:
        raise ValueError("visual unit role is invalid")
    return {
        "role": role,
        "title": _bounded_text(value["title"], "visual title", 1, 120),
        "body": _bounded_text(value["body"], "visual body", 1, 600),
        "claim_ids": sorted(_claim_ids(value["claim_ids"], allowed_claims)),
    }


def _adaptation_prompt(request_value: dict[str, Any]) -> str:
    from .prompt_policy import compose
    return compose("""Write Instagram slide copy and metadata from the supplied canonical
content. Canonical claims and qualifications are authoritative; create no new factual
claims or teaching meaning. The caller already selected the visual structure.
content_contract is the sole resolved slide capacity and semantic sequence policy.
Follow its planned count or bounded role range exactly.
Do not reconcile other capacity policies, choose a design, or write image prompts.
Hero and dialogue positions must include the target expression when required.
Section labels belong to local chrome: titles must add lesson-specific information.
Map every canonical claim into slide claim_ids and/or public_text_claim_ids.
Keep uncertainty visible at the point of use. Check dialogue speaker logic and
that examples actually illustrate the taught meaning before returning.
visual_cues may be empty; otherwise each references a claim already on that slide,
with bounded semantic_emphasis and participants_count. They never contain style prompts.

caption_summary <=1100 characters; complete caption (canonical hook, summary,
optional CTA, hashtags joined with blank lines) <=1500. CTA null or <=12 words/120
characters. 2–6 unique private tags, <=80 characters each. At most 8 unique lowercase
ASCII hashtags matching #[a-z0-9_]{1,48}. Alt text <=1000 characters.
Do not remove meaning to fit: fail visibly if the content contract cannot hold it.
""", request_value, domain=request_value['pipeline_id'], label='FROZEN_OUTPUT')


def _metadata_retry_prompt(request_value: dict[str, Any]) -> str:
    from .prompt_policy import compose
    return compose("""Write only private_tags, hashtags and alt_text for the supplied
already-validated Instagram body. Do not rewrite body copy or invent factual claims.
Use 2–6 unique private tags (80 characters each), at most 8 unique lowercase ASCII
hashtags matching #[a-z0-9_]{1,48}, and alt text of at most 1000 characters.
""", {'body': request_value['checkpointed_adapted_body']}, label='FROZEN_OUTPUT')
