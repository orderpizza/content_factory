"""Build hook; project metadata remains in pyproject.toml."""

from setuptools import setup
from pathlib import Path
from runpy import run_path

# PEP 517 build isolation does not put the project root on sys.path.
BuildWithContracts = run_path(str(Path(__file__).resolve().with_name("build_support.py")))["BuildWithContracts"]

setup(cmdclass={"build_py": BuildWithContracts})
