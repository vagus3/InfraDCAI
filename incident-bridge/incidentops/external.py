from __future__ import annotations

from typing import Any

from incidentops.models import Incident, SignalSource


def external_incident_summary(incident: Incident) -> dict[str, Any]:
    """Allow-listed view of an incident for anything leaving this process --
    a fix-dispatch webhook, a notification webhook. `incident.model_dump()`
    includes each fact's `details`, and for a customer_report fact that is
    the customer's original email body (see matching.py); for a telemetry
    fact it is the full signal payload including free-form labels. Sending
    the whole incident means sending that to whatever URL an operator
    configured, which CODE_RULES.md #8 asks to avoid by naming the fields
    that actually need to leave instead.

    Customer summaries include names and subjects, so omit them as well as
    details. Previous triage output is excluded: it can quote those inputs.
    """
    return {
        "id": incident.id,
        "tenant": incident.tenant,
        "status": incident.status.value,
        "severity": incident.severity.value,
        "title": incident.title,
        "symptom": incident.symptom,
        "trigger": incident.trigger.value,
        "opened_at": incident.opened_at.isoformat(),
        "updated_at": incident.updated_at.isoformat(),
        "alert_gap": incident.alert_gap,
        "detection_lead_seconds": incident.detection_lead_seconds,
        "resolution_note": incident.resolution_note,
        "facts": [
            {
                "source": fact.source.value,
                "kind": fact.kind,
                "summary": "Customer reported a service issue"
                if fact.source == SignalSource.CUSTOMER_EMAIL else fact.summary,
                "observed_at": fact.observed_at.isoformat(),
            }
            for fact in incident.facts
        ],
    }
