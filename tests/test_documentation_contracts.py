"""Regression guards for Phase 1 documentation routing and schema maturity."""

import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "check_docs.py"
SPEC = importlib.util.spec_from_file_location("documentation_checks", SCRIPT)
checks = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(checks)


class PhaseOneDocumentationTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.domains = sorted(checks.PHASE_ONE_DOMAINS)
        self.write("docs/pipelines/domains.md", "\n".join(
            f"| `{domain}` | Instagram | X | configured |" for domain in self.domains
        ))
        names = " ".join(f"`{domain}`" for domain in self.domains)
        self.write("AGENTS.md", names)
        self.write("docs/system.md", names)
        self.write("docs/specs/content-production.md", "# Production owner\n")
        self.write_schema()
        root_patch = patch.object(checks, "ROOT", self.root)
        root_patch.start()
        self.addCleanup(root_patch.stop)

    def write(self, relative, content):
        path = self.root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")

    def write_schema(self, maturity="superseded", owner="docs/specs/content-production.md"):
        self.write("docs/contracts/recipe-v1.schema.json", json.dumps({
            "$id": "content_factory/recipe_v1",
            "x-maturity": maturity,
            "x-replacement-owner": owner,
        }))

    def errors(self):
        result = []
        checks.check_phase_one_contracts(result)
        return result

    def test_valid_domain_map_and_retired_schema(self):
        self.assertEqual(self.errors(), [])

    def test_duplicate_domain_row_rejected(self):
        path = self.root / "docs/pipelines/domains.md"
        self.write("docs/pipelines/domains.md", path.read_text(encoding="utf-8")
                   + "\n| `english` | duplicate | X | configured |")
        self.assertTrue(any("exactly the five" in error for error in self.errors()))

    def test_platform_suffixed_domain_rejected(self):
        path = self.root / "docs/pipelines/domains.md"
        self.write("docs/pipelines/domains.md", path.read_text(encoding="utf-8")
                   .replace("`english`", "`o2_english_instagram`"))
        self.assertTrue(any("exactly the five" in error for error in self.errors()))

    def test_old_agent_responsibility_rejected(self):
        path = self.root / "AGENTS.md"
        self.write("AGENTS.md", path.read_text(encoding="utf-8")
                   + "\nPipelines are platform- and format-specific.")
        self.assertTrue(any("platform-specific pipelines" in error for error in self.errors()))

    def test_unmarked_superseded_schema_rejected(self):
        self.write_schema(maturity="approved_for_implementation")
        self.assertTrue(any("x-maturity" in error for error in self.errors()))

    def test_missing_replacement_owner_rejected(self):
        self.write_schema(owner="docs/specs/missing.md")
        self.assertTrue(any("x-replacement-owner" in error for error in self.errors()))

    def test_missing_router_domain_rejected(self):
        path = self.root / "docs/system.md"
        self.write("docs/system.md", path.read_text(encoding="utf-8").replace("`english`", ""))
        self.assertTrue(any("does not name domain `english`" in error for error in self.errors()))


if __name__ == "__main__":
    unittest.main()
