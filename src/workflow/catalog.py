"""Read the frozen-routing catalog without invoking another worker."""
from common.timestamps import utc_now
from typing import Any
import json

WORKFLOW_PIPELINES = ("english", "ai_tech", "psychology")


DOMAIN_REMITS = {
    "english": "Teach usable English expressions, vocabulary and pragmatic context to language learners; popularity alone is not a teaching angle.",
    "ai_tech": "Explain AI tools, capabilities, limitations and practical use cases with evidence.",
    "psychology": "Explain evidence-grounded behavior and communication; do not invent diagnoses.",
}

def read_catalog(connection, kind="fixture") -> list[dict[str, Any]]:
    pipeline_version = (
        "domain_pipeline_catalog_production_v1"
        if kind == "production"
        else "domain_pipeline_catalog_v1"
    )
    fields = (
        "SELECT c.*, b.output_binding_id,b.platform,b.account,b.content_format,"
        "b.output_contract_version,b.ready,b.safe_reason"
    )
    if kind == "production":
        fields += (
            ",b.delivery_enabled,b.visual_configuration_approved,d.enabled destination_enabled,"
            "d.destination_key,r.status readiness_status,r.valid_until readiness_valid_until"
        )
    rows = connection.execute(
        fields + " FROM pipeline_capabilities c "
        "JOIN configuration_activations a ON a.configuration_release_id=c.configuration_release_id "
        "AND a.scope_key='global' AND a.status='active' "
        "LEFT JOIN output_bindings b ON b.pipeline_capability_id=c.pipeline_capability_id "
        + (
            "LEFT JOIN social_destinations d ON d.social_destination_id=b.social_destination_id "
            "LEFT JOIN capability_readiness r ON r.social_destination_id=d.social_destination_id "
            if kind == "production" else ""
        )
        + "WHERE c.pipeline_version=? ORDER BY c.pipeline_capability_id,b.output_binding_id",
        (pipeline_version,),
    ).fetchall()
    by_pipeline: dict[str, dict[str, Any]] = {}
    for row in rows:
        item = by_pipeline.setdefault(row["pipeline_id"], {"pipeline_id": row["pipeline_id"], "enabled": bool(row["enabled"]), "generation_ready": bool(row["generation_ready"]), "outputs": [], "remit": json.loads(row["remit_json"])})
        if row["output_binding_id"] is not None:
            output = {key: row[key] for key in ("output_binding_id","platform","account","content_format","output_contract_version","ready","safe_reason")}
            if kind == "production":
                ready = (
                    bool(row["ready"])
                    and bool(row["delivery_enabled"])
                    and bool(row["visual_configuration_approved"])
                    and bool(row["destination_enabled"])
                    and row["readiness_status"] == "ready"
                    and isinstance(row["readiness_valid_until"], str)
                    and row["readiness_valid_until"] > utc_now()
                )
                output["ready"] = ready
                if not ready:
                    output["safe_reason"] = (
                        "production output blocked: visual configuration approval or provider readiness is not current"
                    )
            else:
                output["ready"] = bool(output["ready"])
            item["outputs"].append(output)
    return [by_pipeline[key] for key in WORKFLOW_PIPELINES if key in by_pipeline]
