"""Exercise the built distribution outside the checkout, without providers."""

from hashlib import sha256
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
import zipfile


ROOT = Path(__file__).resolve().parents[1]


class PackagedContractTests(unittest.TestCase):
    def test_built_wheel_migrates_without_checkout_resources(self):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory)
            build = subprocess.run(
                [sys.executable, "setup.py", "egg_info", "--egg-base", str(target), "build", "--build-base", str(target / "build"),
                 "bdist_wheel", "--dist-dir", str(target / "dist"), "--bdist-dir", str(target / "bdist")],
                cwd=ROOT, capture_output=True, text=True,
            )
            self.assertEqual(build.returncode, 0, build.stdout + build.stderr)
            wheel, = (target / "dist").glob("*.whl")
            installed = target / "installed"
            with zipfile.ZipFile(wheel) as archive:
                archive.extractall(installed)
            contracts = installed / "content_factory_resources" / "contracts"
            expected = sorted((ROOT / "docs/contracts").glob("*-schema-v*.sql"))
            self.assertGreaterEqual(len(expected), 3)
            for source in expected:
                self.assertEqual(sha256(source.read_bytes()).hexdigest(), sha256((contracts / source.name).read_bytes()).hexdigest())
            code = """
import sys
sys.path.insert(0, sys.argv[1])
from database.migrations import migrate_detection_dashboard, migrate_editorial_workflow, migrate_detection_safety, connect, validate_detection_dashboard, CONTRACT_PATH
assert 'installed' in str(CONTRACT_PATH), CONTRACT_PATH
path = sys.argv[2]
assert migrate_detection_dashboard(path)
assert migrate_editorial_workflow(path)
assert migrate_detection_safety(path)
assert not migrate_detection_safety(path)
connection = connect(path)
validate_detection_dashboard(connection)
assert connection.execute('PRAGMA user_version').fetchone()[0] == 3
connection.close()
"""
            result = subprocess.run([sys.executable, "-I", "-c", code, str(installed), str(target / "fixture.db")],
                                    cwd=target, capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


if __name__ == "__main__":
    unittest.main()
