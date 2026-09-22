import asyncio
import sqlite3

import httpx
import pytest

from incidentops.collectors import http_probe
from incidentops.incident_store import IncidentStore


def test_legacy_database_is_upgraded_without_deleting_records(tmp_path):
    db_path = tmp_path / "old.db"
    with sqlite3.connect(db_path) as conn:
        conn.execute("CREATE TABLE customer_email (id INTEGER PRIMARY KEY, tenant TEXT NOT NULL, "
                     "received_at TEXT NOT NULL, payload TEXT NOT NULL)")
        conn.execute("INSERT INTO customer_email VALUES (1, 'old', '2026-09-19T00:00:00+00:00', '{}')")
    IncidentStore(db_path)
    IncidentStore(db_path)  # Restarting must not attempt to add columns twice.
    with sqlite3.connect(db_path) as conn:
        assert conn.execute("SELECT tenant, payload, message_id, incident_id FROM customer_email").fetchall() == [
            ("old", "{}", None, None),
        ]


def test_collector_sends_token_only_to_ingest_and_reports_rejection(monkeypatch, capsys):
    requests = []

    def handle(request):
        requests.append(request)
        if request.url.host == "workload.invalid":
            assert "authorization" not in request.headers
            return httpx.Response(200)
        assert request.headers["authorization"] == "Bearer synthetic-collector-token"
        return httpx.Response(403)

    async def stop_after_iteration(_):
        raise asyncio.CancelledError

    client_class = httpx.AsyncClient
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kw: client_class(
        transport=httpx.MockTransport(handle), **kw,
    ))
    monkeypatch.setattr(http_probe.settings, "api_token", "synthetic-collector-token")
    monkeypatch.setattr(asyncio, "sleep", stop_after_iteration)
    with pytest.raises(asyncio.CancelledError):
        asyncio.run(http_probe.run("https://workload.invalid", "https://ingest.invalid", "demo", 1))
    assert len(requests) == 3
    output = capsys.readouterr().out
    assert output.count("collector ingest failed: HTTPStatusError") == 2
    assert "synthetic-collector-token" not in output
