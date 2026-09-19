from __future__ import annotations

from pathlib import Path

import httpx

from incidentops.config import settings
from incidentops.models import Incident


async def dispatch_fix(incident: Incident, task_path: Path) -> dict:
    task_text = task_path.read_text(encoding="utf-8")
    request_body = {
        "event": "incident.fix_requested",
        "incident_id": incident.id,
        "incident": incident.model_dump(mode="json"),
        "task": task_text,
    }
    if not settings.fix_webhook_url:
        return {
            "dispatched": False,
            "reason": "INCIDENTOPS_FIX_WEBHOOK_URL is not configured",
            "request": request_body,
        }

    async with httpx.AsyncClient(timeout=30) as client:
        response = await client.post(settings.fix_webhook_url, json=request_body)
        response.raise_for_status()
        return {"dispatched": True, "status_code": response.status_code}
