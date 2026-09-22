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
    monkeypatch.setattr(api.settings, "api_token", "test-operator-token")
    monkeypatch.setattr(api.settings, "notify_webhook_url", None)
    monkeypatch.setattr(api.settings, "triage_webhook_url", None)
    monkeypatch.setattr(api.settings, "smtp_host", None)
    try:
        yield TestClient(api.app, headers={"Authorization": "Bearer test-operator-token"}), tracker
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


def test_api_is_disabled_when_no_token_is_configured(client, monkeypatch):
    c, tracker = client
    monkeypatch.setattr(api.settings, "api_token", None)
    incident_id = _open_incident(tracker)

    response = c.post(f"/api/v1/incidents/{incident_id}/notify")
    assert response.status_code == 503
    assert c.get('/api/v1/incidents').status_code == 503
    assert c.get('/health').status_code == 200


def test_action_endpoints_require_the_configured_token(client, monkeypatch):
    c, tracker = client
    monkeypatch.setattr(api.settings, "api_token", "s3cret")
    c.headers.pop("Authorization")
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


def test_reads_require_a_token_too(client):
    c, tracker = client
    incident_id = _open_incident(tracker)

    response = c.get(f"/api/v1/incidents/{incident_id}")
    assert response.status_code == 200
    c.headers.pop("Authorization")
    assert c.get(f"/api/v1/incidents/{incident_id}").status_code == 403


@pytest.mark.parametrize("method,path", [
    ("GET", "/incidents"),
    ("GET", "/incidents/INC-TEST"),
    ("POST", "/signals/telemetry"),
    ("POST", "/customer-email"),
    ("POST", "/incidents/INC-TEST/triage"),
    ("POST", "/incidents/INC-TEST/fix-task"),
    ("POST", "/incidents/INC-TEST/fix-dispatch"),
    ("POST", "/incidents/INC-TEST/verify"),
    ("POST", "/incidents/INC-TEST/notify"),
])
def test_every_incident_route_rejects_missing_auth_before_processing(client, method, path):
    c, tracker = client
    c.headers.pop("Authorization")
    assert c.request(method, "/api/v1" + path, json={}).status_code == 403
    assert tracker.list_incidents() == []


def test_authenticated_synthetic_flow(client):
    c, _ = client
    opened = c.post('/api/v1/signals/telemetry', json={
        'tenant': 'demo', 'metric': 'readiness', 'value': 0,
    })
    assert opened.status_code == 200
    incident_id = opened.json()['incident']['id']
    assert c.post(f'/api/v1/incidents/{incident_id}/triage').status_code == 200
    assert c.post(f'/api/v1/incidents/{incident_id}/fix-task').status_code == 200
    result = c.post(f'/api/v1/incidents/{incident_id}/verify', json={
        'ci_passed': True, 'deploy_succeeded': True, 'production_healthy': True,
        'notes': 'Synthetic test only; not measured recovery.',
    })
    assert result.status_code == 200
    assert result.json()['status'] == 'RESOLVED'
