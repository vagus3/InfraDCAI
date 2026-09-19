from __future__ import annotations

from pathlib import Path

from incidentops.config import settings
from incidentops.models import Incident, IncidentType


class FixTaskBuilder:
    def __init__(self, artifact_dir: Path | None = None):
        self.artifact_dir = Path(artifact_dir or settings.artifact_dir)
        self.artifact_dir.mkdir(parents=True, exist_ok=True)

    def write(self, incident: Incident) -> Path:
        if not incident.triage:
            raise ValueError("incident must be triaged before creating a fix task")

        triage = incident.triage
        if triage.incident_type in {IncidentType.CAPACITY, IncidentType.UNKNOWN}:
            raise ValueError(f"{triage.incident_type.value} requires human review")

        path = self.artifact_dir / f"{incident.id}-fix.md"
        facts = "\n".join(f"- {item}" for item in triage.facts) or "- none"
        allowed_paths = "\n".join(f"- {item}" for item in triage.allowed_paths) or "- No source change approved."
        checks = "\n".join(f"- [ ] {item}" for item in triage.checks)

        content = f"""# Fix request — {incident.id}

## Incident
{incident.title}

Tenant: `{incident.tenant}`  
Severity: `{incident.severity.value}`  
Type: `{triage.incident_type.value}`

## Likely cause
{triage.probable_cause}

## Facts
{facts}

## Next step
{triage.next_step}

## Files you may change
{allowed_paths}

## Constraints
- Keep the change focused on this incident.
- Do not weaken security checks just to make CI pass.
- Prefer a small, reversible change.
- Stop if the available facts do not support a safe change.

## Checks
{checks}

## Completion note
List the changed files, tests/checks run, remaining risk, and rollback path.
"""
        path.write_text(content, encoding="utf-8")
        return path
