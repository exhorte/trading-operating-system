"""The launcher's structured events (ADR 0038, § 12): one JSON line per event in ``events-AAAAMMJJ.jsonl`` (UTC day), because the launcher
runs before the database. Every text is masked first; no secret reaches the file."""

from __future__ import annotations

import json
import uuid
from datetime import UTC, date, datetime
from enum import StrEnum
from pathlib import Path

from pydantic import field_serializer

from trading_os.domain.primitives import DomainModel
from trading_os.shared.logging.redaction import redact
from trading_os.shared.time import Clock, iso


class EventType(StrEnum):
    STARTUP_DATABASE_READY = "STARTUP_DATABASE_READY"
    STARTUP_CORE_READY = "STARTUP_CORE_READY"
    STARTUP_COCKPIT_READY = "STARTUP_COCKPIT_READY"
    STARTUP_BACKUP_DONE = "STARTUP_BACKUP_DONE"
    STARTUP_SCHEMA_APPLIED = "STARTUP_SCHEMA_APPLIED"
    STARTUP_FAILED = "STARTUP_FAILED"
    LAUNCHER_PORT_FOREIGN_PROCESS = "LAUNCHER_PORT_FOREIGN_PROCESS"
    LAUNCHER_PROCESS_STARTED = "LAUNCHER_PROCESS_STARTED"
    LAUNCHER_PROCESS_STOPPED = "LAUNCHER_PROCESS_STOPPED"
    LAUNCHER_PROCESS_ADOPTED = "LAUNCHER_PROCESS_ADOPTED"
    LAUNCHER_STOP_REFUSED = "LAUNCHER_STOP_REFUSED"
    MT5_TERMINAL_DISCOVERED = "MT5_TERMINAL_DISCOVERED"
    MT5_TERMINAL_REGISTERED = "MT5_TERMINAL_REGISTERED"
    MT5_EA_BUILT = "MT5_EA_BUILT"
    MT5_EA_BUILD_REFUSED = "MT5_EA_BUILD_REFUSED"
    MT5_EA_DEPLOYED = "MT5_EA_DEPLOYED"
    MT5_EA_DEPLOY_REFUSED = "MT5_EA_DEPLOY_REFUSED"
    MT5_PRESET_WRITTEN = "MT5_PRESET_WRITTEN"
    MT5_PREPARE_REFUSED = "MT5_PREPARE_REFUSED"
    MT5_STATE_TRANSITION = "MT5_STATE_TRANSITION"
    MT5_STATE_ANOMALY = "MT5_STATE_ANOMALY"
    MT5_TERMINAL_CLOSE_REFUSED = "MT5_TERMINAL_CLOSE_REFUSED"
    MT5_START_FAILED = "MT5_START_FAILED"
    MT5_TERMINAL_STARTED = "MT5_TERMINAL_STARTED"
    MT5_RESTART_REQUESTED = "MT5_RESTART_REQUESTED"
    MT5_EA_CONNECTED = "MT5_EA_CONNECTED"
    MT5_ACCOUNT_MISMATCH = "MT5_ACCOUNT_MISMATCH"
    MT5_PROTOCOL_INCOMPATIBLE = "MT5_PROTOCOL_INCOMPATIBLE"
    MT5_WEBREQUEST_NOT_ALLOWED = "MT5_WEBREQUEST_NOT_ALLOWED"
    MT5_EA_NOT_REPORTING = "MT5_EA_NOT_REPORTING"
    MT5_HEARTBEAT_TIMEOUT = "MT5_HEARTBEAT_TIMEOUT"
    EXECUTION_READINESS_BLOCKED = "EXECUTION_READINESS_BLOCKED"


class EventSeverity(StrEnum):
    INFO = "INFO"
    WARNING = "WARNING"
    ERROR = "ERROR"


class LauncherEvent(DomainModel):
    occurred_at: datetime
    component: str
    instance_id: str | None = None  # the MT5 terminal instance, when the event is about one
    account_id: str | None = None
    type: EventType
    severity: EventSeverity = EventSeverity.INFO
    correlation_id: str
    diagnostic: str = ""

    @field_serializer("occurred_at")
    def _utc(self, value: datetime) -> str:
        return iso(value)


def new_correlation_id() -> str:
    return uuid.uuid4().hex[:12]


class EventLog:
    def __init__(self, directory: Path, clock: Clock) -> None:
        self._directory = directory
        self._clock = clock

    def emit(
        self,
        type: EventType,
        *,
        component: str,
        correlation_id: str,
        severity: EventSeverity = EventSeverity.INFO,
        diagnostic: str = "",
        instance_id: str | None = None,
        account_id: str | None = None,
    ) -> LauncherEvent:
        event = LauncherEvent(
            occurred_at=self._clock.now().astimezone(UTC),
            component=redact(component),
            instance_id=redact(instance_id) if instance_id else None,
            account_id=redact(account_id) if account_id else None,
            type=type,
            severity=severity,
            correlation_id=redact(correlation_id),
            diagnostic=redact(diagnostic),
        )
        line = event.model_dump_json(by_alias=True) + "\n"
        self._directory.mkdir(parents=True, exist_ok=True)
        with self._file_of(event.occurred_at.date()).open("a", encoding="utf-8", newline="\n") as handle:
            handle.write(line)  # one write: a reader never sees half an event
        return event

    def read(self, limit: int = 100) -> list[LauncherEvent]:
        """The last ``limit`` events, oldest first. A damaged line is skipped. Creates nothing."""
        if not self._directory.is_dir():
            return []
        found: list[LauncherEvent] = []
        for path in sorted(self._directory.glob("events-*.jsonl"), reverse=True):
            events = self._events_of(path)
            found = events + found
            if len(found) >= limit:
                break
        return found[-limit:]

    # ------------------------------------------------------------------------------------------------ internals

    def _file_of(self, day: date) -> Path:
        return self._directory / f"events-{day:%Y%m%d}.jsonl"

    @staticmethod
    def _events_of(path: Path) -> list[LauncherEvent]:
        events: list[LauncherEvent] = []
        for line in path.read_text(encoding="utf-8").splitlines():
            try:
                events.append(LauncherEvent.model_validate(json.loads(line)))
            except ValueError:
                continue
        return events
