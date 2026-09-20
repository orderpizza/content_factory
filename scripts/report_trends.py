"""Print a bounded, read-only report from the current detection schema."""

from __future__ import annotations

from pathlib import Path
import os
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from common.environment import load_environment_file
from detection.store import DetectionStore


ROOT = Path(__file__).resolve().parents[1]


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    load_environment_file(ROOT / ".env")
    database = os.getenv("CONTENT_FACTORY_DB_PATH", str(ROOT / "data" / "development.db"))
    limit = max(1, min(100, int(os.getenv("CONTENT_FACTORY_REPORT_LIMIT", "20"))))
    with DetectionStore(database, read_only=True) as store:
        rows = store.connection.execute(
            "SELECT trend_candidate_id, eligibility_status, score, canonical_subject, "
            "eligibility_reason, last_seen_at FROM trend_candidates "
            "ORDER BY score DESC, last_seen_at DESC, trend_candidate_id DESC LIMIT ?",
            (limit,),
        ).fetchall()
    if not rows:
        print("No scored Clusters. Run scripts/run_detection.py first.")
        return
    print('Cluster ID · Detection attention score · Detection selection · Subject')
    for row in rows:
        print(
            f"{row['trend_candidate_id']:>4}  {row['score']:.4f}  "
            f"{row['eligibility_status']:<18}  {row['canonical_subject']}"
        )
        print(f"      {row['eligibility_reason']} · {row['last_seen_at']}")


if __name__ == "__main__":
    main()
