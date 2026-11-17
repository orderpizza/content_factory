"""Explicit, local-only delivery rehearsal; default invocation cannot send."""
import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from workflow.delivery_simulation import (
    initialize_simulation, offline_only, simulation_store, post_now, run_once, report, local_relay,
)
from workflow.delivery import PublicationReconciliationWorker, R2CleanupWorker


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    init = commands.add_parser("init", help="create synthetic PNGs, JPEG candidates and a fresh isolated DB; no approval")
    init.add_argument("--workspace", type=Path, help="new directory only; default: a new retained temporary directory")
    for name in ("report", "post-now", "run", "cancel", "reconcile", "resolve", "cleanup"):
        command = commands.add_parser(name)
        command.add_argument("--workspace", type=Path, required=True)
        if name == "post-now":
            command.add_argument("--review-id", type=int, required=True)
            command.add_argument("--row-version", type=int, required=True)
            command.add_argument("--review-identity", required=True)
            command.add_argument("--destination", required=True)
        if name in {"post-now", "cancel", "reconcile", "resolve"}:
            command.add_argument("--command-id", required=True)
        if name in {"cancel", "reconcile"}:
            command.add_argument("--post-id", type=int, required=True)
        if name in {"cancel", "resolve"}:
            command.add_argument("--row-version", type=int, required=True)
        if name == "run":
            command.add_argument("--outcome", choices=("success", "unknown", "outage"), default="success")
        if name == "resolve":
            command.add_argument("--request-id", type=int, required=True)
            command.add_argument("--check-id", type=int, required=True)
            command.add_argument("--decision", choices=("published", "not_published_cancel", "leave_unknown"), required=True)
            command.add_argument("--note", required=True)
    args = parser.parse_args()
    with offline_only():
        if args.command == "init":
            root = initialize_simulation(args.workspace)
            with simulation_store(root, read_only=True) as store:
                result = report(store)
            result["workspace"] = str(root)
        else:
            with simulation_store(args.workspace, read_only=args.command == "report") as store:
                if args.command == "post-now":
                    post_now(store, review_id=args.review_id, row_version=args.row_version,
                             identity=args.review_identity, destination=args.destination, command_id=args.command_id)
                elif args.command == "run":
                    run_once(store, args.workspace, outcome=args.outcome)
                elif args.command == "cancel":
                    store.cancel_delivery(args.post_id, row_version=args.row_version, command_id=args.command_id)
                elif args.command == "reconcile":
                    store.request_publication_reconciliation(args.post_id, command_id=args.command_id)
                    PublicationReconciliationWorker(store).run_once()
                elif args.command == "resolve":
                    store.resolve_publication_unknown(args.request_id, reconciliation_check_id=args.check_id,
                        decision=args.decision, note=args.note, row_version=args.row_version, command_id=args.command_id)
                elif args.command == "cleanup":
                    worker = R2CleanupWorker(store, relay_factory=lambda config: local_relay(args.workspace))
                    while worker.run_once() is not None:
                        pass
                result = report(store)
        print(json.dumps(result, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
