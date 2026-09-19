from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from incidentops.fix_tasks import FixTaskBuilder
from incidentops.incident_store import IncidentStore
from incidentops.matching import IncidentMatcher
from incidentops.models import CustomerEmail, Incident, IncidentStatus, TelemetrySignal, VerificationRequest
from incidentops.reporting import IncidentReportWriter
from incidentops.triage import IncidentTriage


class IncidentAlreadyResolved(ValueError):
    """Raised for any status-changing call on an incident already RESOLVED.

    DESIGN.md #4 leaves "what happens if the symptom recurs" as an open
    question -- a new linked incident, or an explicit reopen rule, neither of
    which exists yet. Silently letting triage/verify run again on a RESOLVED
    incident would reopen it by accident, with no record that that happened.
    Raising here turns a silent state change into a visible decision the
    caller has to make once that policy exists.
    """

    def __init__(self, incident_id: str):
        super().__init__(
            f"{incident_id} is already RESOLVED. Re-running its workflow would reopen it "
            "without the reopen policy DESIGN.md #4 still needs; open a new incident instead."
        )


class IncidentTracker:
    def __init__(self, store: IncidentStore | None = None):
        self.store = store or IncidentStore()
        self.matcher = IncidentMatcher(self.store)
        self.triage = IncidentTriage()
        self.fix_tasks = FixTaskBuilder()
        self.reports = IncidentReportWriter()

    async def record_telemetry(self, signal: TelemetrySignal) -> Incident | None:
        return self.matcher.add_telemetry(signal)

    async def record_customer_email(self, email: CustomerEmail) -> Incident:
        return self.matcher.add_customer_email(email)

    async def triage_incident(self, incident_id: str) -> Incident:
        incident = self._get_required(incident_id)
        self._ensure_not_resolved(incident)
        incident.triage = await self.triage.run(incident)
        self._set_status(incident, IncidentStatus.TRIAGED)
        return incident

    def create_fix_task(self, incident_id: str) -> tuple[Incident, Path]:
        incident = self._get_required(incident_id)
        self._ensure_not_resolved(incident)
        path = self.fix_tasks.write(incident)
        self._set_status(incident, IncidentStatus.READY_FOR_FIX)
        return incident, path

    def mark_fix_started(self, incident_id: str) -> Incident:
        incident = self._get_required(incident_id)
        self._ensure_not_resolved(incident)
        self._set_status(incident, IncidentStatus.FIX_IN_PROGRESS)
        return incident

    def verify(self, incident_id: str, request: VerificationRequest) -> Incident:
        incident = self._get_required(incident_id)
        self._ensure_not_resolved(incident)
        self._set_status(incident, IncidentStatus.VERIFYING)

        healthy = request.ci_passed and request.deploy_succeeded and request.production_healthy
        if request.decision_check_passed is not None:
            healthy = healthy and request.decision_check_passed

        if healthy:
            incident.status = IncidentStatus.RESOLVED
            incident.resolution_note = request.notes or "CI, deployment, and live service checks passed."
        else:
            incident.status = IncidentStatus.ESCALATED
            incident.resolution_note = request.notes or "Post-deploy checks failed; manual investigation is required."

        incident.updated_at = datetime.now(timezone.utc)
        self.store.save_incident(incident)
        self.reports.write_resolution(incident)
        return incident

    def list_incidents(self) -> list[Incident]:
        return self.store.all_incidents()

    def get(self, incident_id: str) -> Incident:
        return self._get_required(incident_id)

    def _get_required(self, incident_id: str) -> Incident:
        incident = self.store.get_incident(incident_id)
        if not incident:
            raise KeyError(incident_id)
        return incident

    def _ensure_not_resolved(self, incident: Incident) -> None:
        if incident.status == IncidentStatus.RESOLVED:
            raise IncidentAlreadyResolved(incident.id)

    def _set_status(self, incident: Incident, status: IncidentStatus) -> None:
        """The status+timestamp+save sequence every transition above needs,
        in one place instead of repeated at each call site."""
        incident.status = status
        incident.updated_at = datetime.now(timezone.utc)
        self.store.save_incident(incident)
