from __future__ import annotations

import time
from typing import Any


def _require_boto3():
    try:
        import boto3  # type: ignore
    except ImportError as exc:
        raise RuntimeError(
            "Live AWS scanning requires boto3. Install decision_monitor/requirements.txt first."
        ) from exc
    return boto3


def _discover_instance(ec2, project: str) -> dict[str, Any]:
    response = ec2.describe_instances(
        Filters=[
            {"Name": "tag:Project", "Values": [project]},
            {"Name": "instance-state-name", "Values": ["pending", "running", "stopping", "stopped"]},
        ]
    )
    instances = [instance for reservation in response["Reservations"] for instance in reservation["Instances"]]
    if not instances:
        raise RuntimeError(f"No EC2 instance found with Project={project!r}")
    if len(instances) > 1:
        instances.sort(key=lambda item: item.get("LaunchTime"), reverse=True)
    return instances[0]


def _security_groups(ec2, instance: dict[str, Any]) -> list[dict[str, Any]]:
    ids = [item["GroupId"] for item in instance.get("SecurityGroups", [])]
    if not ids:
        return []
    response = ec2.describe_security_groups(GroupIds=ids)
    groups = []
    for group in response["SecurityGroups"]:
        ingress = []
        for perm in group.get("IpPermissions", []):
            for item in perm.get("IpRanges", []):
                ingress.append(
                    {
                        "protocol": perm.get("IpProtocol"),
                        "from_port": perm.get("FromPort"),
                        "to_port": perm.get("ToPort"),
                        "cidr": item.get("CidrIp"),
                    }
                )
            for item in perm.get("Ipv6Ranges", []):
                ingress.append(
                    {
                        "protocol": perm.get("IpProtocol"),
                        "from_port": perm.get("FromPort"),
                        "to_port": perm.get("ToPort"),
                        "cidr": item.get("CidrIpv6"),
                    }
                )
        groups.append({"id": group["GroupId"], "name": group["GroupName"], "ingress": ingress})
    return groups


def _runtime_evidence(ssm, instance_id: str) -> dict[str, float | None]:
    # Normalized 1-minute load is used as fast, cheap demo evidence. It is not
    # identical to CPUUtilization; the UI/report must label it correctly.
    command = (
        "LOAD=$(cut -d' ' -f1 /proc/loadavg); "
        "CPU=$(nproc); "
        "awk -v l=\"$LOAD\" -v c=\"$CPU\" 'BEGIN { printf \"normalized_load_pct=%.2f\\n\", (l/c)*100 }'"
    )
    response = ssm.send_command(
        InstanceIds=[instance_id],
        DocumentName="AWS-RunShellScript",
        Parameters={"commands": [command]},
        TimeoutSeconds=30,
    )
    command_id = response["Command"]["CommandId"]
    deadline = time.time() + 30
    while time.time() < deadline:
        try:
            result = ssm.get_command_invocation(CommandId=command_id, InstanceId=instance_id)
        except ssm.exceptions.InvocationDoesNotExist:
            time.sleep(1)
            continue
        status = result["Status"]
        if status == "Success":
            for line in result.get("StandardOutputContent", "").splitlines():
                if line.startswith("normalized_load_pct="):
                    return {"host.normalized_load_pct": float(line.split("=", 1)[1])}
            return {"host.normalized_load_pct": None}
        if status in {"Cancelled", "TimedOut", "Failed"}:
            return {"host.normalized_load_pct": None}
        time.sleep(1)
    return {"host.normalized_load_pct": None}


def collect(region: str, project: str) -> dict[str, Any]:
    boto3 = _require_boto3()
    session = boto3.Session(region_name=region)
    ec2 = session.client("ec2")
    ssm = session.client("ssm")

    instance = _discover_instance(ec2, project)
    instance_id = instance["InstanceId"]
    snapshot: dict[str, Any] = {
        "meta": {"region": region, "project": project, "instance_id": instance_id},
        "security_groups": _security_groups(ec2, instance),
        "metrics": {},
    }
    if instance.get("State", {}).get("Name") == "running":
        snapshot["metrics"].update(_runtime_evidence(ssm, instance_id))
    return snapshot
