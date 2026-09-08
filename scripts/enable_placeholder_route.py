"""Register one non-deliverable local fixture route for an end-to-end demo.

This is intentionally separate from production configuration.  Its account is
synthetic and its Posting Agent remains disabled.
"""

from __future__ import annotations

from argparse import ArgumentParser
from pathlib import Path
import os
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from workflow import WORKFLOW_PIPELINES, WorkflowStore

ROOT = Path(__file__).resolve().parents[1]


def main() -> None:
    parser = ArgumentParser(description=__doc__)
    parser.add_argument("--pipeline", choices=WORKFLOW_PIPELINES, default="english")
    parser.add_argument("--database", default=os.getenv("CONTENT_FACTORY_DB_PATH", str(ROOT / "data" / "content.db")))
    parser.add_argument("--confirm-local-placeholder", action="store_true")
    args = parser.parse_args()
    if not args.confirm_local_placeholder:
        raise SystemExit("Refusing: pass --confirm-local-placeholder for a synthetic, non-deliverable fixture.")
    with WorkflowStore(args.database) as store:
        capability_id = store.register_capability(args.pipeline, enabled=True, generation_ready=True, outputs=[{
            "platform": "instagram", "account": f"fixture_{args.pipeline}",
            "content_format": "instagram_static_carousel_v2", "ready": True,
            "safe_reason": "explicit local placeholder; not a social account",
        }])
    print(f"Registered local placeholder capability {capability_id}; social delivery remains disabled.")


if __name__ == "__main__":
    main()
