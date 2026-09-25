"""Gemini-backed three-domain Determination worker for the workflow."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any
import json
from copy import deepcopy

from .model_trace import generate_json
from common.gemini import VertexGeminiClient, configured_model

from .store import WORKFLOW_PIPELINES, WorkflowStore
from .workers import local_operation
from .planning_context import model_context


DETERMINATION_PROMPT_VERSION = "workflow_gemini_determination_prompt_v5"
DETERMINATION_SCHEMA_VERSION = "workflow_gemini_determination_result_v2"
OUTPUT_FIELDS = (
    "output_binding_id", "platform", "account", "content_format",
    "output_contract_version", "ready", "safe_reason",
)

_OUTPUT_SCHEMA = {
    "type": "object",
    "required": list(OUTPUT_FIELDS),
    "additionalProperties": False,
    "properties": {
        "output_binding_id": {"type": "integer"},
        "platform": {"type": "string", "enum": ["instagram"]},
        "account": {"type": "string"},
        "content_format": {"type": "string"},
        "output_contract_version": {"type": "string"},
        "ready": {"type": "boolean"},
        "safe_reason": {"type": "string"},
    },
}
DETERMINATION_SCHEMA: dict[str, Any] = {
    "type": "object",
    "required": ["outcome", "opportunity_value", "rationale", "warnings", "routes"],
    "additionalProperties": False,
    "properties": {
        "outcome": {
            "type": "string",
            "enum": ["accepted", "not_recommended", "blocked"],
        },
        "opportunity_value": {"type": "string"},
        "rationale": {"type": "string"},
        "warnings": {"type": "array", "items": {"type": "string"}},
        "routes": {
            "type": "array",
            "minItems": 3,
            "maxItems": 3,
            "items": {
                "type": "object",
                "required": ["pipeline_id", "disposition", "fit", "reason", "outputs"],
                "additionalProperties": False,
                "properties": {
                    "pipeline_id": {"type": "string", "enum": list(WORKFLOW_PIPELINES)},
                    "disposition": {
                        "type": "string",
                        "enum": ["selected", "skipped", "blocked"],
                    },
                    "fit": {"type": "string"},
                    "reason": {"type": "string"},
                    "outputs": {"type": "array", "items": _OUTPUT_SCHEMA},
                },
            },
        },
    },
}


def determination_schema(catalog):
    schema = deepcopy(DETERMINATION_SCHEMA)
    routes = schema['properties']['routes']
    routes.update(minItems=len(catalog), maxItems=len(catalog))
    routes['items']['properties']['pipeline_id']['enum'] = [d['pipeline_id'] for d in catalog]
    return schema


class GeminiDeterminationWorker:
    """Evaluate every domain and persist only a validated complete decision."""

    def __init__(
        self,
        store: WorkflowStore,
        client: Any | None = None,
        *,
        instance_id: str = "determination-gemini",
    ):
        self.store = store
        maximum = None if store.model_budget_policy is None else store.model_budget_policy.phase_limits["determination"][1]
        self.client = client or VertexGeminiClient(
            max_output_tokens=maximum,
            thinking_level="LOW" if configured_model().startswith("gemini-3") else None,
        )
        self.instance_id = instance_id

    def run_once(self) -> int | None:
        request = self.store.claim(
            "determination_requests", "determination_request_id", self.instance_id
        )
        if request is None:
            return None
        return self._process(request)

    @local_operation("determination_requests", "determination_request_id")
    def _process(self, request: Any) -> int | None:
        snapshot = json.loads(request["input_snapshot_json"])
        if not isinstance(snapshot, dict) or not all(
            key in snapshot for key in ("brief", "source_context", "catalog")
        ):
            raise ValueError("Determination request has an incomplete frozen input snapshot")
        model_input = model_context(snapshot)
        invocation_id = self.store.begin_model_invocation(
            phase="determination",
            table="determination_requests",
            key="determination_request_id",
            row=request,
            request_version=str(snapshot.get("routing_policy_version", "determination_policy_v3")),
            prompt_version=DETERMINATION_PROMPT_VERSION,
            schema_version=DETERMINATION_SCHEMA_VERSION,
            request_value=model_input,
            model_id=str(getattr(self.client, "model", "gemini")),
        )
        try:
            response = generate_json(self.store, invocation_id, self.client,
                _determination_prompt(model_input), determination_schema(snapshot['catalog']), temperature=0.2
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
            decision = _validate_decision(response, snapshot["catalog"], snapshot["brief"])
        except Exception as error:
            self.store.finish_model_invocation(
                invocation_id,
                outcome="schema_failed",
                usage=getattr(self.client, "last_usage", None),
                response_value=response,
                error=str(error),
            )
            raise

        self.store.finish_model_invocation(
            invocation_id,
            outcome="succeeded",
            usage=getattr(self.client, "last_usage", None),
            response_value=response,
        )
        decision["catalog"] = snapshot["catalog"]
        return self.store.record_decision(request, decision)


def _validate_decision(value: Any, catalog: Any, brief=None) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise ValueError("Gemini Determination response must be an object")
    if not isinstance(catalog, list):
        raise ValueError("frozen capability catalog must be a list")
    for field in ("outcome", "opportunity_value", "rationale"):
        if not isinstance(value.get(field), str) or not value[field].strip():
            raise ValueError(f"{field} must be a non-empty string")
    if value["outcome"] not in {"accepted", "not_recommended", "blocked"}:
        raise ValueError("invalid aggregate outcome")
    warnings = value.get("warnings")
    if not isinstance(warnings, list) or any(not isinstance(item, str) for item in warnings):
        raise ValueError("warnings must be a list of strings")
    routes = value.get("routes")
    if not isinstance(routes, list) or len(routes) != len(catalog):
        raise ValueError("determination must return exactly three routes")
    if {route.get("pipeline_id") for route in routes if isinstance(route, Mapping)} != {item["pipeline_id"] for item in catalog}:
        raise ValueError("determination must return one route for every registered domain")

    catalog_by_pipeline = {
        item["pipeline_id"]: item
        for item in catalog
        if isinstance(item, Mapping)
    }
    normalized_routes: list[dict[str, Any]] = []
    selected_count = 0
    blocked_count = 0
    for route in routes:
        if not isinstance(route, Mapping):
            raise ValueError("each determination route must be an object")
        if set(route) != {"pipeline_id", "disposition", "fit", "reason", "outputs"}:
            raise ValueError("invalid closed domain assessment")
        pipeline_id = route["pipeline_id"]
        disposition = route.get("disposition")
        if disposition not in {"selected", "skipped", "blocked"}:
            raise ValueError(f"invalid disposition for {pipeline_id}")
        for field in ("fit", "reason"):
            if not isinstance(route.get(field), str) or not route[field].strip():
                raise ValueError(f"{pipeline_id} route requires a non-empty {field}")
        if disposition == "selected":
            selected_count += 1
        if disposition == "blocked":
            blocked_count += 1

        outputs = route.get("outputs")
        if not isinstance(outputs, list):
            raise ValueError(f"{pipeline_id} outputs must be a list")
        capability = catalog_by_pipeline.get(pipeline_id)
        frozen_outputs = [] if capability is None else capability.get("outputs", [])
        if not isinstance(frozen_outputs, list):
            raise ValueError(f"{pipeline_id} frozen outputs are invalid")
        normalized_outputs = []
        seen_bindings: set[int] = set()
        for output in outputs:
            if not isinstance(output, Mapping):
                raise ValueError(f"{pipeline_id} output reference must be an object")
            candidate = dict(output)
            if any(field not in candidate for field in OUTPUT_FIELDS):
                raise ValueError(f"{pipeline_id} output reference is incomplete")
            if candidate not in frozen_outputs or candidate.get("ready") is not True:
                raise ValueError(f"{pipeline_id} output is not a ready frozen catalog binding")
            binding_id = candidate["output_binding_id"]
            if type(binding_id) is not int or binding_id in seen_bindings:
                raise ValueError(f"{pipeline_id} output bindings must be unique integer references")
            seen_bindings.add(binding_id)
            normalized_outputs.append(candidate)
        if disposition == "selected":
            if (
                capability is None
                or capability.get("enabled") is not True
                or capability.get("generation_ready") is not True
                or not normalized_outputs
            ):
                raise ValueError(f"selected route {pipeline_id} is not ready in the frozen catalog")
            if len({output["platform"] for output in normalized_outputs}) != len(normalized_outputs):
                raise ValueError(f"selected route {pipeline_id} repeats a platform binding")
        normalized_routes.append({
            "pipeline_id": pipeline_id,
            "disposition": disposition,
            "fit": route["fit"].strip(),
            "reason": route["reason"].strip(),
            "outputs": normalized_outputs,
        })

    if value["outcome"] == "accepted" and selected_count == 0:
        raise ValueError("accepted outcome requires at least one selected route")
    if value["outcome"] != "accepted" and selected_count:
        raise ValueError("non-accepted outcome cannot contain selected routes")
    if value["outcome"] == "blocked" and blocked_count == 0:
        raise ValueError("blocked outcome requires at least one blocked route")
    if value["outcome"] == "not_recommended" and blocked_count:
        raise ValueError("not_recommended outcome cannot contain blocked routes")
    if brief is not None:
        from .human_constraints import editorial_scope
        included, excluded = editorial_scope(brief)
        for route in normalized_routes:
            if route['pipeline_id'] in excluded or (included and route['pipeline_id'] not in included):
                route.update(disposition='skipped', outputs=[], fit='Outside requested editorial scope',
                             reason='Human subject treatment and explicit domain constraints take precedence over semantic adjacency.')
        dispositions = {r['disposition'] for r in normalized_routes}
        value = {**value, 'outcome': 'accepted' if 'selected' in dispositions else 'blocked' if 'blocked' in dispositions else 'not_recommended'}
    return {
        "outcome": value["outcome"],
        "opportunity_value": value["opportunity_value"].strip(),
        "rationale": value["rationale"].strip(),
        "warnings": list(warnings),
        "routes": normalized_routes,
    }


def _determination_prompt(snapshot: dict[str, Any]) -> str:
    from .prompt_policy import compose
    value = {key: snapshot[key] for key in ('brief', 'source_context')}
    value['DOMAIN_CATALOG'] = snapshot['catalog']
    return compose("""Decide which supplied subject areas should cover this request.
Evaluate every domain in DOMAIN_CATALOG independently and return one assessment
per entry. A domain is an editorial remit; its outputs are configured destinations.
Select only enabled, generation-ready domains with ready outputs, copying the
selected output objects exactly. Skip weak fits and domains outside explicit human
scope. Route by requested editorial intention, not semantic adjacency. An English
expression lesson is English learning even if its words mention emotions or technology.
Select another domain only for direct reader value in the requested treatment or
explicit intent. A question about why people behave a certain way can fit Psychology.
Explicit included_domains and excluded_domains are authoritative. Selected domains
must each offer distinct reader value. Missing audience or
treatment is not a reason to manufacture intent. Do not choose the treatment,
write content or decide visual presentation; later stages own those decisions.
""", value, label='FROZEN_INPUT')
