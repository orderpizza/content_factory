"""Validate current documentation links, schema inventory and configuration."""
from pathlib import Path
import json
import re
import sqlite3
import sys
from urllib.parse import unquote

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from database.current import SCHEMA_VERSION, CONTRACT_PATH
from detection.configuration import load_manifest
from workflow.catalog import WORKFLOW_PIPELINES

DOCUMENTS = [*sorted(ROOT.glob('*.md')), *sorted((ROOT / "docs").rglob("*.md"))]
REQUIRED = ["docs/system.md", "docs/current-state.md", "docs/specs/detection.md",
            "docs/specs/idea-intake-and-determination.md", "docs/specs/dashboard.md",
            "docs/specs/data-model.md", "docs/specs/data/records.md",
            "docs/specs/configuration.md", "docs/specs/runtime.md",
            "docs/contracts/application-schema.sql", "docs/contracts/README.md",
            "docs/plans/target-implementation.md", ".env.example"]
LINK = re.compile(r"(?<!!)\[[^\]]*\]\(([^)\s]+)(?:\s+\"[^\"]*\")?\)")
HEADING = re.compile(r"^#{1,6}\s+(.+?)\s*$", re.M)


def anchor(value):
    return re.sub(r"[^a-z0-9 _-]", "", value.lower()).replace(" ", "-")


def main():
    errors = [f"Missing {p}" for p in REQUIRED if not (ROOT/p).is_file()]
    texts = {p: p.read_text() for p in DOCUMENTS if p.is_file()}
    router = texts.get(ROOT/'docs/system.md', '')
    routed = {(ROOT/'docs'/target.partition('#')[0]).resolve()
              for target in LINK.findall(router) if '://' not in target}
    for document in texts:
        relative = document.relative_to(ROOT)
        if relative.parts[:2] in {('docs','specs'), ('docs','pipelines'), ('docs','platforms')} and document.resolve() not in routed:
            errors.append(f"Unrouted focused document: {relative}")
    for document, content in texts.items():
        for target in LINK.findall(content):
            target = unquote(target)
            if "://" in target or target.startswith(("mailto:", "tel:")):
                continue
            path, _, fragment = target.partition("#")
            linked = (document.parent / path.split("?")[0]).resolve() if path else document.resolve()
            if not linked.is_relative_to(ROOT) or not linked.is_file():
                errors.append(f"{document.relative_to(ROOT)}: missing local link {target}")
            elif fragment and linked in texts and fragment not in {anchor(h) for h in HEADING.findall(texts[linked])}:
                errors.append(f"{document.relative_to(ROOT)}: missing anchor {target}")
        local_content = re.sub(r"https?://[^\s)]+", "", content)
        for target in re.findall(r"(?:scripts|src|config|docs/contracts)/[A-Za-z0-9_./-]+", local_content):
            target = target.rstrip(".")
            if Path(target).suffix in {".py", ".sql", ".json"} and not (ROOT/target).is_file():
                errors.append(f"{document.relative_to(ROOT)}: obsolete file reference {target}")
    connection = sqlite3.connect(":memory:")
    try:
        connection.executescript(CONTRACT_PATH.read_text())
        if connection.execute("PRAGMA user_version").fetchone()[0] != SCHEMA_VERSION:
            errors.append("SQL schema version disagrees with database.current")
        tables = [r[0] for r in connection.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")]
        records = (ROOT/"docs/specs/data/records.md").read_text()
        for table in tables:
            if table not in records:
                errors.append(f"SQLite record inventory does not name {table}")
        if connection.execute("PRAGMA foreign_key_check").fetchall():
            errors.append("SQL foreign keys are inconsistent")
    finally:
        connection.close()
    try:
        manifest = load_manifest(ROOT/"config/releases/detection.json")
        detection = (ROOT/"docs/specs/detection.md").read_text()
        for source in manifest["components"]["detection"]["sources"]:
            if source["stable_id"] not in detection:
                errors.append(f"Undocumented Detection source: {source['stable_id']}")
        if manifest["components"]["detection"]["score_formula_version"] not in detection:
            errors.append("Active scoring version is not documented")
    except Exception as error:
        errors.append(f"Detection configuration is invalid: {type(error).__name__}")
    domains = re.findall(r"^\| `([a-z0-9_]+)` \|", (ROOT/"docs/pipelines/domains.md").read_text(), re.M)
    if set(domains) != set(WORKFLOW_PIPELINES) or len(domains) != 5:
        errors.append("Domain reference must contain exactly five registered domains")
    settings = (ROOT/"docs/specs/configuration.md").read_text()
    for key in re.findall(r"^(?:# )?([A-Z][A-Z0-9_]+)=", (ROOT/".env.example").read_text(), re.M):
        if key not in settings and not re.fullmatch(r"GEMINI_(INTAKE|DETERMINATION|GENERATION|ADAPTATION)_MAX_(INPUT|OUTPUT)_TOKENS", key):
            errors.append(f"Undocumented environment variable: {key}")
    for path in (ROOT/"docs/contracts").glob("*.schema.json"):
        try:
            json.loads(path.read_text())
        except ValueError:
            errors.append(f"Invalid JSON contract: {path.name}")
    if errors:
        print("Documentation check failed:\n" + "\n".join("- "+e for e in sorted(set(errors))))
        raise SystemExit(1)
    print(f"Documentation check passed: {len(texts)} current documents, {len(tables)} schema tables.")


if __name__ == "__main__":
    main()
