"""Generate a read-only HTML dashboard."""

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from database.sqlite import Database
from dashboard import render_dashboard


database = Database(os.getenv("CONTENT_FACTORY_DB_PATH", "data/content.db"))
database.initialize()
try:
    output = Path(os.getenv("CONTENT_FACTORY_DASHBOARD_PATH", "generated/dashboard.html"))
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(render_dashboard(database), encoding="utf-8")
    print(output)
finally:
    database.close()
