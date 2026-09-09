"""Small polling workers for each persisted v2 boundary.

The default policies are deliberately deterministic placeholders.  They make
the complete lineage demonstrable without pretending that Gemini credentials,
model prices, renderer profiles, or publication access have been approved.
"""

from __future__ import annotations

from hashlib import sha256
from pathlib import Path
from typing import Any
import json
from functools import wraps

from .store import WORKFLOW_PIPELINES, WorkflowStore


def local_operation(table: str, key: str):
    """Persist an explicit local failure; never retry an unknown external call."""
    def decorate(function):
        @wraps(function)
        def execute(self, row):
            try:
                return function(self, row)
            except Exception as error:
                # Exception bodies may contain operator text or secrets.
                reason = "input_too_large" if isinstance(error, ValueError) and str(error).startswith("input_too_large:") else f"local operation failed ({type(error).__name__})"
                try:
                    self.store.fail_claim(table, key, row, reason)
                except RuntimeError:
                    # A stale owner must neither finalize nor overwrite its successor.
                    pass
                return None
        return execute
    return decorate


class IdeaIntakeWorker:
    def __init__(self, store: WorkflowStore, *, instance_id: str = "intake-placeholder"):
        self.store, self.instance_id = store, instance_id

    def run_once(self) -> int | None:
        request = self.store.claim("intake_requests", "intake_request_id", self.instance_id)
        if request is None:
            return None
        return self._process(request)

    @local_operation("intake_requests", "intake_request_id")
    def _process(self, request):
        context = json.loads(request["context_json"])
        if context.get("kind") == "human_conversation":
            snapshot = self.store.conversation_snapshot(
                int(request["thread_id"]), context.get("last_message_id") or context.get("message_id")
            )
            messages = [item for item in snapshot["messages"] if item["author_kind"] == "human"]
            text = " ".join(item["body"] for item in messages).strip()
            if len(text) < 8:
                self.store.clarify_intake(request, "What topic and outcome would you like this content to address?")
                return None
            previous = self.store.connection.execute(
                "SELECT brief_json FROM brief_revisions WHERE thread_id=? ORDER BY revision_number DESC LIMIT 1",
                (request["thread_id"],),
            ).fetchone()
            if previous is None:
                topic = text[:240]
                brief = {
                    "editorial_goal": f"Explain {topic} accurately and usefully.", "topic": topic,
                    "coverage_kind": "editorial_topic", "canonical_target": topic,
                    "revision_scope": "whole_brief", "audience": "general audience",
                    "desired_outcome": "inform", "constraints": {},
                    "source_context": f"Placeholder Intake summary for {topic}.", "open_questions": [],
                }
            else:
                prior = json.loads(previous["brief_json"])
                refinement = messages[-1]["body"]
                constraints = dict(prior.get("constraints", {}))
                changes = list(constraints.get("requested_changes", []))
                changes.append(refinement)
                constraints["requested_changes"] = changes
                brief = {
                    **prior,
                    "revision_scope": "whole_brief",
                    "constraints": constraints,
                    "source_context": f"Refinement requested: {refinement}",
                    "open_questions": [],
                }
        else:
            candidate = self.store.trend_snapshot(request)["topic_snapshot"]
            topic = candidate["canonical_subject"]
            brief = {
                "editorial_goal": f"Explain {topic} accurately and usefully.", "topic": topic,
                "coverage_kind": "editorial_topic", "canonical_target": topic,
                "revision_scope": "whole_brief", "audience": "general audience",
                "desired_outcome": "inform", "constraints": {},
                "source_context": f"Placeholder Intake summary for {topic}.", "open_questions": [],
            }
        return self.store.complete_intake(request, brief, actor_message="A route-neutral brief was frozen by the local placeholder policy.")


class DeterminationWorker:
    def __init__(self, store: WorkflowStore, *, instance_id: str = "determination-placeholder"):
        self.store, self.instance_id = store, instance_id

    def run_once(self) -> int | None:
        request = self.store.claim("determination_requests", "determination_request_id", self.instance_id)
        if request is None:
            return None
        return self._process(request)

    @local_operation("determination_requests", "determination_request_id")
    def _process(self, request):
        snapshot = json.loads(request["input_snapshot_json"]); catalog = snapshot["catalog"]
        routes: list[dict[str, Any]] = []
        selected = False
        for pipeline in WORKFLOW_PIPELINES:
            capability = next((item for item in catalog if item["pipeline_id"] == pipeline), None)
            outputs = [] if capability is None else [item for item in capability["outputs"] if item["ready"]]
            if capability is None or not capability["enabled"]:
                routes.append({"pipeline_id": pipeline, "disposition": "skipped", "fit": "not_evaluated", "reason": "Domain is disabled or not registered in the frozen catalog.", "angle": None, "outputs": []}); continue
            if not capability["generation_ready"] or not outputs:
                routes.append({"pipeline_id": pipeline, "disposition": "blocked", "fit": "credible_placeholder", "reason": "The configured placeholder has no ready generation/output binding.", "angle": {"angle_kind":"placeholder","canonical_target":snapshot["brief"]["canonical_target"],"audience":snapshot["brief"]["audience"],"thesis":snapshot["brief"]["editorial_goal"],"reader_value":snapshot["brief"]["desired_outcome"],"evidence_reference_ids":[]}, "outputs": []}); continue
            # Placeholder policy selects exactly one ready domain; real Gemini routing
            # replaces this after priced model configuration and fixture approval.
            if selected:
                routes.append({"pipeline_id": pipeline, "disposition": "skipped", "fit": "not_selected", "reason": "Placeholder policy limits this fixture run to one domain.", "angle": None, "outputs": []}); continue
            angle={"angle_kind":"explain","canonical_target":snapshot["brief"]["canonical_target"],"audience":snapshot["brief"]["audience"],"thesis":snapshot["brief"]["editorial_goal"],"reader_value":snapshot["brief"]["desired_outcome"],"evidence_reference_ids":[]}
            routes.append({"pipeline_id": pipeline, "disposition": "selected", "fit": "placeholder_ready", "reason": "Ready operator fixture selected by deterministic placeholder routing.", "angle": angle, "outputs": outputs}); selected=True
        outcome = "accepted" if selected else ("blocked" if any(route["disposition"] == "blocked" for route in routes) else "not_recommended")
        return self.store.record_decision(request, {"outcome": outcome, "opportunity_value": "placeholder assessment", "rationale": "No Gemini call was made; this is an explicit local placeholder decision.", "warnings": ["Gemini routing is disabled until model pricing and reviewed fixtures are activated."], "catalog": catalog, "routes": routes})


class PipelineRunner:
    def __init__(self, store: WorkflowStore, *, instance_id: str = "pipeline-placeholder"):
        self.store, self.instance_id = store, instance_id

    def run_once(self) -> int | None:
        run = self.store.claim("generation_runs", "generation_run_id", self.instance_id)
        if run is None: return None
        return self._process(run)

    @local_operation("generation_runs", "generation_run_id")
    def _process(self, run):
        job = self.store.connection.execute("SELECT recipe_json FROM content_jobs WHERE content_job_id=?", (run["content_job_id"],)).fetchone()
        recipe=json.loads(job[0]); brief=recipe["brief"]
        canonical={"schema_version":"canonical_content_v1","hook":brief["topic"],"context":brief["source_context"],"key_points":[recipe["angle"]["thesis"]],"examples":[],"takeaway":brief["desired_outcome"],"claims":[],"pipeline_id":recipe["pipeline_id"],"domain_payload":{"placeholder":True}}
        return self.store.create_canonical(run, canonical)


class AdaptationWorker:
    def __init__(self, store: WorkflowStore, *, instance_id: str = "adaptation-placeholder"):
        self.store, self.instance_id = store, instance_id

    def run_once(self) -> int | None:
        run=self.store.claim("adaptation_runs","adaptation_run_id",self.instance_id)
        if run is None: return None
        return self._process(run)

    @local_operation("adaptation_runs", "adaptation_run_id")
    def _process(self, run):
        output=self.store.connection.execute("SELECT o.*,c.canonical_json FROM output_requests o JOIN canonical_contents c ON c.canonical_content_id=o.canonical_content_id WHERE o.output_request_id=?",(run["output_request_id"],)).fetchone()
        content=json.loads(output["canonical_json"])
        package={"platform":output["platform"],"account":output["account"],"format":output["content_format"],"caption":content["hook"],"hashtags":[],"alt_text":content["context"],"claim_mappings":[],"visual_spec":{"profile":"placeholder_static_v1","cards":[{"text":content["hook"]}]},"placeholder":True}
        return self.store.create_package(run,package)


class VisualRenderer:
    def __init__(self, store: WorkflowStore, artifact_root: str | Path, *, instance_id: str = "renderer-placeholder"):
        self.store,self.artifact_root,self.instance_id=store,Path(artifact_root),instance_id

    def run_once(self) -> int | None:
        run=self.store.claim("render_runs","render_run_id",self.instance_id)
        if run is None:return None
        return self._process(run)

    @local_operation("render_runs", "render_run_id")
    def _process(self, run):
        package=self.store.connection.execute("SELECT package_json FROM content_packages WHERE content_package_id=?",(run["content_package_id"],)).fetchone()
        body=json.loads(package[0]); destination=self.artifact_root / f"render-{run['render_run_id']}"
        destination = destination.resolve()
        destination.mkdir(parents=True,exist_ok=False); path=destination / "preview.html"
        safe=body["caption"].replace("&","&amp;").replace("<","&lt;").replace(">","&gt;")
        path.write_text(f"<!doctype html><meta charset='utf-8'><main>{safe}</main>",encoding="utf-8")
        data=path.read_bytes(); asset={"role":"preview_html","path":str(path),"mime":"text/html","width":1,"height":1,"bytes":len(data),"sha256":sha256(data).hexdigest()}
        manifest={"renderer":"placeholder_static_v1","assets":[asset],"package_placeholder":True}
        return self.store.complete_render(run,manifest,asset)


class PostingAgent:
    """Safety placeholder: never issues an external request."""
    def __init__(self, store: WorkflowStore, *, instance_id: str = "posting-disabled"):
        self.store,self.instance_id=store,instance_id

    def run_once(self) -> int | None:
        run=self.store.claim("post_records","post_record_id",self.instance_id)
        if run is None:return None
        self.store.fail_claim("post_records","post_record_id",run,"delivery adapter is intentionally disabled pending provider verification")
        return int(run["post_record_id"])
