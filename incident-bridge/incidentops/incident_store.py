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
    message_id TEXT,
    incident_id TEXT,
    payload TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_customer_email_tenant_time ON customer_email(tenant, received_at);
-- A NULL message_id means the caller supplied no identifier, so every such
-- email is its own event -- SQLite does not enforce uniqueness among NULLs in
-- a UNIQUE index, which is exactly the "no id, always new" behaviour we want.
CREATE UNIQUE INDEX IF NOT EXISTS idx_customer_email_dedup ON customer_email(tenant, message_id);

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

    def recent_telemetry(
        self, tenant: str, minutes: int = 30, now: datetime | None = None
    ) -> list[TelemetrySignal]:
        """Signals within [now - minutes, now].

        The upper bound matters as much as the lower one: without it, a signal
        timestamped in the future -- clock skew, a bad client, or a malformed
        offset -- matches every window forever, since it is always ">= since".
        `now` is a parameter rather than read internally so this stays testable
        with a fixed clock instead of a real one.
        """
        now = now or datetime.now(timezone.utc)
        since = now - timedelta(minutes=minutes)
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT payload FROM telemetry WHERE tenant=? AND observed_at>=? AND observed_at<=? "
                "ORDER BY observed_at ASC",
                (tenant, since.isoformat(), now.isoformat()),
            ).fetchall()
        return [TelemetrySignal.model_validate_json(row["payload"]) for row in rows]

    def add_customer_email(self, email: CustomerEmail) -> bool:
        """Stores the email and reports whether it was new.

        Returns False when (tenant, message_id) already exists -- a resend of
        the same event, not a second event -- so the caller can skip adding a
        duplicate fact. An email with no message_id has no identifier to dedupe
        on, so it is always treated as new; DESIGN.md's rule is that the same
        *content* reported twice is two events unless something identifies them
        as the same one.
        """
        with self._connect() as conn:
            cursor = conn.execute(
                "INSERT OR IGNORE INTO customer_email(tenant, received_at, message_id, payload) "
                "VALUES(?,?,?,?)",
                (email.tenant, email.received_at.isoformat(), email.message_id, email.model_dump_json()),
            )
            return cursor.rowcount > 0

    def customer_email_incident(self, tenant: str, message_id: str) -> str | None:
        """Which incident a previously-seen (tenant, message_id) is linked to,
        if any. Used to resolve a resend to the incident it already joined
        without scanning every incident's fact list."""
        with self._connect() as conn:
            row = conn.execute(
                "SELECT incident_id FROM customer_email WHERE tenant=? AND message_id=?",
                (tenant, message_id),
            ).fetchone()
        return row["incident_id"] if row else None

    def link_customer_email_incident(
        self, tenant: str, message_id: str | None, incident_id: str
    ) -> None:
        """Records which incident a (tenant, message_id) email ended up on.
        A no-op when there is no message_id, since there is then nothing to
        dedupe against later."""
        if message_id is None:
            return
        with self._connect() as conn:
            conn.execute(
                "UPDATE customer_email SET incident_id=? WHERE tenant=? AND message_id=?",
                (incident_id, tenant, message_id),
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

    def latest_open_incident(
        self, tenant: str, at: datetime, window_minutes: int
    ) -> Incident | None:
        """The most recent open incident for `tenant` still within the
        correlation window of `at`, or None.

        Bounded and LIMIT 1 in SQL rather than fetching every open incident and
        taking the first: this is also what stops an incident from absorbing
        signals indefinitely. `status<>'RESOLVED'` alone would let an
        ESCALATED incident from days ago keep collecting new alerts and emails
        forever; bounding by `updated_at` means it stops being a match once
        nothing has touched it inside the window, RESOLVED or not.

        The window is symmetric (`BETWEEN since AND until`) rather than
        one-sided so a signal that arrives slightly out of order -- plausible
        under real clock skew between a collector and this service -- can
        still correlate.
        """
        since = (at - timedelta(minutes=window_minutes)).isoformat()
        until = (at + timedelta(minutes=window_minutes)).isoformat()
        with self._connect() as conn:
            row = conn.execute(
                "SELECT payload FROM incidents WHERE tenant=? AND status<>? "
                "AND updated_at BETWEEN ? AND ? ORDER BY updated_at DESC LIMIT 1",
                (tenant, "RESOLVED", since, until),
            ).fetchone()
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
