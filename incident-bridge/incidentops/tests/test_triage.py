import asyncio
import json
from datetime import datetime, timezone

import httpx
import pytest

from incidentops.config import settings
from incidentops.models import (
    Incident,
    IncidentFact,
    IncidentStatus,
    IncidentType,
    Severity,
    SignalSource,
)
from incidentops.triage import IncidentTriage


@pytest.fixture(autouse=True)
def no_live_triage(monkeypatch):
    monkeypatch.setattr(settings, "triage_webhook_url", None)


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


@pytest.mark.parametrize("response_kind", ["success", "server_error", "invalid_json", "invalid_schema", "timeout"])
def test_webhook_uses_reduced_payload_and_falls_back_safely(monkeypatch, response_kind):
    private_text = "synthetic-private-customer-data"
    incident = _incident(IncidentFact(
        source=SignalSource.CUSTOMER_EMAIL,
        kind="customer_report",
        summary=private_text,
        details={"body": private_text, "customer": private_text},
    ))
    expected = IncidentTriage()._from_rules(incident)
    incident.triage = expected  # Previous analysis quotes customer facts too.
    requests = []

    def handle(request):
        requests.append(request)
        payload = json.loads(request.content)
        assert private_text not in request.content.decode()
        assert "details" not in payload["incident"]["facts"][0]
        if response_kind == "timeout":
            raise httpx.ReadTimeout("synthetic timeout", request=request)
        if response_kind == "server_error":
            return httpx.Response(503)
        if response_kind == "invalid_json":
            return httpx.Response(200, text="not json")
        if response_kind == "invalid_schema":
            return httpx.Response(200, json=["not a triage result"])
        return httpx.Response(200, json={"triage": expected.model_dump(mode="json")})

    client_class = httpx.AsyncClient
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kw: client_class(
        transport=httpx.MockTransport(handle), **kw,
    ))
    monkeypatch.setattr(settings, "triage_webhook_url", "https://triage.invalid")
    result = asyncio.run(IncidentTriage().run(incident))
    assert len(requests) == 1
    if response_kind == "success":
        assert result == expected
    else:
        assert result.incident_type == IncidentType.UNKNOWN
        assert result.allowed_paths == []
        assert "External triage unavailable" in result.probable_cause
