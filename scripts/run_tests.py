"""Run the offline pytest suite without manual Python path configuration."""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))


if __name__ == "__main__":
    import pytest
    raise SystemExit(pytest.main([str(ROOT / "tests"), "-q"]))
