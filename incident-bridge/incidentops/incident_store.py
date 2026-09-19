from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path

from incidentops.config import settings
from incidentops.models import CustomerEmail, Incident, TelemetrySignal


SCHEMA = """
CREATE TABLE IF NOT EXISTS telemetry (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    tenant TEXT NOT NULL,
    metric TEXT NOT NULL,
    observed_at TEXT NOT NULL,
    payload TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_telemetry_tenant_time ON telemetry(tenant, observed_at);

CREATE TABLE IF NOT EXISTS customer_email (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    tenant TEXT NOT NULL,
    received_at TEXT NOT NULL,
    payload TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_customer_email_tenant_time ON customer_email(tenant, received_at);

CREATE TABLE IF NOT EXISTS incidents (
    id TEXT PRIMARY KEY,
    tenant TEXT NOT NULL,
    status TEXT NOT NULL,
    opened_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    payload TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_incidents_tenant_status ON incidents(tenant, status);
"""


class IncidentStore:
    def __init__(self, db_path: Path | str | None = None):
        self.db_path = Path(db_path or settings.db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as conn:
            conn.executescript(SCHEMA)

    @contextmanager
    def _connect(self):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    def add_telemetry(self, signal: TelemetrySignal) -> None:
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO telemetry(tenant, metric, observed_at, payload) VALUES(?,?,?,?)",
                (signal.tenant, signal.metric, signal.observed_at.isoformat(), signal.model_dump_json()),
            )

    def recent_telemetry(self, tenant: str, minutes: int = 30) -> list[TelemetrySignal]:
        since = datetime.now(timezone.utc) - timedelta(minutes=minutes)
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT payload FROM telemetry WHERE tenant=? AND observed_at>=? ORDER BY observed_at ASC",
                (tenant, since.isoformat()),
            ).fetchall()
        return [TelemetrySignal.model_validate_json(row["payload"]) for row in rows]

    def add_customer_email(self, email: CustomerEmail) -> None:
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO customer_email(tenant, received_at, payload) VALUES(?,?,?)",
                (email.tenant, email.received_at.isoformat(), email.model_dump_json()),
            )

    def save_incident(self, incident: Incident) -> None:
        with self._connect() as conn:
            conn.execute(
                """INSERT INTO incidents(id, tenant, status, opened_at, updated_at, payload)
                   VALUES(?,?,?,?,?,?)
                   ON CONFLICT(id) DO UPDATE SET status=excluded.status, updated_at=excluded.updated_at, payload=excluded.payload""",
                (
                    incident.id,
                    incident.tenant,
                    incident.status.value,
                    incident.opened_at.isoformat(),
                    incident.updated_at.isoformat(),
                    incident.model_dump_json(),
                ),
            )

    def get_incident(self, incident_id: str) -> Incident | None:
        with self._connect() as conn:
            row = conn.execute("SELECT payload FROM incidents WHERE id=?", (incident_id,)).fetchone()
        return Incident.model_validate_json(row["payload"]) if row else None

    def open_incidents(self, tenant: str | None = None) -> list[Incident]:
        if tenant:
            sql = "SELECT payload FROM incidents WHERE tenant=? AND status<>? ORDER BY opened_at DESC"
            args = (tenant, "RESOLVED")
        else:
            sql = "SELECT payload FROM incidents WHERE status<>? ORDER BY opened_at DESC"
            args = ("RESOLVED",)
        with self._connect() as conn:
            rows = conn.execute(sql, args).fetchall()
        return [Incident.model_validate_json(row["payload"]) for row in rows]

    def all_incidents(self) -> list[Incident]:
        with self._connect() as conn:
            rows = conn.execute("SELECT payload FROM incidents ORDER BY opened_at DESC").fetchall()
        return [Incident.model_validate_json(row["payload"]) for row in rows]
