"""Read-only, non-network smoke-readiness inspection for the versioned workflow."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from hashlib import sha256
from pathlib import Path
from typing import Any, Callable, Mapping
import json
import os

from database.current import SchemaError, validate_database

from .model_budget import ModelBudgetConfigurationError, ModelBudgetPolicy
from .store import WORKFLOW_PIPELINES, WorkflowStore


def _dependency_probe() -> dict[str, tuple[bool, str]]:
    checks: dict[str, tuple[bool, str]] = {}
    try:
        from google import genai  # noqa: F401
    except ImportError:
        checks["google_genai"] = (False, "google-genai is not installed")
    else:
        checks["google_genai"] = (True, "google-genai is importable")
    try:
        from playwright.sync_api import sync_playwright

        with sync_playwright() as playwright:
            executable = Path(playwright.chromium.executable_path)
            available = executable.is_file()
    except Exception as error:
        checks["playwright_chromium"] = (
            False, f"Playwright Chromium inspection failed ({type(error).__name__})",
        )
    else:
        checks["playwright_chromium"] = (
            available,
            "Playwright Chromium is installed" if available
            else "Playwright Chromium is missing; run playwright install chromium",
        )
    return checks


def _path_writable(path: Path) -> bool:
    candidate = path
    while not candidate.exists() and candidate != candidate.parent:
        candidate = candidate.parent
    return candidate.is_dir() and os.access(candidate, os.W_OK | os.X_OK)


def _file_hash(path: Path) -> str:
    hasher = sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            hasher.update(chunk)
    return hasher.hexdigest()


def inspect_smoke_readiness(
    database: str | Path,
    artifact_root: str | Path,
    backup_root: str | Path | None,
    *,
    mode: str,
    environment: Mapping[str, str] | None = None,
    dependency_probe: Callable[[], dict[str, tuple[bool, str]]] = _dependency_probe,
    at: datetime | None = None,
) -> dict[str, Any]:
    """Return safe preflight facts without calling Gemini or any delivery provider."""
    if mode == "planning":
        return inspect_planning_readiness(database, environment=environment)
    if mode not in {"preview", "production", "delivery"}:
        raise ValueError("smoke readiness mode must be preview, production, or delivery")
    values = os.environ if environment is None else environment
    moment = (at or datetime.now(timezone.utc)).astimezone(timezone.utc).replace(microsecond=0)
    checks: list[dict[str, str]] = []

    def add(check_id: str, status: str, detail: str) -> None:
        checks.append({"check": check_id, "status": status, "detail": detail})

    database_path = Path(database).resolve()
    artifacts = Path(artifact_root).resolve()
    backups = None if backup_root is None else Path(backup_root).resolve()
    store: WorkflowStore | None = None
    try:
        store = WorkflowStore(
            database_path, read_only=True,
            catalog_kind="production" if mode != "preview" else "fixture",
        )
    except (OSError, SchemaError) as error:
        add("database", "blocked", f"versioned database is unavailable ({type(error).__name__})")
    if store is not None:
        try:
            version = int(store.connection.execute("PRAGMA user_version").fetchone()[0])
            add("database_schema", "pass", f"workflow schema version {version} is readable")
            quick = store.connection.execute("PRAGMA quick_check").fetchone()[0]
            add(
                "database_integrity", "pass" if quick == "ok" else "blocked",
                "SQLite quick check passed" if quick == "ok" else "SQLite quick check failed",
            )
            foreign = store.connection.execute("PRAGMA foreign_key_check").fetchone()
            add(
                "database_foreign_keys", "pass" if foreign is None else "blocked",
                "foreign-key check passed" if foreign is None else "foreign-key violations exist",
            )
            if mode != "preview":
                try:
                    validate_database(store.connection)
                except SchemaError as error:
                    add("production_schema", "blocked", str(error))
                else:
                    add("production_schema", "pass", "current application schema is valid")
        except Exception as error:
            add("database_inspection", "blocked", f"database inspection failed ({type(error).__name__})")

    project = str(values.get("GOOGLE_CLOUD_PROJECT", "")).strip()
    add(
        "gemini_project", "pass" if project else "blocked",
        "Vertex project is configured" if project else "GOOGLE_CLOUD_PROJECT is missing",
    )
    model = str(values.get("GEMINI_MODEL") or values.get("VERTEX_AI_MODEL") or "gemini-2.5-flash")
    add("gemini_model", "pass", f"configured model identifier: {model}")
    for check_id, (ready, detail) in dependency_probe().items():
        add(check_id, "pass" if ready else "blocked", detail)
    add(
        "artifact_root", "pass" if _path_writable(artifacts) else "blocked",
        "artifact destination is locally writable" if _path_writable(artifacts)
        else "artifact destination or its nearest existing parent is not writable",
    )

    if mode != "preview":
        if backups is None:
            add("backup_root", "blocked", "backup root is required")
        else:
            writable = _path_writable(backups)
            add(
                "backup_root", "pass" if writable else "blocked",
                "backup destination is locally writable" if writable
                else "backup destination or its nearest existing parent is not writable",
            )
        try:
            policy = ModelBudgetPolicy.from_environment(model, values)
        except (ModelBudgetConfigurationError, TypeError, ValueError) as error:
            add("gemini_budget", "blocked", str(error))
        else:
            add(
                "gemini_budget", "pass",
                f"priced policy {policy.fingerprint[:12]} has finite phase and owner limits",
            )

        if store is not None:
            configuration = store.connection.execute(
                "SELECT pc.configuration_json FROM production_configurations pc "
                "JOIN configuration_activations a "
                "ON a.configuration_release_id=pc.configuration_release_id "
                "AND a.scope_key='global' AND a.status='active'"
            ).fetchone()
            if configuration is None:
                add("production_configuration", "blocked", "active immutable production configuration is missing")
            else:
                add("production_configuration", "pass", "active immutable production configuration exists")
                value = json.loads(configuration["configuration_json"])
                profile = value.get("renderer_profile", {})
                font = Path(str(profile.get("font_path", "")))
                safe_font = False
                try:
                    safe_font = (
                        font.is_absolute() and not font.is_symlink() and font.is_file()
                        and font.stat().st_size <= 20_000_000
                        and _file_hash(font) == profile.get("font_sha256")
                    )
                except OSError:
                    safe_font = False
                add(
                    "production_font", "pass" if safe_font else "blocked",
                    "approved production font fingerprint matches"
                    if safe_font else "approved production font is missing or its fingerprint changed",
                )
                catalog = store.catalog()
                complete = (
                    {item["pipeline_id"] for item in catalog} == set(WORKFLOW_PIPELINES)
                    and all(item["enabled"] and item["generation_ready"] and item["outputs"] for item in catalog)
                )
                add(
                    "production_catalog", "pass" if complete else "blocked",
                    "all five domains have materialized destination bindings"
                    if complete else "the five-domain production catalog is incomplete",
                )

            sample = store.connection.execute(
                "SELECT state,sampled_at FROM storage_samples ORDER BY storage_sample_id DESC LIMIT 1"
            ).fetchone()
            current_sample = False
            if sample is not None:
                try:
                    sampled = datetime.fromisoformat(sample["sampled_at"]).astimezone(timezone.utc)
                    current_sample = sampled >= moment - timedelta(minutes=10)
                except (TypeError, ValueError):
                    pass
            storage_ready = bool(current_sample and sample["state"] == "normal")
            add(
                "storage_admission", "pass" if storage_ready else "blocked",
                "current normal storage sample exists" if storage_ready
                else "run maintenance/storage sampling until a current normal sample exists",
            )

            backup = store.connection.execute(
                "SELECT backup_path,checksum FROM maintenance_runs "
                "WHERE kind='sqlite_backup' AND status='succeeded' "
                "AND backup_path IS NOT NULL AND checksum IS NOT NULL "
                "ORDER BY maintenance_run_id DESC LIMIT 1"
            ).fetchone()
            backup_ready = False
            if backup is not None:
                path = Path(backup["backup_path"])
                try:
                    resolved = path.resolve()
                    backup_ready = bool(
                        backups is not None
                        and resolved.is_relative_to(backups)
                        and not path.is_symlink()
                        and resolved.is_file()
                        and _file_hash(resolved) == backup["checksum"]
                    )
                except OSError:
                    pass
            add(
                "verified_backup", "pass" if backup_ready else "blocked",
                "latest audited SQLite backup exists and matches its checksum"
                if backup_ready else "run verified maintenance backup before production smoke",
            )

            if mode == "delivery":
                destinations = store.connection.execute(
                    "SELECT d.platform,d.secret_ref,r.status,r.valid_until "
                    "FROM social_destinations d JOIN capability_readiness r "
                    "ON r.social_destination_id=d.social_destination_id "
                    "WHERE d.enabled=1 ORDER BY d.social_destination_id"
                ).fetchall()
                if not destinations:
                    add("delivery_destinations", "blocked", "no enabled production destination exists")
                for row in destinations:
                    platform = str(row["platform"])
                    required = [str(row["secret_ref"])]
                    if platform == "instagram":
                        required.extend(("R2_ACCESS_KEY_ID", "R2_SECRET_ACCESS_KEY"))
                    missing = [name for name in required if not str(values.get(name, "")).strip()]
                    add(
                        f"{platform}_secrets", "pass" if not missing else "blocked",
                        f"{platform} secret references are resolved" if not missing
                        else f"missing secret references: {', '.join(sorted(set(missing)))}",
                    )
                    readiness_current = False
                    try:
                        readiness_current = (
                            row["status"] == "ready"
                            and datetime.fromisoformat(row["valid_until"]).astimezone(timezone.utc) > moment
                        )
                    except (TypeError, ValueError):
                        pass
                    add(
                        f"{platform}_live_readiness", "pass" if readiness_current else "blocked",
                        f"{platform} live readiness is current" if readiness_current
                        else f"{platform} requires a current successful live readiness check",
                    )
                uncertain = int(store.connection.execute(
                    "SELECT COUNT(*) FROM post_records WHERE status='publication_unknown'"
                ).fetchone()[0])
                add(
                    "publication_uncertainty", "pass" if uncertain == 0 else "warning",
                    "no unresolved publication-unknown record exists" if uncertain == 0
                    else f"{uncertain} publication-unknown record(s) require human reconciliation",
                )

    if store is not None:
        store.close()
    human_review = [
        "Confirm Google ADC and model availability with the first explicitly authorized Gemini smoke.",
        "Inspect the exact generated copy, claims, alt text, and rendered assets.",
    ]
    if mode != "preview":
        human_review.extend([
            "Approve the selected font/profile, account IDs, cadence, limits, and destination bindings.",
            "Confirm current Gemini prices and owner budget limits.",
        ])
    if mode == "delivery":
        human_review.extend([
            "Authorize the live Meta/X identity checks and transient R2 probe.",
            "Approve Post now separately for each exact destination package and observe the provider result.",
        ])
    blocked = sum(check["status"] == "blocked" for check in checks)
    warnings = sum(check["status"] == "warning" for check in checks)
    return {
        "schema_version": "smoke_readiness_report_v1",
        "mode": mode,
        "status": "ready" if blocked == 0 else "blocked",
        "blocking_count": blocked,
        "warning_count": warnings,
        "checks": checks,
        "human_review_required": human_review,
        "network_calls_made": False,
    }


def inspect_planning_readiness(database, *, environment=None):
    """Inspect local planning prerequisites; never resolve credentials over a network."""
    import importlib.util
    import sqlite3
    values = os.environ if environment is None else environment
    checks = []
    def add(name, ready, detail):
        checks.append({"check": name, "status": "pass" if ready else "blocked", "detail": detail})
    try:
        with WorkflowStore(database, read_only=True) as store:
            add('database', store.connection.execute('PRAGMA quick_check').fetchone()[0] == 'ok', 'current schema and SQLite integrity')
            catalog = store.catalog()
            ready = len(catalog) == 5 and all(c['enabled'] and c['generation_ready'] and len(c['outputs']) == 2 and all(o['ready'] for o in c['outputs']) for c in catalog)
            add('planning_catalog', ready, 'five development domains and two synthetic output bindings per domain')
            row = store.connection.execute("SELECT manifest_json FROM configuration_releases r JOIN configuration_activations a USING(configuration_release_id) WHERE a.status='active' AND a.scope_key='global'").fetchone()
            policy = json.loads(row[0])['components']['detection']['semantic_resolution']
            from huggingface_hub import hf_hub_download
            for filename in ('config.json', 'modules.json', 'tokenizer.json', 'model.safetensors', '1_Pooling/config.json'):
                hf_hub_download(policy['model_id'], filename, revision=policy['model_revision'], local_files_only=True)
            add('local_embedding_cache', True, 'pinned MiniLM snapshot exists locally; no inference or download performed')
    except Exception as error:
        add('local_setup', False, f'local planning setup incomplete ({type(error).__name__}); run setup_development.py with a fresh path and provision MiniLM')
    add('gemini_project', bool(values.get('GOOGLE_CLOUD_PROJECT', '').strip()), 'GOOGLE_CLOUD_PROJECT must be set')
    try:
        available = importlib.util.find_spec('google.genai') is not None
    except ModuleNotFoundError:
        available = False
    add('google_genai', available, 'local google-genai package')
    try:
        ModelBudgetPolicy.from_environment(values.get('GEMINI_MODEL') or values.get('VERTEX_AI_MODEL') or 'gemini-2.5-flash', values)
        add('gemini_budget', True, 'configured prices and bounded phase/daily/job limits are valid')
    except (ValueError, ModelBudgetConfigurationError) as error:
        add('gemini_budget', False, str(error))
    blocked = sum(c['status']=='blocked' for c in checks)
    return {'mode':'planning', 'status':'blocked' if blocked else 'ready', 'blocking_count':blocked,
            'checks':checks, 'network_calls_made':False,
            'human_review_required':['First live Gemini call verifies ADC, project permissions and model availability.',
                                     'Review source relevance, clarification quality and five-domain decisions; fixture accounts do not deliver content.']}
