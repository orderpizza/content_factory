"""Delete detector records older than the configured retention period."""

import os
from datetime import datetime, timedelta, timezone

from database.sqlite import Database


database = Database(os.getenv("CONTENT_FACTORY_DB_PATH", "data/content.db"))
database.initialize()
try:
    days = int(os.getenv("CONTENT_FACTORY_RETENTION_DAYS", "30"))
    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    print(database.cleanup_before(cutoff))
finally:
    database.close()
