"""Explicit schema/configuration setup for local semantic Scout; no collection."""

from argparse import ArgumentParser
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from database.migrations import migrate_semantic_events
from detection.configuration import load_manifest
from detection.store import DetectionStore


def main():
    parser = ArgumentParser(description=__doc__)
    parser.add_argument("--database", required=True, help="Existing schema v4 database; back up and stop Scout first")
    parser.add_argument("--download-model", action="store_true", help="Explicitly download the pinned public model; no observations leave this machine")
    args = parser.parse_args()
    manifest = load_manifest(ROOT / "config/releases/detection.json")
    if args.download_model:
        from huggingface_hub import snapshot_download
        policy = manifest["components"]["detection"]["semantic_resolution"]
        snapshot_download(policy["model_id"], revision=policy["model_revision"],
                          allow_patterns=["*.json", "*.txt", "*.safetensors"],
                          ignore_patterns=["onnx/*", "openvino/*"])
    migrate_semantic_events(args.database)
    with DetectionStore(args.database) as store:
        store.apply_manifest(manifest)
    print("Semantic event schema and configured release ready. No collection or publishing performed.")


if __name__ == "__main__":
    main()
