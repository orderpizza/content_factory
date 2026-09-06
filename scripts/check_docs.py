"""Consistency checks for the Content Factory documentation model."""

from pathlib import Path
import re
from urllib.parse import unquote


ROOT = Path(__file__).resolve().parents[1]
REQUIRED = [
    ROOT / "AGENTS.md",
    ROOT / "docs" / "system.md",
    ROOT / "docs" / "specs" / "detection.md",
    ROOT / "docs" / "specs" / "idea-intake-and-determination.md",
    ROOT / "docs" / "specs" / "visual-rendering.md",
    ROOT / "docs" / "specs" / "posting.md",
    ROOT / "docs" / "specs" / "data-model.md",
    ROOT / "docs" / "specs" / "dashboard.md",
    ROOT / "docs" / "specs" / "runtime.md",
    ROOT / "docs" / "specs" / "reliability.md",
    ROOT / "docs" / "pipelines" / "o2-english-instagram.md",
    ROOT / "docs" / "platforms" / "meta.md",
    ROOT / "docs" / "archive" / "decisions.md",
    ROOT / ".env.example",
]
TIER_TWO_CONTRACTS = [
    ROOT / "docs" / "specs" / "detection.md",
    ROOT / "docs" / "specs" / "idea-intake-and-determination.md",
    ROOT / "docs" / "specs" / "visual-rendering.md",
    ROOT / "docs" / "specs" / "posting.md",
    ROOT / "docs" / "specs" / "data-model.md",
    ROOT / "docs" / "specs" / "dashboard.md",
    ROOT / "docs" / "specs" / "runtime.md",
    ROOT / "docs" / "specs" / "reliability.md",
    ROOT / "docs" / "pipelines" / "o2-english-instagram.md",
    ROOT / "docs" / "platforms" / "meta.md",
]
DOCUMENTS = [ROOT / "README.md", *sorted((ROOT / "docs").rglob("*.md"))]
LOCAL_LINK = re.compile(r"(?<!!)\[[^\]]*\]\(([^)\s]+)(?:\s+\"[^\"]*\")?\)")
DATA_MODEL_REQUIRED_HEADINGS = (
    "## Four identities",
    "## Required constraints and indexes",
    "## Baseline DDL and transition rules",
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
    "content_jobs",
    "generation_runs",
    "content_packages",
    "render_runs",
    "review_requests",
    "post_requests",
    "post_records",
    "post_attempts",
    "reconciliation_requests",
    "model_invocations",
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
