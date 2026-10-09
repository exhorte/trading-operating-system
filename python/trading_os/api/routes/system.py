"""System: health (open and minimal), the cockpit's overview, readiness, the audit trail, incidents."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Query, Request

from trading_os import __version__
from trading_os.api.schemas.system import (
    AccessView,
    AuditView,
    DatabaseView,
    EventRecord,
    JobView,
    SystemHealthView,
    SystemStatus,
    TickQueueView,
    WebSocketView,
)
from trading_os.api.websocket.hub import CockpitHub
from trading_os.app.container import Container
from trading_os.app.dependencies import Core
from trading_os.domain.autonomy.readiness import ReadinessReport
from trading_os.domain.system.incidents import Incident

router = APIRouter(prefix="/api/system", tags=["system"])

Limit = Annotated[int, Query(ge=1, le=500)]


def build_health(c: Container, hub: CockpitHub | None) -> SystemHealthView:
    now = c.clock.now()
    health = c.db.health
    stats = hub.stats() if hub is not None else None
    return SystemHealthView(
        status=c.supervisor.status(),
        version=__version__,
        started_at=c.heartbeat.started_at,
        uptime_seconds=round(c.heartbeat.uptime_seconds(), 1),
        checked_at=c.supervisor.last_tick_at,
        database=DatabaseView(
            up=health.up, last_error=health.last_error, last_ok_at=health.last_ok_at, last_error_at=health.last_error_at
        ),
        audit=AuditView(written=c.audit.written, lost=c.audit.lost),
        ticks=TickQueueView(queued=c.tick_writer.queued, written=c.tick_writer.written, dropped=c.tick_writer.dropped),
        websocket=WebSocketView(
            clients=stats.clients if stats else 0,
            frames_sent=stats.frames_sent if stats else 0,
            frames_dropped=stats.frames_dropped if stats else 0,
            closed_for_overflow=stats.closed_for_overflow if stats else 0,
        ),
        agents_connected=len(c.execution.registered_logins()),
        jobs=[
            JobView(
                name=job.name,
                interval_s=job.interval_s,
                critical=job.critical,
                runs=job.runs,
                failures=job.failures,
                consecutive_failures=job.consecutive_failures,
                running=job.running,
                overdue=job.overdue(now),
                last_success_at=job.last_success_at,
                last_duration_ms=job.last_duration_ms,
                last_error=job.last_error,
            )
            for job in c.scheduler.stats()
        ],
        findings=c.supervisor.findings,
        access=AccessView(
            cockpit_guarded=c.settings.trading_os_cockpit_token is not None,
            agent_link_guarded=c.settings.trading_os_agent_token is not None,
        ),
    )


def hub_of(request: Request) -> CockpitHub | None:
    hub: CockpitHub | None = getattr(request.app.state, "hub", None)
    return hub


@router.get("/health", response_model=SystemHealthView, summary="Is the core up, and what is wrong with it")
async def health(request: Request, c: Core) -> SystemHealthView:
    """The one open endpoint: a launcher or a monitor reads it without a browser. It says whether the secrets are configured,
    never what they are, and names no account."""
    return build_health(c, hub_of(request))


@router.get("/status", response_model=SystemStatus, summary="The cockpit's overview of the whole system")
async def status(request: Request, c: Core) -> SystemStatus:
    return SystemStatus(
        server_time=c.clock.now(),
        version=__version__,
        active_account_id=c.accounts.active_account_id,
        accounts=await c.accounts.accounts(),
        agents=[s for login in c.execution.registered_logins() if (s := c.execution.agent_status(login)) is not None],
        autonomy=await c.autonomy.overview(),
        health=build_health(c, hub_of(request)),
    )


@router.get("/readiness", response_model=ReadinessReport, summary="The sixteen checks before an automatic mode")
async def readiness(c: Core, fresh: bool = False) -> ReadinessReport:
    return await c.autonomy.readiness(fresh=fresh)


@router.get("/events", response_model=list[EventRecord], summary="The audit trail, newest first")
async def events(
    c: Core,
    limit: Limit = 50,
    types: Annotated[list[str] | None, Query()] = None,
    account_id: Annotated[str | None, Query(alias="accountId")] = None,
    correlation_id: Annotated[str | None, Query(alias="correlationId")] = None,
    since: datetime | None = None,
) -> list[EventRecord]:
    rows = await c.repos.events.query(
        types=types, account_id=account_id, correlation_id=correlation_id, since=since, limit=limit
    )
    return [
        EventRecord(
            event_id=r["event_id"], type=r["type"], occurred_at=r["occurred_at"], account_id=r["account_id"],
            correlation_id=r["correlation_id"], payload=r["payload"],
        )
        for r in rows
    ]  # fmt: skip


@router.get("/incidents", response_model=list[Incident], summary="Abnormal situations the supervisor recorded")
async def incidents(
    c: Core, limit: Limit = 100, open_only: Annotated[bool, Query(alias="openOnly")] = False
) -> list[Incident]:
    return await c.repos.incidents.open_incidents() if open_only else await c.repos.incidents.recent(limit)
