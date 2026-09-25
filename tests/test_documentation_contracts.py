"""Current-documentation guards; no compatibility payloads are required."""

from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
from unittest.mock import patch
import runpy
import shutil
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]


class DocumentationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        for directory in ('docs','config','src','scripts','acceptance'):
            shutil.copytree(ROOT/directory,self.root/directory,ignore=shutil.ignore_patterns('__pycache__'))
        for path in [*ROOT.glob('*.md'),ROOT/'.env.example']:
            shutil.copy2(path,self.root/path.name)
        self.main = runpy.run_path(str(ROOT/'scripts/check_docs.py'))['main']

    def run_check(self):
        documents = [*self.root.glob('*.md'),*(self.root/'docs').rglob('*.md'),*(self.root/'acceptance').rglob('*.md')]
        with patch.dict(self.main.__globals__,{'ROOT':self.root,'DOCUMENTS':documents,'CONTRACT_PATH':self.root/'docs/contracts/application-schema.sql'}), redirect_stdout(StringIO()) as output:
            try:
                self.main()
            except SystemExit:
                pass
        return output.getvalue()

    def alter(self,path,transform):
        target=self.root/path
        target.write_text(transform(target.read_text()))

    def test_current_documents_pass(self):
        self.assertIn('check passed',self.run_check())

    def test_missing_local_link_is_rejected(self):
        self.alter('README.md',lambda text:text+'\n[missing](docs/missing.md)\n')
        self.assertIn('missing local link',self.run_check())

    def test_unrouted_focused_document_is_rejected(self):
        self.alter('docs/system.md',lambda text:text.replace('(specs/visual-rendering.md)', ''))
        self.assertIn('Unrouted focused document: docs/specs/visual-rendering.md',self.run_check())

    def test_root_readme_broken_anchor_is_rejected(self):
        self.alter('README.md',lambda text:text+'\n[bad](docs/current-state.md#missing-section)\n')
        self.assertIn('missing anchor',self.run_check())

    def test_duplicate_or_platform_specific_domain_is_rejected(self):
        self.alter('docs/pipelines/domains.md',lambda text:text.replace('`english`','`english_instagram`'))
        self.assertIn('exactly three',self.run_check())

    def test_schema_version_disagreement_is_rejected(self):
        self.alter('docs/contracts/application-schema.sql',lambda text:text.replace('user_version = 15','user_version = 99'))
        self.assertIn('schema version disagrees',self.run_check())

    def test_undocumented_table_is_rejected(self):
        self.alter('docs/contracts/application-schema.sql',lambda text:text+'\nCREATE TABLE undocumented_record(id INTEGER);\n')
        self.assertIn('does not name undocumented_record',self.run_check())

    def test_undocumented_environment_variable_is_rejected(self):
        self.alter('.env.example',lambda text:text+'\nNEW_UNDOCUMENTED_KEY=\n')
        self.assertIn('Undocumented environment variable',self.run_check())

    def test_undocumented_code_lookup_is_rejected(self):
        self.alter('src/common/gemini.py', lambda text: text + '\nvalue = os.getenv("NEW_RUNTIME_SETTING")\n')
        self.assertIn('Environment lookup absent from .env.example: NEW_RUNTIME_SETTING', self.run_check())

    def test_unused_template_setting_is_rejected(self):
        self.alter('.env.example', lambda text: text + '\nUNUSED_SETTING=\n')
        self.alter('docs/specs/configuration.md', lambda text: text + '\nUNUSED_SETTING\n')
        self.assertIn('Unused operator environment variable: UNUSED_SETTING', self.run_check())

    def test_duplicate_source_roster_entry_is_rejected(self):
        self.alter('docs/specs/detection.md', lambda text: text + '\n| `openai_news_rss_v1` | duplicate | ignored |\n')
        self.assertIn('roster must match', self.run_check())

    def test_undocumented_operator_script_is_rejected(self):
        (self.root / 'scripts/unlisted.py').write_text('')
        self.assertIn('Operator entrypoint is not documented', self.run_check())

    def test_environment_subscript_lookup_is_checked(self):
        self.alter('src/common/gemini.py', lambda text: text + '\nvalue = os.environ["UNLISTED_KEY"]\n')
        self.assertIn('Environment lookup absent from .env.example: UNLISTED_KEY', self.run_check())
