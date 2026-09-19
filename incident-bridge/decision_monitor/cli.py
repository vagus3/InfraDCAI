from __future__ import annotations

import argparse
import json
from pathlib import Path

from .engine import acknowledgement_state, evaluate
from .models import DecisionStatus
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
            if d.get("rule", {}).get("type") == "terraform_securestring_ownership"
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
    raise SystemExit(exit_code(results))


def exit_code(results: list) -> int:
    """Non-zero when a violation has nobody's name on it.

    Reporting a violation and then exiting 0 is how a checker becomes
    decoration: CI stays green, the finding scrolls past, and the tool has
    taught everyone to ignore it.

    An acknowledged violation is different -- somebody wrote down that they are
    shipping with it and when they will revisit -- so it prints loudly but does
    not block. "Acknowledged" has to mean something, though: the record must be
    complete, unexpired, and bound to the findings that were actually reviewed.
    A record that merely exists is a permanent bypass wearing a date.
    """
    blocking = [
        r
        for r in results
        if r.status == DecisionStatus.VIOLATED and acknowledgement_state(r) != "active"
    ]
    return 1 if blocking else 0


if __name__ == "__main__":
    main()
