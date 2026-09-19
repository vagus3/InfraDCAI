from __future__ import annotations

from pathlib import Path

from incidentops.config import settings
from incidentops.models import Incident


class IncidentReportWriter:
    def __init__(self, artifact_dir: Path | None = None):
        self.artifact_dir = Path(artifact_dir or settings.artifact_dir)
        self.artifact_dir.mkdir(parents=True, exist_ok=True)

    def write_resolution(self, incident: Incident) -> Path:
        path = self.artifact_dir / f"{incident.id}-resolution.md"
        triage = incident.triage
        facts = "\n".join(f"- {fact.summary}" for fact in incident.facts)

        sections = [
            f"# Incident {incident.id} — {incident.status.value}",
            "## Impact",
            incident.title,
            f"Tenant: `{incident.tenant}`  ",
            f"Severity: `{incident.severity.value}`",
            "## Detection",
            f"Source: `{incident.trigger.value}`",
        ]
        if incident.detection_lead_seconds is not None:
            sections.append(f"Customer report arrived {incident.detection_lead_seconds:.0f}s after the incident opened.")
        if incident.alert_gap:
            sections.extend(["## Alert gap", incident.alert_gap])

        sections.extend(["## Facts", facts or "- none"])
        if triage:
            sections.extend([
                "## Triage",
                triage.probable_cause,
                f"Next step: {triage.next_step}",
            ])

        sections.extend([
            "## Resolution",
            incident.resolution_note or "No resolution note provided.",
        ])
        path.write_text("\n\n".join(sections) + "\n", encoding="utf-8")
        return path

    def customer_message(self, incident: Incident) -> str:
        if incident.status.value == "RESOLVED":
            return (
                f"안녕하세요. {incident.tenant} 서비스에서 확인된 이슈는 현재 복구되었습니다.\n\n"
                f"영향: {incident.symptom}\n"
                f"조치: {incident.resolution_note or '원인 확인 및 복구 조치를 완료했습니다.'}\n\n"
                "동일 증상 재발 여부를 계속 확인하겠습니다."
            )
        return (
            f"안녕하세요. {incident.tenant} 서비스에서 {incident.symptom} 징후를 확인하여 조사 중입니다.\n"
            "영향 범위와 원인을 확인하는 대로 후속 내용을 공유드리겠습니다."
        )
