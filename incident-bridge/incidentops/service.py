from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from incidentops.fix_tasks import FixTaskBuilder
from incidentops.incident_store import IncidentStore
from incidentops.matching import IncidentMatcher
from incidentops.models import CustomerEmail, Incident, IncidentStatus, TelemetrySignal, VerificationRequest
from incidentops.reporting import IncidentReportWriter
from incidentops.triage import IncidentTriage


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
        incident.triage = await self.triage.run(incident)
        incident.status = IncidentStatus.TRIAGED
        incident.updated_at = datetime.now(timezone.utc)
        self.store.save_incident(incident)
        return incident

    def create_fix_task(self, incident_id: str) -> tuple[Incident, Path]:
        incident = self._get_required(incident_id)
        path = self.fix_tasks.write(incident)
        incident.status = IncidentStatus.READY_FOR_FIX
        incident.updated_at = datetime.now(timezone.utc)
        self.store.save_incident(incident)
        return incident, path

    def mark_fix_started(self, incident_id: str) -> Incident:
        incident = self._get_required(incident_id)
        incident.status = IncidentStatus.FIX_IN_PROGRESS
        incident.updated_at = datetime.now(timezone.utc)
        self.store.save_incident(incident)
        return incident

    def verify(self, incident_id: str, request: VerificationRequest) -> Incident:
        incident = self._get_required(incident_id)
        incident.status = IncidentStatus.VERIFYING

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
