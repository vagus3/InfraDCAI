from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse

from incidentops.models import CustomerEmail, TelemetrySignal, VerificationRequest
from incidentops.integrations.fix_webhook import dispatch_fix
from incidentops.integrations.notifications import send_notification
from incidentops.service import IncidentTracker

app = FastAPI(title="Incident Bridge", version="0.2.0")
tracker = IncidentTracker()


@app.get("/")
def dashboard():
    return FileResponse("incidentops/static/dashboard.html")


@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/api/v1/incidents")
def incidents():
    return [incident.model_dump(mode="json") for incident in tracker.list_incidents()]


@app.get("/api/v1/incidents/{incident_id}")
def incident(incident_id: str):
    try:
        return tracker.get(incident_id).model_dump(mode="json")
    except KeyError:
        raise HTTPException(404, "incident not found")


@app.post("/api/v1/signals/telemetry")
async def telemetry(signal: TelemetrySignal):
    incident = await tracker.record_telemetry(signal)
    return {"incident": incident.model_dump(mode="json") if incident else None}


@app.post("/api/v1/customer-email")
async def customer_email(email: CustomerEmail):
    incident = await tracker.record_customer_email(email)
    return {"incident": incident.model_dump(mode="json")}


@app.post("/api/v1/incidents/{incident_id}/triage")
async def triage(incident_id: str):
    try:
        return (await tracker.triage_incident(incident_id)).model_dump(mode="json")
    except KeyError:
        raise HTTPException(404, "incident not found")


@app.post("/api/v1/incidents/{incident_id}/fix-task")
def fix_task(incident_id: str):
    try:
        incident, path = tracker.create_fix_task(incident_id)
        return {"incident": incident.model_dump(mode="json"), "task": str(path)}
    except KeyError:
        raise HTTPException(404, "incident not found")
    except ValueError as exc:
        raise HTTPException(409, str(exc))


@app.post("/api/v1/incidents/{incident_id}/fix-dispatch")
async def fix_dispatch(incident_id: str):
    try:
        incident, path = tracker.create_fix_task(incident_id)
        dispatch = await dispatch_fix(incident, path)
        return {"incident": incident.model_dump(mode="json"), "task": str(path), "dispatch": dispatch}
    except KeyError:
        raise HTTPException(404, "incident not found")
    except ValueError as exc:
        raise HTTPException(409, str(exc))


@app.post("/api/v1/incidents/{incident_id}/verify")
def verify(incident_id: str, request: VerificationRequest):
    try:
        return tracker.verify(incident_id, request).model_dump(mode="json")
    except KeyError:
        raise HTTPException(404, "incident not found")


@app.post("/api/v1/incidents/{incident_id}/notify")
async def notify(incident_id: str):
    try:
        incident = tracker.get(incident_id)
    except KeyError:
        raise HTTPException(404, "incident not found")
    message = tracker.reports.customer_message(incident)
    channel = await send_notification(incident, message)
    return {"channel": channel, "message": message}
