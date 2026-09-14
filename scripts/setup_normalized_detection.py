"""Create a separate normalized/hybrid detection database; never replace one."""

from argparse import ArgumentParser
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from database.migrations import migrate_detection_dashboard, migrate_editorial_workflow, migrate_detection_safety, migrate_production_workflow, migrate_semantic_events
from detection.configuration import load_manifest
from detection.store import DetectionStore


def main():
    parser = ArgumentParser(description=__doc__)
    parser.add_argument("--database", required=True, help="New database filename; existing files are refused.")
    args = parser.parse_args()
    manifest = load_manifest(ROOT / "config/releases/detection.json")
    path = Path(args.database).resolve()
    if not path.parent.is_dir():
        parser.error("database parent directory must already exist")
    try:
        with path.open("xb"):
            pass
    except FileExistsError:
        parser.error("database already exists; no data, configuration or handoffs were changed")
    migrate_detection_dashboard(path)
    migrate_editorial_workflow(path)
    migrate_detection_safety(path)
    with DetectionStore(path) as store:
        store.apply_manifest(manifest)
    migrate_production_workflow(path)
    migrate_semantic_events(path)
    print(f"Created normalized hybrid database: {path}. Existing databases were not modified.")


if __name__ == "__main__":
    main()
