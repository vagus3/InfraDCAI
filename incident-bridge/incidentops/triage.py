from __future__ import annotations

import httpx

from incidentops.config import settings
from incidentops.models import Incident, IncidentType, TriageResult


class IncidentTriage:
    async def run(self, incident: Incident) -> TriageResult:
        if settings.triage_webhook_url:
            return await self._from_webhook(incident)
        return self._from_rules(incident)

    def _from_rules(self, incident: Incident) -> TriageResult:
        text = " ".join(
            [incident.title, incident.symptom] + [fact.summary for fact in incident.facts]
        ).lower()
        fact_details = [fact.details for fact in incident.facts if isinstance(fact.details, dict)]
        deployment_shas = [item.get("deployment_sha") for item in fact_details if item.get("deployment_sha")]
        dependencies = [item.get("dependency") for item in fact_details if item.get("dependency")]

        if deployment_shas:
            incident_type = IncidentType.CODE_REGRESSION
            cause = "A recent deployment lines up with the service regression."
            next_step = "Prepare a small code change or rollback, then check the live service after deployment."
            allowed_paths = ["app/**", ".github/workflows/**"]
        elif dependencies or "postgres" in text or "redis" in text or "readiness failed" in text:
            incident_type = IncidentType.DEPENDENCY_FAILURE
            cause = "A dependency looks unhealthy while the application itself is still reachable."
            next_step = "Follow the dependency runbook before changing application code."
            allowed_paths = ["RUNBOOK.md", "docker-compose.yml", "infra/**"]
        elif "ssh" in text or "security group" in text or "terraform" in text or "adr-" in text:
            incident_type = IncidentType.INFRA_CONFIG
            cause = "The observed infrastructure does not match the intended configuration."
            next_step = "Prepare a Terraform change and run the same configuration check after apply."
            allowed_paths = ["infra/**", "decision_monitor/**"]
        elif "cpu" in text or "memory" in text or "capacity" in text:
            incident_type = IncidentType.CAPACITY
            cause = "The workload may be near a capacity limit."
            next_step = "Review capacity and architecture with a human before changing the platform."
            allowed_paths = []
        else:
            incident_type = IncidentType.UNKNOWN
            cause = "The customer impact is visible, but the current signals are not enough to identify a safe fix."
            next_step = "Collect more logs/metrics or ask for human review before changing code."
            allowed_paths = []

        return TriageResult(
            incident_type=incident_type,
            probable_cause=cause,
            confidence="medium" if incident_type != IncidentType.UNKNOWN else "low",
            facts=[fact.summary for fact in incident.facts[:6]],
            next_step=next_step,
            allowed_paths=allowed_paths,
            checks=[
                "Automated tests pass",
                "CI passes",
                "Deployment succeeds when a deployment is required",
                "The original service symptom is healthy after the change",
            ],
        )

    async def _from_webhook(self, incident: Incident) -> TriageResult:
        request_body = {
            "task": "triage_incident",
            "incident": incident.model_dump(mode="json"),
            "response_schema": TriageResult.model_json_schema(),
        }
        async with httpx.AsyncClient(timeout=45) as client:
            response = await client.post(settings.triage_webhook_url, json=request_body)
            response.raise_for_status()
            body = response.json()
            if "triage" in body:
                body = body["triage"]
            return TriageResult.model_validate(body)
