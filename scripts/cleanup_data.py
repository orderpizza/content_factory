"""Archive and compact detector records older than the configured retention period."""

import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from database.sqlite import Database


database = Database(os.getenv("CONTENT_FACTORY_DB_PATH", "data/content.db"))
database.initialize()
try:
    days = int(os.getenv("CONTENT_FACTORY_RETENTION_DAYS", "90"))
    archive_directory = os.getenv("CONTENT_FACTORY_ARCHIVE_DIR", "data/archive")
    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    print(database.archive_and_cleanup(cutoff, archive_directory))
finally:
    database.close()
