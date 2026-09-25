"""Non-secret build and model configuration identity for local diagnostics."""

from __future__ import annotations

from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
import subprocess

from common.gemini import (
    configured_api_version,
    configured_location,
    configured_model,
    text_timeout_seconds,
)
from database.current import SCHEMA_VERSION


def runtime_fingerprint() -> dict[str, object]:
    """Return stable, non-secret information that identifies this execution."""
    root = Path(__file__).resolve().parents[2]
    try:
        commit = subprocess.run(
            ["git", "-C", str(root), "rev-parse", "--verify", "HEAD"],
            capture_output=True, text=True, timeout=1, check=True,
        ).stdout.strip() or None
    except (OSError, subprocess.SubprocessError):
        commit = None
    try:
        dirty = bool(subprocess.run(
            ["git", "-C", str(root), "status", "--porcelain"],
            capture_output=True, text=True, timeout=1, check=True,
        ).stdout.strip())
    except (OSError, subprocess.SubprocessError):
        dirty = None
    try:
        sdk_version = version("google-genai")
    except PackageNotFoundError:
        sdk_version = None
    from workflow.gemini_adaptation import ADAPTATION_PROMPT_VERSION, ADAPTATION_SCHEMA_VERSION
    from workflow.gemini_determination import DETERMINATION_PROMPT_VERSION, DETERMINATION_SCHEMA_VERSION
    from workflow.gemini_generation import GENERATION_PROMPT_VERSION, GENERATION_SCHEMA_VERSION
    from workflow.gemini_intake import INTAKE_PROMPT_VERSION, INTAKE_SCHEMA_VERSION
    from workflow.editorial_planning import PLANNER_VERSION, PROPOSAL_VERSION, SCHEMA_VERSION as PLAN_SCHEMA_VERSION

    prompt_versions = {
        "intake": INTAKE_PROMPT_VERSION,
        "determination": DETERMINATION_PROMPT_VERSION,
        "editorial_planning": PLANNER_VERSION,
        "generation": GENERATION_PROMPT_VERSION,
        "adaptation": ADAPTATION_PROMPT_VERSION,
    }
    schema_versions = {
        "intake": INTAKE_SCHEMA_VERSION,
        "determination": DETERMINATION_SCHEMA_VERSION,
        "editorial_planning": f"{PROPOSAL_VERSION}/{PLAN_SCHEMA_VERSION}",
        "generation": GENERATION_SCHEMA_VERSION,
        "adaptation": ADAPTATION_SCHEMA_VERSION,
    }
    return {
        "application_version": "0.1.0",
        "database_schema_version": SCHEMA_VERSION,
        "git_commit_sha": commit,
        "git_worktree_dirty": dirty,
        "google_genai_sdk_version": sdk_version,
        "prompt_versions": prompt_versions,
        "schema_versions": schema_versions,
        "text_model": configured_model(),
        "image_model": __import__("os").getenv("GEMINI_IMAGE_MODEL", "gemini-3.1-flash-image"),
        "vertex_location": configured_location(configured_model()),
        "api_version": configured_api_version(configured_model()),
        "text_timeout_seconds": text_timeout_seconds(),
    }
