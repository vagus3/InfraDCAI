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

        # `confidence` reflects how directly each branch's evidence supports its
        # conclusion, not just whether a branch matched. Recording a deployment
        # sha is a fact; that sha caused this incident is a hypothesis the sha
        # merely correlates with (DESIGN.md #6's fact/hypothesis distinction,
        # applied here so the rule-based path doesn't overstate certainty the
        # AI-assisted path is explicitly told not to). A `dependency` field or
        # an observed readiness failure is closer to direct evidence of an
        # unhealthy dependency, so it keeps "medium". The keyword branches
        # below match on rendered text, not structured fields, and are
        # correspondingly the least certain.
        if deployment_shas:
            incident_type = IncidentType.CODE_REGRESSION
            cause = (
                f"Deployment sha(s) {', '.join(deployment_shas)} were recorded around this "
                "incident. That is a correlation, not a confirmed cause -- treat it as the "
                "first hypothesis to check, not an established root cause."
            )
            confidence = "low"
            next_step = "Compare behavior before/after that deployment, then prepare a small code change or rollback."
            allowed_paths = ["app/**", ".github/workflows/**"]
        elif dependencies or "postgres" in text or "redis" in text or "readiness failed" in text:
            incident_type = IncidentType.DEPENDENCY_FAILURE
            cause = "A dependency looks unhealthy while the application itself is still reachable."
            confidence = "medium"
            next_step = "Follow the dependency runbook before changing application code."
            allowed_paths = ["RUNBOOK.md", "docker-compose.yml", "infra/**"]
        elif "ssh" in text or "security group" in text or "terraform" in text or "adr-" in text:
            incident_type = IncidentType.INFRA_CONFIG
            cause = (
                "Wording in the title/facts suggests the observed infrastructure does not "
                "match the intended configuration -- a keyword match, not a confirmed diff."
            )
            confidence = "low"
            next_step = "Prepare a Terraform change and run the same configuration check after apply."
            allowed_paths = ["infra/**", "decision_monitor/**"]
        elif "cpu" in text or "memory" in text or "capacity" in text:
            incident_type = IncidentType.CAPACITY
            cause = "Wording suggests the workload may be near a capacity limit -- a keyword match, not a measured one."
            confidence = "low"
            next_step = "Review capacity and architecture with a human before changing the platform."
            allowed_paths = []
        else:
            incident_type = IncidentType.UNKNOWN
            cause = "The customer impact is visible, but the current signals are not enough to identify a safe fix."
            confidence = "low"
            next_step = "Collect more logs/metrics or ask for human review before changing code."
            allowed_paths = []

        return TriageResult(
            incident_type=incident_type,
            probable_cause=cause,
            confidence=confidence,
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
