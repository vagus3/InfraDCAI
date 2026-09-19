import json
from datetime import datetime, timezone

from incidentops.external import external_incident_summary
from incidentops.models import (
    Incident,
    IncidentFact,
    IncidentStatus,
    Severity,
    SignalSource,
)


def _incident_with_customer_body(secret_body: str) -> Incident:
    now = datetime.now(timezone.utc)
    fact = IncidentFact(
        source=SignalSource.CUSTOMER_EMAIL,
        kind="customer_report",
        summary="Someone: subject line",
        details={"body": secret_body, "message_id": "msg-1"},
        observed_at=now,
    )
    return Incident(
        id="INC-TEST0001",
        tenant="t",
        status=IncidentStatus.OPEN,
        severity=Severity.SEV3,
        title="Customer report: request failures",
        trigger=SignalSource.CUSTOMER_EMAIL,
        symptom="request failures",
        opened_at=now,
        updated_at=now,
        facts=[fact],
    )


def test_external_summary_excludes_raw_customer_email_body():
    secret = "여기에 고객 계좌번호나 다른 민감 정보가 들어있다고 가정"
    incident = _incident_with_customer_body(secret)

    summary = external_incident_summary(incident)

    assert secret not in json.dumps(summary, ensure_ascii=False)
    # The constructed, short summary is still present -- only the raw body,
    # which lives in fact.details, is excluded.
    assert summary["facts"][0]["summary"] == "Someone: subject line"
    assert "details" not in summary["facts"][0]


def test_external_summary_has_no_details_key_anywhere():
    incident = _incident_with_customer_body("secret")
    summary = external_incident_summary(incident)

    def _walk(value):
        if isinstance(value, dict):
            assert "details" not in value
            for v in value.values():
                _walk(v)
        elif isinstance(value, list):
            for v in value:
                _walk(v)

    _walk(summary)
