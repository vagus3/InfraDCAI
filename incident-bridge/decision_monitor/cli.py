from __future__ import annotations

import argparse
import json
from pathlib import Path

from .engine import evaluate
from .report import print_results


def _load_decisions(path: Path) -> list[dict]:
    return json.loads(path.read_text(encoding="utf-8"))["decisions"]


def _default_decisions() -> Path:
    return Path(__file__).with_name("decisions.json")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="decision-monitor",
        description="Check whether architecture decisions are violated or due for review.",
    )
    parser.add_argument("--decisions", type=Path, default=_default_decisions())
    sub = parser.add_subparsers(dest="command", required=True)

    repo = sub.add_parser("repo", help="Evaluate repository evidence only.")
    repo.add_argument("--root", type=Path, default=Path("."))

    snap = sub.add_parser("snapshot", help="Evaluate a saved evidence snapshot.")
    snap.add_argument("snapshot", type=Path)
    snap.add_argument("--root", type=Path, default=Path("."))

    live = sub.add_parser("live", help="Collect evidence from the deployed AWS workload.")
    live.add_argument("--root", type=Path, default=Path("."))
    live.add_argument("--region", default="ap-northeast-2")
    live.add_argument("--project", default="mini-chatgpt")

    return parser


def main() -> None:
    args = build_parser().parse_args()
    decisions = _load_decisions(args.decisions)

    if args.command == "repo":
        snapshot = {"security_groups": [], "metrics": {}}
        # Only repo-backed decisions are meaningful in this mode. Others become
        # UNKNOWN rather than accidentally appearing healthy.
        repo_decisions = [
            d
            for d in decisions
            if d.get("rule", {}).get("type") == "terraform_securestring_no_generated_secret"
        ]
        results = evaluate(repo_decisions, snapshot, args.root.resolve())
    elif args.command == "snapshot":
        snapshot = json.loads(args.snapshot.read_text(encoding="utf-8"))
        results = evaluate(decisions, snapshot, args.root.resolve())
    else:
        from .collectors.aws_live import collect

        snapshot = collect(args.region, args.project)
        results = evaluate(decisions, snapshot, args.root.resolve())

    print_results(results)


if __name__ == "__main__":
    main()
