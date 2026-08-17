"""Render persisted packages. The active POC format is o2_english carousel."""

import asyncio
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from common.models import ContentPackage
from database.sqlite import Database
from visual.o2_english import render_and_record_idiom_carousel_png


def _package_from_row(row) -> ContentPackage:
    return ContentPackage(
        job_id=row["job_id"], pipeline_id=row["pipeline_id"], title=row["title"], body=row["body"],
        caption=row["caption"], visual_spec=json.loads(row["visual_spec"]), assets=json.loads(row["assets"]),
        sources=json.loads(row["sources"]), content_id=row["content_id"], created_at=row["created_at"],
        platform=row["platform"], account=row["account"], content_format=row["content_format"],
        tags=json.loads(row["tags"]), hashtags=json.loads(row["hashtags"]), status=row["status"],
        metadata_status=row["metadata_status"], metadata_model=row["metadata_model"],
    )


async def main() -> None:
    database = Database(os.getenv("CONTENT_FACTORY_DB_PATH", "data/content.db"))
    database.initialize()
    try:
        rendered = 0
        root = Path(os.getenv("CONTENT_FACTORY_RENDER_OUTPUT", "generated"))
        for row in database.packages_awaiting_render():
            package = _package_from_row(row)
            if package.pipeline_id != "o2_english_instagram":
                continue
            await render_and_record_idiom_carousel_png(database, package, root / f"content-{package.content_id}")
            rendered += 1
        print(f"Content packages rendered: {rendered}")
    finally:
        database.close()


if __name__ == "__main__":
    asyncio.run(main())
