"""API-layer tests: authorization and error mapping.

Uses dependency_overrides to inject a tracker backed by a temp DB, and never
enters TestClient as a context manager -- that would run the app's lifespan,
which builds a tracker on the real default db_path as a side effect of
importing/testing this module.
"""

from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient

from incidentops import api
from incidentops.incident_store import IncidentStore
from incidentops.models import TelemetrySignal
from incidentops.service import IncidentTracker


@pytest.fixture
def client(tmp_path, monkeypatch):
    tracker = IncidentTracker(IncidentStore(tmp_path / "api-test.db"))
    tracker.fix_tasks.artifact_dir = tmp_path / "artifacts"
    tracker.fix_tasks.artifact_dir.mkdir()
    tracker.reports.artifact_dir = tracker.fix_tasks.artifact_dir
    api.app.dependency_overrides[api.get_tracker] = lambda: tracker
    monkeypatch.setattr(api.settings, "api_token", None)
    try:
        yield TestClient(api.app), tracker
    finally:
        api.app.dependency_overrides.clear()


def _open_incident(tracker) -> str:
    incident = tracker.matcher.add_telemetry(
        TelemetrySignal(
            tenant="t",
            metric="readiness",
            value=0,
            observed_at=datetime.now(timezone.utc),
        )
    )
    return incident.id


def test_unknown_incident_is_404_not_a_raw_exception(client):
    c, _ = client
    response = c.get("/api/v1/incidents/INC-DOES-NOT-EXIST")
    assert response.status_code == 404


def test_verify_on_resolved_incident_is_409_not_500(client):
    c, tracker = client
    incident_id = _open_incident(tracker)
    tracker.verify(
        incident_id,
        api.VerificationRequest(ci_passed=True, deploy_succeeded=True, production_healthy=True),
    )

    response = c.post(
        f"/api/v1/incidents/{incident_id}/verify",
        json={"ci_passed": True, "deploy_succeeded": True, "production_healthy": True},
    )
    assert response.status_code == 409


def test_action_endpoints_are_open_when_no_token_is_configured(client):
    c, tracker = client
    incident_id = _open_incident(tracker)

    response = c.post(f"/api/v1/incidents/{incident_id}/notify")
    assert response.status_code == 200


def test_action_endpoints_require_the_configured_token(client, monkeypatch):
    c, tracker = client
    monkeypatch.setattr(api.settings, "api_token", "s3cret")
    incident_id = _open_incident(tracker)

    no_auth = c.post(f"/api/v1/incidents/{incident_id}/notify")
    assert no_auth.status_code == 403

    wrong = c.post(
        f"/api/v1/incidents/{incident_id}/notify", headers={"Authorization": "Bearer wrong"}
    )
    assert wrong.status_code == 403

    right = c.post(
        f"/api/v1/incidents/{incident_id}/notify", headers={"Authorization": "Bearer s3cret"}
    )
    assert right.status_code == 200


def test_read_endpoints_stay_open_even_with_a_token_configured(client, monkeypatch):
    # The token gates the three actions CODE_RULES.md #8 names -- dispatch,
    # notify, verify -- not every endpoint. Reads and ingestion are unaffected.
    c, tracker = client
    monkeypatch.setattr(api.settings, "api_token", "s3cret")
    incident_id = _open_incident(tracker)

    response = c.get(f"/api/v1/incidents/{incident_id}")
    assert response.status_code == 200
