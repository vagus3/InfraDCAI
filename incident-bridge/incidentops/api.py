from __future__ import annotations

import hmac
from contextlib import asynccontextmanager, contextmanager

from fastapi import Depends, FastAPI, Header, HTTPException, Request
from fastapi.responses import FileResponse

from incidentops.config import settings
from incidentops.integrations.fix_webhook import dispatch_fix
from incidentops.integrations.notifications import send_notification
from incidentops.models import CustomerEmail, TelemetrySignal, VerificationRequest
from incidentops.service import IncidentTracker


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Built when the app starts serving, not at import time -- importing this
    # module (e.g. for a type or a constant, from a test) should not open a
    # database connection as a side effect.
    app.state.tracker = IncidentTracker()
    yield


app = FastAPI(title="Incident Bridge", version="0.2.0", lifespan=lifespan)


def get_tracker(request: Request) -> IncidentTracker:
    return request.app.state.tracker


@contextmanager
def _map_domain_errors():
    """incident-not-found and policy-violation both come out of the tracker
    as plain exceptions (KeyError, ValueError); this is the one place that
    turns them into the HTTP status each endpoint should return, instead of
    every endpoint repeating its own try/except."""
    try:
        yield
    except KeyError:
        raise HTTPException(404, "incident not found")
    except ValueError as exc:
        raise HTTPException(409, str(exc))


def require_action_token(authorization: str | None = Header(default=None)) -> None:
    """Gates dispatching a fix, sending a customer notification, and
    approving recovery -- the three actions CODE_RULES.md #8 calls out as
    needing caller authorization, since each can trigger something external
    (a webhook call, an email) or close an incident out.

    When INCIDENTOPS_API_TOKEN is unset -- the local-demo default -- this is
    a no-op and these endpoints stay open, exactly as before. That is a
    statement about what this check does, not a claim that an unconfigured
    deployment is safe to expose; see README.md/DESIGN.md.
    """
    if not settings.api_token:
        return
    expected = f"Bearer {settings.api_token}"
    if not authorization or not hmac.compare_digest(authorization, expected):
        raise HTTPException(403, "missing or invalid action token")


@app.get("/")
def dashboard():
    return FileResponse("incidentops/static/dashboard.html")


@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/api/v1/incidents")
def incidents(tracker: IncidentTracker = Depends(get_tracker)):
    return [incident.model_dump(mode="json") for incident in tracker.list_incidents()]


@app.get("/api/v1/incidents/{incident_id}")
def incident(incident_id: str, tracker: IncidentTracker = Depends(get_tracker)):
    with _map_domain_errors():
        return tracker.get(incident_id).model_dump(mode="json")


@app.post("/api/v1/signals/telemetry")
async def telemetry(signal: TelemetrySignal, tracker: IncidentTracker = Depends(get_tracker)):
    incident = await tracker.record_telemetry(signal)
    return {"incident": incident.model_dump(mode="json") if incident else None}


@app.post("/api/v1/customer-email")
async def customer_email(email: CustomerEmail, tracker: IncidentTracker = Depends(get_tracker)):
    incident = await tracker.record_customer_email(email)
    return {"incident": incident.model_dump(mode="json")}


@app.post("/api/v1/incidents/{incident_id}/triage")
async def triage(incident_id: str, tracker: IncidentTracker = Depends(get_tracker)):
    with _map_domain_errors():
        return (await tracker.triage_incident(incident_id)).model_dump(mode="json")


@app.post("/api/v1/incidents/{incident_id}/fix-task")
def fix_task(incident_id: str, tracker: IncidentTracker = Depends(get_tracker)):
    with _map_domain_errors():
        incident, path = tracker.create_fix_task(incident_id)
        return {"incident": incident.model_dump(mode="json"), "task": str(path)}


@app.post(
    "/api/v1/incidents/{incident_id}/fix-dispatch",
    dependencies=[Depends(require_action_token)],
)
async def fix_dispatch(incident_id: str, tracker: IncidentTracker = Depends(get_tracker)):
    with _map_domain_errors():
        incident, path = tracker.create_fix_task(incident_id)
    dispatch = await dispatch_fix(incident, path)
    return {"incident": incident.model_dump(mode="json"), "task": str(path), "dispatch": dispatch}


@app.post(
    "/api/v1/incidents/{incident_id}/verify",
    dependencies=[Depends(require_action_token)],
)
def verify(incident_id: str, request: VerificationRequest, tracker: IncidentTracker = Depends(get_tracker)):
    with _map_domain_errors():
        return tracker.verify(incident_id, request).model_dump(mode="json")


@app.post(
    "/api/v1/incidents/{incident_id}/notify",
    dependencies=[Depends(require_action_token)],
)
async def notify(incident_id: str, tracker: IncidentTracker = Depends(get_tracker)):
    with _map_domain_errors():
        incident = tracker.get(incident_id)
    message = tracker.reports.customer_message(incident)
    channel = await send_notification(incident, message)
    return {"channel": channel, "message": message}
