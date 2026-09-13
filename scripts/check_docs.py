"""Consistency checks for the Content Factory documentation model."""

from pathlib import Path
import json
import re
from urllib.parse import unquote


ROOT = Path(__file__).resolve().parents[1]
REQUIRED = [
    ROOT / "AGENTS.md",
    ROOT / "docs" / "system.md",
    ROOT / "docs" / "current-state.md",
    ROOT / "docs" / "specs" / "detection.md",
    ROOT / "docs" / "specs" / "idea-intake-and-determination.md",
    ROOT / "docs" / "specs" / "visual-rendering.md",
    ROOT / "docs" / "specs" / "posting.md",
    ROOT / "docs" / "specs" / "data-model.md",
    ROOT / "docs" / "specs" / "data" / "records.md",
    ROOT / "docs" / "specs" / "configuration.md",
    ROOT / "docs" / "specs" / "dashboard.md",
    ROOT / "docs" / "specs" / "runtime.md",
    ROOT / "docs" / "specs" / "reliability.md",
    ROOT / "docs" / "pipelines" / "o2-english-instagram.md",
    ROOT / "docs" / "pipelines" / "domains.md",
    ROOT / "docs" / "specs" / "content-production.md",
    ROOT / "docs" / "specs" / "platform-outputs.md",
    ROOT / "docs" / "platforms" / "meta.md",
    ROOT / "docs" / "platforms" / "x.md",
    ROOT / "docs" / "contracts" / "README.md",
    ROOT / "docs" / "contracts" / "maturity.md",
    ROOT / "docs" / "contracts" / "detection-dashboard-schema-v1.sql",
    ROOT / "docs" / "contracts" / "editorial-workflow-schema-v2.sql",
    ROOT / "docs" / "contracts" / "detection-safety-schema-v3.sql",
    ROOT / "docs" / "contracts" / "production-workflow-schema-v4.sql",
    ROOT / "docs" / "contracts" / "configuration-manifest-v2.schema.json",
    ROOT / "docs" / "contracts" / "configuration-manifest-v3.schema.json",
    ROOT / "config" / "releases" / "detection-normalized-v3.json",
    ROOT / "config" / "releases" / "detection-hybrid-v2.json",
    ROOT / "docs" / "profiles" / "editorial-clean-v1.md",
    ROOT / "docs" / "plans" / "target-implementation.md",
    ROOT / "config" / "releases" / "detection-dashboard-v1.json",
    ROOT / "docs" / "archive" / "decisions.md",
    ROOT / ".env.example",
    ROOT / "scripts" / "check_smoke_readiness.py",
    ROOT / "src" / "workflow" / "preflight.py",
]
TIER_TWO_CONTRACTS = [
    ROOT / "docs" / "specs" / "detection.md",
    ROOT / "docs" / "specs" / "idea-intake-and-determination.md",
    ROOT / "docs" / "specs" / "visual-rendering.md",
    ROOT / "docs" / "specs" / "posting.md",
    ROOT / "docs" / "specs" / "data-model.md",
    ROOT / "docs" / "specs" / "data" / "records.md",
    ROOT / "docs" / "specs" / "configuration.md",
    ROOT / "docs" / "specs" / "dashboard.md",
    ROOT / "docs" / "specs" / "runtime.md",
    ROOT / "docs" / "specs" / "reliability.md",
    ROOT / "docs" / "pipelines" / "o2-english-instagram.md",
    ROOT / "docs" / "pipelines" / "domains.md",
    ROOT / "docs" / "specs" / "content-production.md",
    ROOT / "docs" / "specs" / "platform-outputs.md",
    ROOT / "docs" / "platforms" / "meta.md",
    ROOT / "docs" / "platforms" / "x.md",
]
DOCUMENTS = [ROOT / "README.md", ROOT / "audit_report.md", *sorted((ROOT / "docs").rglob("*.md"))]
LOCAL_LINK = re.compile(r"(?<!!)\[[^\]]*\]\(([^)\s]+)(?:\s+\"[^\"]*\")?\)")
HEADING = re.compile(r"^(#{1,6})\s+(.+?)\s*$")
DATA_MODEL_REQUIRED_HEADINGS = (
    "## Identity boundaries",
    "## Target record inventory and transition rules",
    "### Column, foreign-key, and retention catalog",
    "### Claimable-record transition matrix",
)
CANONICAL_RECORDS = (
    "detection_source_instances",
    "trend_candidates",
    "content_threads",
    "intake_requests",
    "brief_revisions",
    "determination_requests",
    "determination_decisions",
    "determination_routes",
    "content_jobs",
    "generation_runs",
    "canonical_contents",
    "output_requests",
    "adaptation_runs",
    "output_bindings",
    "social_destinations",
    "domain_angle_reservations",
    "canonical_reuse_links",
    "content_packages",
    "render_runs",
    "review_requests",
    "post_requests",
    "post_records",
    "post_attempts",
    "reconciliation_requests",
    "model_invocations",
)
PHASE_ONE_DOMAINS = frozenset({
    "english", "ai_tools", "personal_finance", "business_side_hustle",
    "psychology_behavior",
})
SUPERSEDED_SCHEMA_IDS = frozenset({
    "content_factory/brief_v1",
    "content_factory/determination_result_v1",
    "content_factory/recipe_v1",
    "content_factory/o2_creative_v1",
    "content_factory/visual_spec_v1",
})
REQUIRED_SCHEMA_IDS = (
    "content_factory/brief_v1",
    "content_factory/determination_result_v1",
    "content_factory/recipe_v1",
    "content_factory/visual_spec_v1",
    "content_factory/render_manifest_v1",
    "content_factory/provider_attempt_v1",
    "content_factory/configuration_manifest_v1",
    "content_factory/configuration_manifest_v2",
    "content_factory/configuration_manifest_v3",
    "content_factory/o2_creative_v1",
)
DETECTION_DASHBOARD_TABLES = (
    "schema_migrations",
    "configuration_releases",
    "configuration_activations",
    "detection_source_instances",
    "detection_cluster_aliases",
    "source_collection_attempts",
    "source_request_executions",
    "source_health",
    "trends",
    "trend_observations",
    "source_item_events",
    "scout_evaluation_runs",
    "scout_evaluation_inputs",
    "scout_evaluation_attempts",
    "topic_snapshots",
    "trend_candidates",
    "candidate_observation_memberships",
    "content_threads",
    "intake_requests",
    "thread_evidence_events",
    "worker_heartbeats",
    "worker_runs",
)
PRODUCTION_WORKFLOW_TABLES = (
    "social_destinations",
    "production_configurations",
    "posting_policies",
    "capability_readiness",
    "capability_readiness_checks",
    "post_attempts",
    "publication_resources",
    "delivery_cleanup_tasks",
    "reconciliation_requests",
    "reconciliation_checks",
    "human_reconciliation_decisions",
    "storage_samples",
    "maintenance_runs",
    "artifact_reconciliations",
)


def check_local_links(errors: list[str]) -> None:
    """Require local Markdown links to resolve inside the repository."""
    for document in DOCUMENTS:
        if not document.is_file():
            continue
        for target in LOCAL_LINK.findall(document.read_text(encoding="utf-8")):
            target = unquote(target)
            path_part = target.split("#", maxsplit=1)[0].split("?", maxsplit=1)[0]
            if not path_part or "://" in path_part or path_part.startswith(("mailto:", "tel:")):
                continue
            linked_path = (document.parent / path_part).resolve()
            try:
                linked_path.relative_to(ROOT.resolve())
            except ValueError:
                errors.append(
                    f"{document.relative_to(ROOT)} links outside the repository: {target}"
                )
                continue
            if not linked_path.is_file():
                errors.append(
                    f"{document.relative_to(ROOT)} has a missing local link: {target}"
                )


def anchor_for(heading: str) -> str:
    """Match GitHub-style anchors closely enough for local contract links."""
    return re.sub(r"[^a-z0-9 _-]", "", heading.lower()).replace(" ", "-")


def check_structure(errors: list[str]) -> None:
    """Reject empty headings and local anchor references that cannot resolve."""
    anchors: dict[Path, set[str]] = {}
    for document in DOCUMENTS:
        if not document.is_file():
            continue
        lines = document.read_text(encoding="utf-8").splitlines()
        document_anchors = set()
        for line in lines:
            match = HEADING.match(line)
            if match:
                document_anchors.add(anchor_for(match.group(2)))
        anchors[document.resolve()] = document_anchors
        for index, line in enumerate(lines):
            match = HEADING.match(line)
            if not match:
                continue
            next_nonempty = next((value for value in lines[index + 1:] if value.strip()), "")
            next_heading = HEADING.match(next_nonempty)
            if next_heading and len(next_heading.group(1)) == len(match.group(1)):
                errors.append(f"{document.relative_to(ROOT)} has an empty heading: {line}")
    for document in DOCUMENTS:
        if not document.is_file():
            continue
        for target in LOCAL_LINK.findall(document.read_text(encoding="utf-8")):
            if "#" not in target or "://" in target:
                continue
            path_part, anchor = target.split("#", maxsplit=1)
            target_path = (document.parent / path_part).resolve() if path_part else document.resolve()
            if target_path in anchors and anchor not in anchors[target_path]:
                errors.append(f"{document.relative_to(ROOT)} has a missing local anchor: {target}")


def check_phase_one_contracts(errors: list[str]) -> None:
    """Guard stable domain identity and explicitly retired payloads.

    These are structural checks, not proof of architectural or provider readiness.
    """
    catalog = ROOT / "docs" / "pipelines" / "domains.md"
    if catalog.is_file():
        domain_rows = re.findall(
            r"^\| `([a-z0-9_]+)` \|", catalog.read_text(encoding="utf-8"), re.MULTILINE
        )
        if set(domain_rows) != PHASE_ONE_DOMAINS or len(domain_rows) != 5:
            errors.append("docs/pipelines/domains.md must catalog exactly the five Phase 1 domains")
    for path in (ROOT / "AGENTS.md", ROOT / "docs" / "system.md"):
        if not path.is_file():
            continue
        text = path.read_text(encoding="utf-8")
        for domain in sorted(PHASE_ONE_DOMAINS):
            if f"`{domain}`" not in text:
                errors.append(f"{path.relative_to(ROOT)} does not name domain `{domain}`")
        if "Pipelines are platform- and format-specific" in text:
            errors.append(f"{path.relative_to(ROOT)} still declares platform-specific pipelines")
    for path in sorted((ROOT / "docs" / "contracts").glob("*.schema.json")):
        try:
            parsed = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            continue  # The general schema check reports syntax failures.
        if parsed.get("$id") not in SUPERSEDED_SCHEMA_IDS:
            continue
        if parsed.get("x-maturity") != "superseded":
            errors.append(f"{path.relative_to(ROOT)} must mark its old draft x-maturity as superseded")
        replacement = parsed.get("x-replacement-owner")
        if not isinstance(replacement, str) or not (ROOT / replacement).is_file():
            errors.append(f"{path.relative_to(ROOT)} must route an existing x-replacement-owner")


def main() -> None:
    errors = [f"Missing required documentation: {path.relative_to(ROOT)}" for path in REQUIRED if not path.is_file()]
    system = ROOT / "docs" / "system.md"
    if system.is_file():
        text = system.read_text(encoding="utf-8")
        for heading in (
            "## Current Objective",
            "## Components, Inputs, and Persisted Outputs",
            "## Document Router",
            "## Local Operation and Verification",
        ):
            if heading not in text:
                errors.append(f"docs/system.md is missing {heading!r}")
        for contract in TIER_TWO_CONTRACTS:
            relative_path = contract.relative_to(ROOT / "docs").as_posix()
            if relative_path not in text:
                errors.append(f"docs/system.md does not route docs/{relative_path}")
    for contract in TIER_TWO_CONTRACTS:
        if contract.is_file() and "**Document role:** Tier 2" not in contract.read_text(encoding="utf-8"):
            errors.append(f"{contract.relative_to(ROOT)} is missing its Tier 2 document role")
    data_model = ROOT / "docs" / "specs" / "data-model.md"
    if data_model.is_file():
        data_model_text = data_model.read_text(encoding="utf-8")
        for heading in DATA_MODEL_REQUIRED_HEADINGS:
            if heading not in data_model_text:
                errors.append(f"docs/specs/data-model.md is missing {heading!r}")
        for record in CANONICAL_RECORDS:
            if f"`{record}`" not in data_model_text:
                errors.append(f"docs/specs/data-model.md does not catalog `{record}`")
    check_local_links(errors)
    check_structure(errors)
    check_phase_one_contracts(errors)
    maturity = ROOT / "docs" / "contracts" / "maturity.md"
    if maturity.is_file():
        maturity_text = maturity.read_text(encoding="utf-8")
        for contract in TIER_TWO_CONTRACTS:
            registry_path = contract.relative_to(ROOT / "docs").as_posix()
            if f"`{registry_path}`" not in maturity_text:
                errors.append(f"docs/contracts/maturity.md does not register `{registry_path}`")
        for marker in ("**Registry version:**", "**Last architectural review:**", "**Normative terms:**"):
            if marker not in maturity_text:
                errors.append(f"docs/contracts/maturity.md is missing {marker}")
    schemas = sorted((ROOT / "docs" / "contracts").glob("*.schema.json"))
    schema_ids = set()
    for schema in schemas:
        try:
            parsed = json.loads(schema.read_text(encoding="utf-8"))
        except json.JSONDecodeError as error:
            errors.append(f"{schema.relative_to(ROOT)} is not valid JSON: {error.msg}")
            continue
        if parsed.get("$schema") != "https://json-schema.org/draft/2020-12/schema":
            errors.append(f"{schema.relative_to(ROOT)} does not declare JSON Schema Draft 2020-12")
        schema_id = parsed.get("$id")
        if not isinstance(schema_id, str):
            errors.append(f"{schema.relative_to(ROOT)} has no string $id")
        elif schema_id in schema_ids:
            errors.append(f"duplicate contract schema ID: {schema_id}")
        else:
            schema_ids.add(schema_id)
        owner = parsed.get("x-owner")
        if isinstance(owner, str) and not (ROOT / owner).is_file():
            errors.append(f"{schema.relative_to(ROOT)} has a missing x-owner: {owner}")
    for schema_id in REQUIRED_SCHEMA_IDS:
        if schema_id not in schema_ids:
            errors.append(f"missing required contract schema ID: {schema_id}")
    sql_contract = ROOT / "docs" / "contracts" / "detection-dashboard-schema-v1.sql"
    if sql_contract.is_file():
        sql_text = sql_contract.read_text(encoding="utf-8")
        for table in DETECTION_DASHBOARD_TABLES:
            if f"CREATE TABLE {table} (" not in sql_text:
                errors.append(f"detection dashboard SQL contract is missing table `{table}`")
        if "PRAGMA user_version = 1;" not in sql_text:
            errors.append("detection dashboard SQL contract does not set user_version 1")
    production_contract = ROOT / "docs" / "contracts" / "production-workflow-schema-v4.sql"
    if production_contract.is_file():
        sql_text = production_contract.read_text(encoding="utf-8")
        for table in PRODUCTION_WORKFLOW_TABLES:
            if f"CREATE TABLE {table} (" not in sql_text:
                errors.append(f"production workflow SQL contract is missing table `{table}`")
        if "PRAGMA user_version = 4;" not in sql_text:
            errors.append("production workflow SQL contract does not set user_version 4")
    manifest = ROOT / "config" / "releases" / "detection-dashboard-v1.json"
    if manifest.is_file():
        try:
            manifest_data = json.loads(manifest.read_text(encoding="utf-8"))
        except json.JSONDecodeError as error:
            errors.append(f"{manifest.relative_to(ROOT)} is not valid JSON: {error.msg}")
        else:
            if manifest_data.get("schema_id") != "configuration_manifest_v1":
                errors.append("detection dashboard manifest has the wrong schema_id")
            sources = manifest_data.get("components", {}).get("detection", {}).get("sources", [])
            source_ids = [source.get("stable_id") for source in sources if isinstance(source, dict)]
            if len(source_ids) != len(set(source_ids)):
                errors.append("detection dashboard manifest has duplicate source stable IDs")
            detection_text = (ROOT / "docs" / "specs" / "detection.md").read_text(encoding="utf-8")
            for source_id in source_ids:
                if not isinstance(source_id, str) or f"`{source_id}`" not in detection_text:
                    errors.append(f"detection dashboard manifest source is not documented: {source_id!r}")
    for path in (ROOT / "README.md", ROOT / "docs" / "system.md"):
        if path.is_file() and "daily_expression" in path.read_text(encoding="utf-8"):
            errors.append(f"Removed reference project is still mentioned in {path.relative_to(ROOT)}")
    if errors:
        print("Documentation check failed:")
        print("\n".join(f"- {error}" for error in errors))
        raise SystemExit(1)
    print("Documentation check passed.")


if __name__ == "__main__":
    main()
