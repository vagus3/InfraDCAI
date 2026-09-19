from __future__ import annotations

import json
from .models import DecisionStatus, Result


SYMBOLS = {
    DecisionStatus.VALID: "✓",
    DecisionStatus.VIOLATED: "✕",
    DecisionStatus.REVISIT_REQUIRED: "⚠",
    DecisionStatus.UNKNOWN: "?",
}


def print_results(results: list[Result], verbose: bool = True) -> None:
    print("\nARCHITECTURE DECISION HEALTH\n")
    for result in results:
        print(f"{SYMBOLS[result.status]} {result.decision_id:<8} {result.status.value:<17} {result.title}")
        if verbose:
            print(f"  Decision: {result.statement}")
            for evidence in result.evidence:
                print(f"  Evidence: {evidence.summary}")
                if result.status != DecisionStatus.VALID and evidence.details:
                    compact = json.dumps(evidence.details, ensure_ascii=False, indent=2)
                    print("  Details:")
                    for line in compact.splitlines():
                        print(f"    {line}")
            ack = getattr(result, "acknowledgement", None)
            if ack:
                print(
                    f"  Accepted: {ack.get('accepted_on')} by {ack.get('owner')}, "
                    f"revisit by {ack.get('expires_on')}"
                )
                print(f"            {ack.get('reason')}")
            print(f"  Why: {result.reason}\n")

    counts = {status: 0 for status in DecisionStatus}
    for result in results:
        counts[result.status] += 1
    print(
        "Summary: "
        + ", ".join(f"{status.value}={counts[status]}" for status in DecisionStatus)
    )
