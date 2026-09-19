from __future__ import annotations

import hashlib
import json
import operator
from datetime import date
from pathlib import Path
from typing import Any

from .models import DecisionStatus, Evidence, Result
from .terraform_scan import scan_securestring_parameters


OPS = {
    ">": operator.gt,
    ">=": operator.ge,
    "<": operator.lt,
    "<=": operator.le,
    "==": operator.eq,
}


def _evaluate_public_ingress(decision: dict[str, Any], snapshot: dict[str, Any]) -> Result:
    rule = decision["rule"]
    matches = []
    for sg in snapshot.get("security_groups", []):
        for ingress in sg.get("ingress", []):
            cidr = ingress.get("cidr")
            protocol = ingress.get("protocol")
            from_port = ingress.get("from_port")
            to_port = ingress.get("to_port")
            port = rule["port"]
            protocol_matches = protocol in (rule["protocol"], "-1")
            port_matches = protocol == "-1" or (
                from_port is not None and to_port is not None and from_port <= port <= to_port
            )
            if cidr in rule["cidrs"] and protocol_matches and port_matches:
                matches.append({"security_group": sg.get("id", sg.get("name")), **ingress})

    status = DecisionStatus.VIOLATED if matches else DecisionStatus.VALID
    summary = (
        f"Found {len(matches)} public SSH ingress rule(s)."
        if matches
        else "No public SSH ingress found."
    )
    return Result(
        decision_id=decision["id"],
        title=decision["title"],
        status=status,
        statement=decision["statement"],
        reason=decision["reason"],
        evidence=[Evidence(source="aws.ec2.security_groups", summary=summary, details={"matches": matches})],
    )


def _evaluate_metric(decision: dict[str, Any], snapshot: dict[str, Any]) -> Result:
    trigger = decision["revisit_trigger"]
    metric_name = trigger["metric"]
    metrics = snapshot.get("metrics", {})
    if metric_name not in metrics or metrics[metric_name] is None:
        return Result(
            decision_id=decision["id"],
            title=decision["title"],
            status=DecisionStatus.UNKNOWN,
            statement=decision["statement"],
            reason=decision["reason"],
            evidence=[Evidence(source="runtime", summary=f"No evidence for {metric_name}.")],
        )

    actual = float(metrics[metric_name])
    threshold = float(trigger["threshold"])
    op = OPS[trigger["operator"]]
    tripped = op(actual, threshold)
    status = DecisionStatus.REVISIT_REQUIRED if tripped else DecisionStatus.VALID
    return Result(
        decision_id=decision["id"],
        title=decision["title"],
        status=status,
        statement=decision["statement"],
        reason=decision["reason"],
        evidence=[
            Evidence(
                source="runtime",
                summary=f"{metric_name}={actual:.1f}, trigger {trigger['operator']} {threshold:.1f}",
                details={"metric": metric_name, "actual": actual, "operator": trigger["operator"], "threshold": threshold},
            )
        ],
    )


def _evaluate_terraform_secret(decision: dict[str, Any], repo_root: Path) -> Result:
    scan_root = repo_root / decision["rule"].get("path", ".")
    findings = scan_securestring_parameters(scan_root, relative_to=repo_root)
    violations = [f for f in findings if f["kind"] in ("generated_secret", "terraform_managed")]
    generated = [f for f in violations if f["kind"] == "generated_secret"]
    unscannable = [f for f in findings if f["kind"] == "no_value_argument"]

    # A resource this scanner cannot classify is not the same as one it
    # confirmed compliant. Reporting it as VALID would assert a write-only/
    # ephemeral shape (or any other explanation) without the provider
    # evidence to back that up -- exactly the overclaim CODE_RULES.md flagged
    # in the test that used to expect VALID here.
    if violations:
        status = DecisionStatus.VIOLATED
        summary = (
            f"Terraform manages {len(violations)} SecureString parameter(s); "
            f"{len(generated)} of them generate the secret themselves. "
            "Provider refresh writes the decrypted value into state in both cases."
        )
    elif unscannable:
        status = DecisionStatus.UNKNOWN
        summary = (
            f"{len(unscannable)} SecureString parameter(s) have no `value` argument this "
            "scanner can read. Compliance is not confirmed without terraform validate/plan "
            "or provider-version evidence for write-only arguments."
        )
    else:
        status = DecisionStatus.VALID
        summary = "Terraform does not manage the value of any SecureString parameter."

    return Result(
        decision_id=decision["id"],
        title=decision["title"],
        status=status,
        statement=decision["statement"],
        reason=decision["reason"],
        evidence=[Evidence(source="terraform.source", summary=summary, details={"findings": findings})],
        acknowledgement=decision.get("acknowledgement"),
    )


def evaluate(decisions: list[dict[str, Any]], snapshot: dict[str, Any], repo_root: Path) -> list[Result]:
    results = []
    for decision in decisions:
        rule_type = decision.get("rule", {}).get("type")
        trigger_type = decision.get("revisit_trigger", {}).get("type")
        if rule_type == "no_public_ingress":
            results.append(_evaluate_public_ingress(decision, snapshot))
        elif rule_type == "terraform_securestring_ownership":
            results.append(_evaluate_terraform_secret(decision, repo_root))
        elif trigger_type == "metric_threshold":
            results.append(_evaluate_metric(decision, snapshot))
        else:
            results.append(
                Result(
                    decision_id=decision["id"],
                    title=decision["title"],
                    status=DecisionStatus.UNKNOWN,
                    statement=decision["statement"],
                    reason="Unsupported decision rule.",
                )
            )
    return results


# ---------------------------------------------------------------------------
# Acknowledgements
#
# An acknowledged violation does not block CI. That makes the acknowledgement a
# security control, so it needs the properties a control needs: it has to
# expire, it has to be complete, and it has to be bound to the finding somebody
# actually looked at. Without the last one, accepting "three parameters
# Terraform manages" would go on silencing the check after a fourth appears, or
# after one of them starts generating its own secret again.
# ---------------------------------------------------------------------------

REQUIRED_ACK_FIELDS = ("accepted_on", "expires_on", "owner", "reason", "fingerprint")


def finding_fingerprint(result: Result) -> str:
    """Stable digest of what the check actually found."""
    payload = [{"source": e.source, "details": e.details} for e in result.evidence]
    canonical = json.dumps(payload, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:16]


def acknowledgement_state(result: Result, today: date | None = None) -> str:
    """One of: none, malformed, expired, stale, active.

    Only "active" suppresses a failure. Every other outcome, including a
    malformed record, blocks -- a control that cannot be read is not a control.
    """
    ack = result.acknowledgement
    if not ack:
        return "none"
    if any(not ack.get(field) for field in REQUIRED_ACK_FIELDS):
        return "malformed"
    try:
        expires = date.fromisoformat(str(ack["expires_on"]))
    except (TypeError, ValueError):
        return "malformed"
    if expires < (today or date.today()):
        return "expired"
    if str(ack["fingerprint"]) != finding_fingerprint(result):
        return "stale"
    return "active"
