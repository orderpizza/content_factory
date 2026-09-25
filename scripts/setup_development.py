"""Create one fresh current-schema development database and planning catalog."""
from argparse import ArgumentParser
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from workflow.development import prepare_development_database
from common.environment import load_environment_file
from database.paths import new_primary_database_path

DATA_DIRECTORY = ROOT / "data"


def main():
    load_environment_file(ROOT / ".env")
    parser = ArgumentParser(description=__doc__)
    parser.add_argument("--download-model", action="store_true", help="Provision the pinned public MiniLM model; no input data is sent")
    args = parser.parse_args()
    if args.download_model:
        from huggingface_hub import snapshot_download
        from detection.configuration import load_manifest
        policy = load_manifest(ROOT / "config/releases/detection.json")["components"]["detection"]["semantic_resolution"]
        snapshot_download(policy["model_id"], revision=policy["model_revision"],
                          allow_patterns=["*.json", "*.txt", "*.safetensors"], ignore_patterns=["onnx/*", "openvino/*"])
    database_path = new_primary_database_path(DATA_DIRECTORY)
    path = prepare_development_database(database_path)
    print(f"Created {path}: current schema, three development domains, no deliverable accounts. No provider calls made.")


if __name__ == "__main__":
    main()
