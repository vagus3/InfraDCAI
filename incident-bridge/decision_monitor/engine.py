from __future__ import annotations

import operator
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
    findings = scan_securestring_parameters(scan_root)
    generated = [f for f in findings if f["kind"] == "generated_secret"]

    status = DecisionStatus.VIOLATED if findings else DecisionStatus.VALID
    if findings:
        summary = (
            f"Terraform manages {len(findings)} SecureString parameter(s); "
            f"{len(generated)} of them generate the secret themselves. "
            "Provider refresh writes the decrypted value into state in both cases."
        )
    else:
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
