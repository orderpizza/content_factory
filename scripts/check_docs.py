"""Lightweight consistency checks for the Content Factory documentation model."""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
REQUIRED = [
    ROOT / "AGENTS.md",
    ROOT / "docs" / "system.md",
    ROOT / "docs" / "specs" / "data-model.md",
    ROOT / "docs" / "specs" / "dashboard.md",
    ROOT / "docs" / "specs" / "reliability.md",
    ROOT / "docs" / "pipelines" / "o2-english-instagram.md",
    ROOT / "docs" / "platforms" / "meta.md",
    ROOT / "docs" / "archive" / "decisions.md",
    ROOT / ".env.example",
]


def main() -> None:
    errors = [f"Missing required documentation: {path.relative_to(ROOT)}" for path in REQUIRED if not path.is_file()]
    system = ROOT / "docs" / "system.md"
    if system.is_file():
        text = system.read_text(encoding="utf-8")
        for heading in (
            "## Current Objective",
            "## Current State",
            "## Components, Inputs, and Persisted Outputs",
            "## Document Router",
            "## Local Operation and Verification",
        ):
            if heading not in text:
                errors.append(f"docs/system.md is missing {heading!r}")
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
