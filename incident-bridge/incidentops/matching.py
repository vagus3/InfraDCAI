from __future__ import annotations

import uuid
from datetime import datetime, timezone

from incidentops.config import settings
from incidentops.incident_store import IncidentStore
from incidentops.models import (
    CustomerEmail,
    Incident,
    IncidentFact,
    IncidentStatus,
    Severity,
    SignalSource,
    TelemetrySignal,
)


def _incident_id() -> str:
    return f"INC-{uuid.uuid4().hex[:8].upper()}"


def _alert_reason(signal: TelemetrySignal) -> str | None:
    metric = signal.metric.lower()
    if metric in {"5xx_rate", "error_rate"} and signal.value >= settings.error_rate_alert_ratio:
        return f"error rate {signal.value:.1%} exceeded {settings.error_rate_alert_ratio:.1%}"
    if metric in {"p95_latency", "latency_p95"} and signal.value >= settings.latency_alert_seconds:
        return f"p95 latency {signal.value:.2f}s exceeded {settings.latency_alert_seconds:.2f}s"
    if metric in {"readiness", "ready"} and signal.value <= 0:
        return "readiness failed"
    return None


def _customer_symptom(email: CustomerEmail) -> str:
    text = f"{email.subject} {email.body}".lower()
    if any(word in text for word in ["느리", "느립", "느려", "slow", "latency", "지연"]):
        return "performance degradation"
    if any(word in text for word in ["500", "오류", "에러", "error", "안 됨", "안됩니다", "fail"]):
        return "request failures"
    if any(word in text for word in ["로그인", "login", "인증", "auth"]):
        return "authentication issue"
    return "customer-reported service issue"


class IncidentMatcher:
    def __init__(self, store: IncidentStore):
        self.store = store

    def add_telemetry(self, signal: TelemetrySignal) -> Incident | None:
        self.store.add_telemetry(signal)
        reason = _alert_reason(signal)
        if not reason:
            return None

        current = self._latest_open_incident(signal.tenant)
        fact = IncidentFact(
            source=SignalSource.TELEMETRY,
            kind="alert",
            summary=reason,
            details=signal.model_dump(mode="json"),
            observed_at=signal.observed_at,
        )
        if current:
            current.facts.append(fact)
            current.updated_at = datetime.now(timezone.utc)
            self.store.save_incident(current)
            return current

        severity = (
            Severity.SEV2
            if signal.metric.lower() in {"5xx_rate", "error_rate"} and signal.value >= 0.2
            else Severity.SEV3
        )
        incident = Incident(
            id=_incident_id(),
            tenant=signal.tenant,
            status=IncidentStatus.OPEN,
            severity=severity,
            title=f"Service alert: {reason}",
            trigger=SignalSource.TELEMETRY,
            symptom=reason,
            opened_at=signal.observed_at,
            updated_at=signal.observed_at,
            facts=[fact],
        )
        self.store.save_incident(incident)
        return incident

    def add_customer_email(self, email: CustomerEmail) -> Incident:
        self.store.add_customer_email(email)
        symptom = _customer_symptom(email)
        recent_signals = self.store.recent_telemetry(email.tenant, settings.correlation_window_minutes)
        current = self._latest_open_incident(email.tenant)

        customer_report = IncidentFact(
            source=SignalSource.CUSTOMER_EMAIL,
            kind="customer_report",
            summary=f"{email.customer}: {email.subject}",
            details={"body": email.body, "message_id": email.message_id, "symptom": symptom},
            observed_at=email.received_at,
        )

        if current:
            current.facts.append(customer_report)
            current.detection_lead_seconds = max(
                0.0, (email.received_at - current.opened_at).total_seconds()
            )
            current.updated_at = email.received_at
            self.store.save_incident(current)
            return current

        related_facts, alert_gap = self._find_subthreshold_regression(recent_signals, symptom)
        incident = Incident(
            id=_incident_id(),
            tenant=email.tenant,
            status=IncidentStatus.OPEN,
            severity=Severity.SEV3,
            title=f"Customer report: {symptom}",
            trigger=SignalSource.CUSTOMER_EMAIL,
            symptom=symptom,
            opened_at=email.received_at,
            updated_at=email.received_at,
            facts=[customer_report] + related_facts,
            alert_gap=alert_gap,
        )
        self.store.save_incident(incident)
        return incident

    def _latest_open_incident(self, tenant: str) -> Incident | None:
        incidents = self.store.open_incidents(tenant)
        return incidents[0] if incidents else None

    def _find_subthreshold_regression(
        self, signals: list[TelemetrySignal], symptom: str
    ) -> tuple[list[IncidentFact], str | None]:
        related_facts: list[IncidentFact] = []
        alert_gap: str | None = None
        if "performance" not in symptom:
            return related_facts, alert_gap

        candidates = [
            signal
            for signal in signals
            if signal.metric.lower() in {"p95_latency", "latency_p95"} and signal.baseline
        ]
        for signal in candidates:
            ratio = signal.value / signal.baseline if signal.baseline else 0
            if ratio >= settings.relative_latency_regression_ratio and signal.value < settings.latency_alert_seconds:
                summary = f"latency rose {ratio:.1f}x from baseline without crossing the alert threshold"
                related_facts.append(
                    IncidentFact(
                        source=SignalSource.TELEMETRY,
                        kind="latency_regression",
                        summary=summary,
                        details=signal.model_dump(mode="json"),
                        observed_at=signal.observed_at,
                    )
                )
                alert_gap = (
                    f"The {settings.latency_alert_seconds:.1f}s latency alert did not fire even though "
                    f"p95 increased from {signal.baseline:.2f}s to {signal.value:.2f}s ({ratio:.1f}x)."
                )
        return related_facts, alert_gap
