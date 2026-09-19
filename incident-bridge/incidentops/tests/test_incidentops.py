import asyncio
from datetime import datetime, timedelta, timezone
from pathlib import Path

from incidentops.incident_store import IncidentStore
from incidentops.models import CustomerEmail, IncidentStatus, TelemetrySignal, VerificationRequest
from incidentops.service import IncidentTracker


def make_tracker(tmp_path: Path) -> IncidentTracker:
    tracker = IncidentTracker(IncidentStore(tmp_path / "test.db"))
    tracker.fix_tasks.artifact_dir = tmp_path / "artifacts"
    tracker.fix_tasks.artifact_dir.mkdir()
    tracker.reports.artifact_dir = tracker.fix_tasks.artifact_dir
    return tracker


def test_match_customer_email_to_existing_incident(tmp_path):
    tracker = make_tracker(tmp_path)
    now = datetime.now(timezone.utc)

    incident = asyncio.run(
        tracker.record_telemetry(
            TelemetrySignal(
                tenant="a",
                metric="5xx_rate",
                value=0.30,
                observed_at=now,
                deployment_sha="bad123",
            )
        )
    )
    assert incident is not None

    same_incident = asyncio.run(
        tracker.record_customer_email(
            CustomerEmail(
                tenant="a",
                customer="customer",
                subject="error",
                body="API error",
                received_at=now + timedelta(minutes=5),
            )
        )
    )
    assert same_incident.id == incident.id
    assert same_incident.detection_lead_seconds == 300


def test_customer_email_finds_subthreshold_latency_regression(tmp_path):
    tracker = make_tracker(tmp_path)
    now = datetime.now(timezone.utc)

    assert asyncio.run(
        tracker.record_telemetry(
            TelemetrySignal(
                tenant="b",
                metric="p95_latency",
                value=3.6,
                baseline=1.0,
                observed_at=now - timedelta(minutes=1),
            )
        )
    ) is None

    incident = asyncio.run(
        tracker.record_customer_email(
            CustomerEmail(
                tenant="b",
                customer="customer",
                subject="응답이 느립니다",
                body="평소보다 느려졌어요",
                received_at=now,
            )
        )
    )
    assert incident.alert_gap is not None
    assert any(fact.kind == "latency_regression" for fact in incident.facts)


def test_resolution_requires_live_service_check(tmp_path):
    tracker = make_tracker(tmp_path)
    incident = asyncio.run(
        tracker.record_telemetry(
            TelemetrySignal(
                tenant="c",
                metric="5xx_rate",
                value=0.2,
                deployment_sha="bad",
            )
        )
    )
    asyncio.run(tracker.triage_incident(incident.id))

    resolved = tracker.verify(
        incident.id,
        VerificationRequest(
            ci_passed=True,
            deploy_succeeded=True,
            production_healthy=True,
            notes="recovered",
        ),
    )
    assert resolved.status == IncidentStatus.RESOLVED


def test_failed_live_check_escalates(tmp_path):
    tracker = make_tracker(tmp_path)
    incident = asyncio.run(
        tracker.record_telemetry(
            TelemetrySignal(tenant="d", metric="readiness", value=0)
        )
    )

    result = tracker.verify(
        incident.id,
        VerificationRequest(
            ci_passed=True,
            deploy_succeeded=True,
            production_healthy=False,
        ),
    )
    assert result.status == IncidentStatus.ESCALATED
