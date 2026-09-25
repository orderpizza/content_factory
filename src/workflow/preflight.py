"""Read-only, non-network smoke-readiness inspection for the versioned workflow."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Callable, Mapping
import json
import os

from database.current import SchemaError

from .model_budget import ModelBudgetConfigurationError, ModelBudgetPolicy
from .store import WorkflowStore


def _dependency_probe() -> dict[str, tuple[bool, str]]:
    checks: dict[str, tuple[bool, str]] = {}
    try:
        from google import genai  # noqa: F401
    except ImportError:
        checks["google_genai"] = (False, "google-genai is not installed")
    else:
        checks["google_genai"] = (True, "google-genai is importable")
    try:
        from PIL import Image
    except ImportError:
        checks["pillow"] = (False, "Pillow is not installed")
    else:
        checks["pillow"] = (True, "Pillow is importable for storyboard processing")
    return checks


def _path_writable(path: Path) -> bool:
    candidate = path
    while not candidate.exists() and candidate != candidate.parent:
        candidate = candidate.parent
    return candidate.is_dir() and os.access(candidate, os.W_OK | os.X_OK)


def inspect_smoke_readiness(
    database: str | Path,
    artifact_root: str | Path,
    *,
    mode: str,
    environment: Mapping[str, str] | None = None,
    dependency_probe: Callable[[], dict[str, tuple[bool, str]]] = _dependency_probe,
) -> dict[str, Any]:
    """Return safe preflight facts without calling Gemini or any delivery provider."""
    if mode == "planning":
        return inspect_planning_readiness(database, environment=environment)
    if mode != "preview":
        raise ValueError("smoke readiness mode must be planning or preview")
    values = os.environ if environment is None else environment
    checks: list[dict[str, str]] = []

    def add(check_id: str, status: str, detail: str) -> None:
        checks.append({"check": check_id, "status": status, "detail": detail})

    database_path = Path(database).resolve()
    artifacts = Path(artifact_root).resolve()
    store: WorkflowStore | None = None
    try:
        store = WorkflowStore(
            database_path, read_only=True,
            catalog_kind="fixture",
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
        except Exception as error:
            add("database_inspection", "blocked", f"database inspection failed ({type(error).__name__})")

    project = str(values.get("GOOGLE_CLOUD_PROJECT", "")).strip()
    add(
        "gemini_project", "pass" if project else "blocked",
        "Vertex project is configured" if project else "GOOGLE_CLOUD_PROJECT is missing",
    )
    model = str(values.get("GEMINI_MODEL") or values.get("VERTEX_AI_MODEL") or "gemini-3.7-flash")
    add("gemini_model", "pass", f"configured model identifier: {model}")
    for check_id, (ready, detail) in dependency_probe().items():
        add(check_id, "pass" if ready else "blocked", detail)
    add(
        "artifact_root", "pass" if _path_writable(artifacts) else "blocked",
        "artifact destination is locally writable" if _path_writable(artifacts)
        else "artifact destination or its nearest existing parent is not writable",
    )

    for image, model_id, key in (
        (False, model, "gemini_budget"),
        (True, values.get("GEMINI_IMAGE_MODEL") or "gemini-3.1-flash-image", "image_budget"),
    ):
        try:
            ModelBudgetPolicy.from_environment(model_id, values, image=image)
            add(key, "pass", "priced phase/daily/job policy is configured")
        except (ModelBudgetConfigurationError, TypeError, ValueError) as error:
            add(key, "blocked", str(error))

    if store is not None:
        store.close()
    human_review = [
        "Confirm Google ADC and model availability with the first explicitly authorized Gemini smoke.",
        "Inspect the exact generated copy, claims, alt text, and rendered assets.",
    ]
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
            ready = len(catalog) == 3 and all(c['enabled'] and c['generation_ready'] and len(c['outputs']) == 1 and all(o['ready'] for o in c['outputs']) for c in catalog)
            add('planning_catalog', ready, 'three development domains and one synthetic Instagram binding per domain')
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
        ModelBudgetPolicy.from_environment(values.get('GEMINI_MODEL') or values.get('VERTEX_AI_MODEL') or 'gemini-3.7-flash', values)
        add('gemini_budget', True, 'configured prices and bounded phase/daily/job limits are valid')
    except (ValueError, ModelBudgetConfigurationError) as error:
        add('gemini_budget', False, str(error))
    blocked = sum(c['status']=='blocked' for c in checks)
    return {'mode':'planning', 'status':'blocked' if blocked else 'ready', 'blocking_count':blocked,
            'checks':checks, 'network_calls_made':False,
            'human_review_required':['First live Gemini call verifies ADC, project permissions and model availability.',
                                     'Review source relevance, clarification quality and three-domain decisions; fixture accounts do not deliver content.']}
