from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


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


class CustomerEmail(BaseModel):
    tenant: str
    customer: str
    subject: str
    body: str
    received_at: datetime = Field(default_factory=utcnow)
    message_id: str | None = None


class IncidentFact(BaseModel):
    source: SignalSource
    kind: str
    summary: str
    details: dict[str, Any] = Field(default_factory=dict)
    observed_at: datetime = Field(default_factory=utcnow)


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


class VerificationRequest(BaseModel):
    ci_passed: bool
    deploy_succeeded: bool
    production_healthy: bool
    decision_check_passed: bool | None = None
    notes: str = ""
