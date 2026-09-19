import asyncio
from datetime import datetime, timezone

from incidentops.models import (
    Incident,
    IncidentFact,
    IncidentStatus,
    IncidentType,
    Severity,
    SignalSource,
)
from incidentops.triage import IncidentTriage


def _incident(fact: IncidentFact, symptom: str = "error rate exceeded") -> Incident:
    now = datetime.now(timezone.utc)
    return Incident(
        id="INC-TEST0002",
        tenant="t",
        status=IncidentStatus.OPEN,
        severity=Severity.SEV3,
        title=f"Service alert: {symptom}",
        trigger=SignalSource.TELEMETRY,
        symptom=symptom,
        opened_at=now,
        updated_at=now,
        facts=[fact],
    )


def test_deployment_sha_is_a_low_confidence_hypothesis_not_a_confirmed_cause():
    fact = IncidentFact(
        source=SignalSource.TELEMETRY,
        kind="alert",
        summary="error rate 31.0% exceeded 5.0%",
        details={"deployment_sha": "bad-v19"},
    )
    result = asyncio.run(IncidentTriage().run(_incident(fact)))

    assert result.incident_type == IncidentType.CODE_REGRESSION
    assert result.confidence == "low"
    assert "correlation, not a confirmed cause" in result.probable_cause
    assert "bad-v19" in result.probable_cause


def test_structured_dependency_signal_keeps_medium_confidence():
    fact = IncidentFact(
        source=SignalSource.TELEMETRY,
        kind="alert",
        summary="readiness failed",
        details={"dependency": "postgres"},
    )
    result = asyncio.run(IncidentTriage().run(_incident(fact, symptom="readiness failed")))

    assert result.incident_type == IncidentType.DEPENDENCY_FAILURE
    assert result.confidence == "medium"
