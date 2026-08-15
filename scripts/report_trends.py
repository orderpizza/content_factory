"""Print the current ranked trend report."""

import os

from database.sqlite import Database
from intelligence.reporting import format_report, ranked_candidates


def main() -> None:
    database = Database(os.getenv("CONTENT_FACTORY_DB_PATH", "data/content.db"))
    database.initialize()
    try:
        candidates = ranked_candidates(database, limit=int(os.getenv("CONTENT_FACTORY_REPORT_LIMIT", "20")))
        print(format_report(candidates))
    finally:
        database.close()


if __name__ == "__main__":
    main()
