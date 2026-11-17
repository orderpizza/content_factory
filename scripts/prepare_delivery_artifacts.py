"""Export unapproved JPEG candidates from an English PNG review; never alter its DB."""
import argparse
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from workflow.delivery_artifacts import prepare_review_bundle
from workflow.offline import offline_only
from workflow.store import WorkflowStore


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", type=Path, required=True)
    parser.add_argument("--review-id", type=int, required=True)
    parser.add_argument("--artifacts", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True, help="new directory with an existing parent")
    args = parser.parse_args()
    with offline_only(), WorkflowStore(args.database, read_only=True) as store:
        prepare_review_bundle(store, args.review_id, artifact_root=args.artifacts, output=args.output)
    print(f"Unapproved JPEG candidate: {args.output.resolve() / 'candidate.json'}")
    print("New exact-JPEG, caption, alt-text and destination review required. No posting authorization created.")


if __name__ == "__main__":
    main()
