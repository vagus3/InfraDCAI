import asyncio
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from incidentops.incident_store import IncidentStore
from incidentops.models import CustomerEmail, IncidentStatus, TelemetrySignal, VerificationRequest
from incidentops.service import IncidentAlreadyResolved, IncidentTracker


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


# --- CODE_RULES.md 2026-09-20 reproductions --------------------------------
# Each of these reproduced a concrete bug before the fix. Kept as regression
# tests rather than deleted once green, per CODE_RULES.md #7: a bug found in a
# security/data/state-transition path gets a test with the real failing input.


def test_naive_datetime_is_rejected_not_silently_assumed_utc():
    with pytest.raises(Exception):
        TelemetrySignal(tenant="e", metric="readiness", value=1.0, observed_at=datetime.now())


def test_future_dated_signal_falls_out_of_the_correlation_window(tmp_path):
    store = IncidentStore(tmp_path / "test.db")
    now = datetime.now(timezone.utc)

    # +09:00 offset one hour in the past, and a signal dated a day in the
    # future -- the exact pair from the reproduction. Before the fix, both
    # came back from a 30-minute window because the query only bounded the
    # lower end and compared ISO strings with mixed offsets.
    near_past_other_offset = TelemetrySignal(
        tenant="e",
        metric="p95_latency",
        value=1.0,
        observed_at=(now - timedelta(hours=1)).astimezone(timezone(timedelta(hours=9))),
    )
    far_future = TelemetrySignal(
        tenant="e", metric="p95_latency", value=1.0, observed_at=now + timedelta(days=1)
    )
    store.add_telemetry(near_past_other_offset)
    store.add_telemetry(far_future)

    result = store.recent_telemetry("e", minutes=30, now=now)
    assert result == []


def test_resent_customer_email_does_not_duplicate_the_fact(tmp_path):
    tracker = make_tracker(tmp_path)
    email = CustomerEmail(
        tenant="f",
        customer="customer",
        subject="답변이 안 옵니다",
        body="오류가 발생합니다",
        message_id="msg-1",
    )

    first = asyncio.run(tracker.record_customer_email(email))
    second = asyncio.run(tracker.record_customer_email(email))

    assert second.id == first.id
    customer_facts = [f for f in second.facts if f.kind == "customer_report"]
    assert len(customer_facts) == 1


def test_resolved_incident_rejects_further_transitions(tmp_path):
    tracker = make_tracker(tmp_path)
    incident = asyncio.run(
        tracker.record_telemetry(TelemetrySignal(tenant="h", metric="readiness", value=0))
    )
    resolved = tracker.verify(
        incident.id,
        VerificationRequest(ci_passed=True, deploy_succeeded=True, production_healthy=True),
    )
    assert resolved.status == IncidentStatus.RESOLVED

    with pytest.raises(IncidentAlreadyResolved):
        tracker.verify(
            incident.id,
            VerificationRequest(ci_passed=True, deploy_succeeded=True, production_healthy=True),
        )
    with pytest.raises(IncidentAlreadyResolved):
        asyncio.run(tracker.triage_incident(incident.id))


def test_unrelated_failure_a_day_later_does_not_merge_into_the_old_incident(tmp_path):
    tracker = make_tracker(tmp_path)
    now = datetime.now(timezone.utc)

    first = asyncio.run(
        tracker.record_telemetry(
            TelemetrySignal(
                tenant="g", metric="readiness", value=0, endpoint="/login", observed_at=now
            )
        )
    )
    assert first is not None

    second = asyncio.run(
        tracker.record_telemetry(
            TelemetrySignal(
                tenant="g",
                metric="p95_latency",
                value=6.0,
                endpoint="/chat/stream",
                observed_at=now + timedelta(days=1),
            )
        )
    )
    assert second is not None
    assert second.id != first.id
