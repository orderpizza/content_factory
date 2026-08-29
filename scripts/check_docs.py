"""Lightweight consistency checks for the Content Factory documentation model."""

from pathlib import Path


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
