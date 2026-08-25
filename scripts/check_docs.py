"""Lightweight consistency checks for the Content Factory documentation model."""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
REQUIRED = [
    ROOT / "AGENTS.md",
    ROOT / "docs" / "current.md",
    ROOT / "docs" / "roadmap.md",
    ROOT / "docs" / "architecture.md",
    ROOT / "docs" / "interfaces.md",
    ROOT / "docs" / "system-flow.md",
    ROOT / "docs" / "poc.md",
    ROOT / "docs" / "pipelines" / "o2-english-instagram.md",
    ROOT / "docs" / "decisions.md",
    ROOT / "docs" / "runbooks" / "gemini.md",
    ROOT / "docs" / "runbooks" / "local-runtime.md",
]


def main() -> None:
    errors = [f"Missing required documentation: {path.relative_to(ROOT)}" for path in REQUIRED if not path.is_file()]
    current = ROOT / "docs" / "current.md"
    if current.is_file():
        text = current.read_text(encoding="utf-8")
        for heading in ("## Current Target", "## Status", "## Acceptance Criteria For This Milestone"):
            if heading not in text:
                errors.append(f"docs/current.md is missing {heading!r}")
    for path in (ROOT / "README.md", ROOT / "docs" / "architecture.md", ROOT / "docs" / "poc.md"):
        if path.is_file() and "daily_expression" in path.read_text(encoding="utf-8"):
            errors.append(f"Removed reference project is still mentioned in {path.relative_to(ROOT)}")
    if errors:
        print("Documentation check failed:")
        print("\n".join(f"- {error}" for error in errors))
        raise SystemExit(1)
    print("Documentation check passed.")


if __name__ == "__main__":
    main()
