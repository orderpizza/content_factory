"""Generate a static read-only detection dashboard snapshot."""

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from common.environment import load_environment_file
from database.migrations import connect, validate_detection_dashboard
from dashboard import render_detection_dashboard


ROOT = Path(__file__).resolve().parents[1]
load_environment_file(ROOT / ".env")
connection = connect(
    os.getenv("CONTENT_FACTORY_DB_PATH", str(ROOT / "data" / "content.db")),
    read_only=True,
)
try:
    validate_detection_dashboard(connection)
    output = Path(
        os.getenv(
            "CONTENT_FACTORY_DASHBOARD_PATH", str(ROOT / "generated" / "dashboard.html")
        )
    )
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(render_detection_dashboard(connection), encoding="utf-8")
    print(output)
finally:
    connection.close()
