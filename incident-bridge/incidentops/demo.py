from __future__ import annotations

import argparse
import asyncio
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

from incidentops.incident_store import IncidentStore
from incidentops.models import CustomerEmail, TelemetrySignal, VerificationRequest
from incidentops.service import IncidentTracker


async def monitor_detected(tracker: IncidentTracker):
    print("\n=== monitor-detected incident ===")
    now = datetime.now(timezone.utc)
    incident = await tracker.record_telemetry(
        TelemetrySignal(
            tenant="company-a",
            metric="5xx_rate",
            value=0.31,
            unit="ratio",
            endpoint="/chat",
            deployment_sha="bad-v19",
            observed_at=now,
            labels={"previous_sha": "good-v18"},
        )
    )
    print(f"opened: {incident.id} {incident.title}")

    same_incident = await tracker.record_customer_email(
        CustomerEmail(
            tenant="company-a",
            customer="Acme Ops",
            subject="API 오류가 계속 발생합니다",
            body="14시쯤부터 /chat 요청이 자주 실패합니다.",
            received_at=now + timedelta(minutes=6),
        )
    )
    print(f"customer report matched: lead={same_incident.detection_lead_seconds:.0f}s")

    triaged = await tracker.triage_incident(same_incident.id)
    print(f"triage: {triaged.triage.incident_type.value} / {triaged.triage.probable_cause}")
    _, task = tracker.create_fix_task(same_incident.id)
    print(f"fix task: {task}")

    resolved = tracker.verify(
        same_incident.id,
        VerificationRequest(
            ci_passed=True,
            deploy_succeeded=True,
            production_healthy=True,
            notes="Rolled back bad-v19 to good-v18; 5xx rate returned below 1%.",
        ),
    )
    print(f"result: {resolved.status.value}")


async def customer_reported(tracker: IncidentTracker):
    print("\n=== customer-reported incident ===")
    now = datetime.now(timezone.utc)
    await tracker.record_telemetry(
        TelemetrySignal(
            tenant="company-b",
            metric="p95_latency",
            value=3.7,
            unit="seconds",
            endpoint="/chat",
            baseline=1.1,
            observed_at=now - timedelta(minutes=2),
        )
    )

    incident = await tracker.record_customer_email(
        CustomerEmail(
            tenant="company-b",
            customer="Beta Support",
            subject="응답 속도가 어제부터 너무 느립니다",
            body="장애 메시지는 없지만 평소 1초 정도였던 응답이 3~4초씩 걸립니다.",
            received_at=now,
        )
    )
    print(f"opened: {incident.id} source={incident.trigger.value}")
    print(f"alert gap: {incident.alert_gap}")

    triaged = await tracker.triage_incident(incident.id)
    print(f"triage: {triaged.triage.incident_type.value}")
    print("customer message:\n" + tracker.reports.customer_message(triaged))


async def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "scenario",
        choices=["monitor", "customer", "all"],
        default="all",
        nargs="?",
    )
    args = parser.parse_args()

    with tempfile.TemporaryDirectory() as tmpdir:
        tracker = IncidentTracker(IncidentStore(Path(tmpdir) / "demo.db"))
        tracker.fix_tasks.artifact_dir = Path(tmpdir) / "artifacts"
        tracker.fix_tasks.artifact_dir.mkdir()
        tracker.reports.artifact_dir = tracker.fix_tasks.artifact_dir

        if args.scenario in {"monitor", "all"}:
            await monitor_detected(tracker)
        if args.scenario in {"customer", "all"}:
            await customer_reported(tracker)


if __name__ == "__main__":
    asyncio.run(main())
