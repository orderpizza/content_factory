"""Copy canonical resources into build output, never duplicate editable contracts."""

from pathlib import Path
from setuptools.command.build_py import build_py


class BuildWithContracts(build_py):
    def run(self):
        super().run()
        root = Path(__file__).resolve().parent
        target = Path(self.build_lib) / "content_factory_resources" / "contracts"
        self.mkpath(str(target))
        source = root / "docs" / "contracts" / "application-schema.sql"
        self.copy_file(str(source), str(target / source.name))
