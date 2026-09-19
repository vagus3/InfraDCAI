from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field, field_validator


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _require_aware_utc(value: datetime) -> datetime:
    """Reject naive datetimes and normalize the rest to UTC.

    Storage compares these values as ISO-8601 strings (see incident_store.py),
    which only sorts correctly when every string uses the same offset. A naive
    value would force a silent guess about its zone, and a non-UTC offset would
    compare incorrectly against a UTC one even though both are valid instants.
    Rejecting naive input is the explicit policy DESIGN.md #2 asks for, instead
    of silently assuming UTC.
    """
    if value.tzinfo is None:
        raise ValueError(
            "naive datetime is not accepted; include a UTC offset (e.g. trailing Z or +09:00)"
        )
    return value.astimezone(timezone.utc)


class SignalSource(str, Enum):
    TELEMETRY = "telemetry"
    CUSTOMER_EMAIL = "customer_email"
    DECISION_MONITOR = "decision_monitor"


class IncidentStatus(str, Enum):
    OPEN = "OPEN"
    TRIAGED = "TRIAGED"
    READY_FOR_FIX = "READY_FOR_FIX"
    FIX_IN_PROGRESS = "FIX_IN_PROGRESS"
    VERIFYING = "VERIFYING"
    RESOLVED = "RESOLVED"
    ESCALATED = "ESCALATED"


class IncidentType(str, Enum):
    CODE_REGRESSION = "CODE_REGRESSION"
    INFRA_CONFIG = "INFRA_CONFIG"
    DEPENDENCY_FAILURE = "DEPENDENCY_FAILURE"
    CAPACITY = "CAPACITY"
    UNKNOWN = "UNKNOWN"


class Severity(str, Enum):
    SEV1 = "SEV1"
    SEV2 = "SEV2"
    SEV3 = "SEV3"


class TelemetrySignal(BaseModel):
    tenant: str
    metric: str
    value: float
    unit: str = ""
    endpoint: str | None = None
    baseline: float | None = None
    deployment_sha: str | None = None
    dependency: str | None = None
    observed_at: datetime = Field(default_factory=utcnow)
    labels: dict[str, str] = Field(default_factory=dict)

    _normalize_observed_at = field_validator("observed_at")(_require_aware_utc)


class CustomerEmail(BaseModel):
    tenant: str
    customer: str
    subject: str
    body: str
    received_at: datetime = Field(default_factory=utcnow)
    message_id: str | None = None

    _normalize_received_at = field_validator("received_at")(_require_aware_utc)


class IncidentFact(BaseModel):
    source: SignalSource
    kind: str
    summary: str
    details: dict[str, Any] = Field(default_factory=dict)
    observed_at: datetime = Field(default_factory=utcnow)

    _normalize_observed_at = field_validator("observed_at")(_require_aware_utc)


class TriageResult(BaseModel):
    incident_type: IncidentType
    probable_cause: str
    confidence: str
    facts: list[str]
    next_step: str
    allowed_paths: list[str] = Field(default_factory=list)
    checks: list[str] = Field(default_factory=list)


class Incident(BaseModel):
    id: str
    tenant: str
    status: IncidentStatus
    severity: Severity
    title: str
    trigger: SignalSource
    symptom: str
    opened_at: datetime
    updated_at: datetime
    facts: list[IncidentFact] = Field(default_factory=list)
    triage: TriageResult | None = None
    alert_gap: str | None = None
    detection_lead_seconds: float | None = None
    resolution_note: str | None = None

    _normalize_opened_at = field_validator("opened_at")(_require_aware_utc)
    _normalize_updated_at = field_validator("updated_at")(_require_aware_utc)


class VerificationRequest(BaseModel):
    ci_passed: bool
    deploy_succeeded: bool
    production_healthy: bool
    decision_check_passed: bool | None = None
    notes: str = ""
