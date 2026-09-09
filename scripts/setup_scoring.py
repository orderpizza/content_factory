"""Explicitly migrate a v2 database to safety v3 and activate hybrid scoring."""

from argparse import ArgumentParser
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from database.migrations import migrate_detection_safety
from detection.configuration import load_manifest
from detection.store import DetectionStore


def main():
    parser = ArgumentParser(description=__doc__)
    parser.add_argument("--database", required=True, help="Exact existing v2 DB path; stop affected workers and back up first.")
    args = parser.parse_args()
    manifest = load_manifest(ROOT / "config/releases/detection-hybrid-v2.json")
    path = Path(args.database).resolve()
    if not path.is_file():
        parser.error("an existing v2 database is required; this command never creates or resets it")
    migrate_detection_safety(path)
    with DetectionStore(path) as store:
        store.apply_manifest(manifest)
    print(f"Hybrid scoring activated on {path}; historical snapshots and handoffs retained.")


if __name__ == "__main__":
    main()
