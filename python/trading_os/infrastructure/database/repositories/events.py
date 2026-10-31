"""The audit trail (``events``) and the incident register."""

from __future__ import annotations

from datetime import datetime

from trading_os.domain.system.incidents import Incident
from trading_os.infrastructure.database.pool import Database, Row, jsonb
from trading_os.shared.events.base import Event


class EventStore:
    """One row per event; the id is unique, so publishing the same event twice cannot duplicate it."""

    def __init__(self, db: Database) -> None:
        self._db = db

    async def append(self, event: Event) -> bool:
        inserted = await self._db.execute(
            "INSERT INTO events (event_id, type, occurred_at, account_id, correlation_id, payload) "
            "VALUES (%s, %s, %s, %s, %s, %s) ON CONFLICT (event_id) DO NOTHING",
            (
                event.id,
                event.wire_type,
                event.occurred_at,
                event.account_id,
                event.correlation_id,
                jsonb(event.payload()),
            ),
        )
        return inserted == 1

    async def query(
        self,
        *,
        types: list[str] | None = None,
        account_id: str | None = None,
        correlation_id: str | None = None,
        since: datetime | None = None,
        limit: int = 100,
    ) -> list[Row]:
        return await self._db.fetch_all(
            "SELECT event_id, type, occurred_at, account_id, correlation_id, payload FROM events "
            "WHERE (%s::text[] IS NULL OR type = ANY(%s)) AND (%s::text IS NULL OR account_id = %s) "
            "AND (%s::text IS NULL OR correlation_id = %s) AND (%s::timestamptz IS NULL OR occurred_at >= %s) "
            "ORDER BY occurred_at DESC, event_id DESC LIMIT %s",
            (
                types,
                types,
                account_id,
                account_id,
                correlation_id,
                correlation_id,
                since,
                since,
                max(1, min(limit, 1000)),
            ),
        )

    async def counts_by_type(self, since: datetime) -> dict[str, int]:
        rows = await self._db.fetch_all(
            "SELECT type, count(*) AS n FROM events WHERE occurred_at >= %s GROUP BY type ORDER BY type", (since,)
        )
        return {r["type"]: int(r["n"]) for r in rows}


_INCIDENT_COLUMNS = "incident_id, code, component, severity, detail, account_id, opened_at, resolved_at, resolution"


class IncidentRepository:
    def __init__(self, db: Database) -> None:
        self._db = db

    async def open(self, incident: Incident) -> None:
        await self._db.execute(
            "INSERT INTO incidents (incident_id, code, component, severity, detail, account_id, opened_at) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s) ON CONFLICT (incident_id) DO NOTHING",
            (
                incident.incident_id,
                incident.code,
                incident.component,
                incident.severity.value,
                incident.detail,
                incident.account_id,
                incident.opened_at,
            ),
        )

    async def resolve(self, incident_id: str, at: datetime, resolution: str) -> bool:
        updated = await self._db.execute(
            "UPDATE incidents SET resolved_at = %s, resolution = %s WHERE incident_id = %s AND resolved_at IS NULL",
            (at, resolution, incident_id),
        )
        return updated == 1

    async def open_incidents(self) -> list[Incident]:
        rows = await self._db.fetch_all(
            "SELECT "
            + _INCIDENT_COLUMNS
            + " FROM incidents WHERE resolved_at IS NULL ORDER BY opened_at DESC LIMIT 200"
        )
        return [Incident.model_validate(dict(r)) for r in rows]

    async def recent(self, limit: int = 100) -> list[Incident]:
        rows = await self._db.fetch_all(
            "SELECT " + _INCIDENT_COLUMNS + " FROM incidents ORDER BY opened_at DESC LIMIT %s",
            (max(1, min(limit, 500)),),
        )
        return [Incident.model_validate(dict(r)) for r in rows]
