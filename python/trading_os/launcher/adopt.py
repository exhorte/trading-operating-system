"""Adopting (ADR 0038, § 3): a person's explicit gesture that turns a *recognized* process — started by hand, carrying this repository's
signature — into one the launcher owns, so that ``stop`` may end it. Nothing else is ever adopted: not a foreign process, not a container."""

from __future__ import annotations

from trading_os.domain.primitives import DomainModel
from trading_os.launcher.events import EventLog, EventSeverity, EventType
from trading_os.launcher.model import Component, ComponentState, OwnedProcess, Ownership
from trading_os.launcher.observe import Observer
from trading_os.launcher.ports import ProcessTable
from trading_os.launcher.registry import ProcessRegistry
from trading_os.shared.logging.redaction import redact
from trading_os.shared.time import Clock


class AdoptOutcome(DomainModel):
    component: Component
    adopted: bool
    detail: str


def adopt(
    component: Component,
    *,
    observer: Observer,
    processes: ProcessTable,
    registry: ProcessRegistry,
    events: EventLog,
    clock: Clock,
    correlation_id: str,
) -> AdoptOutcome:
    def refused(detail: str) -> AdoptOutcome:
        events.emit(
            EventType.LAUNCHER_STOP_REFUSED,
            component=component.value,
            correlation_id=correlation_id,
            severity=EventSeverity.WARNING,
            diagnostic=f"adoption refusée : {detail}",
        )
        return AdoptOutcome(component=component, adopted=False, detail=detail)

    if component is Component.DATABASE:
        return refused("la base est un conteneur, pas un processus : il n'y a rien à adopter")
    item = observer.observe().component(component)
    if item.state is ComponentState.ABSENT or item.pid is None:
        return refused("rien ne tourne : il n'y a rien à adopter")
    if item.ownership is Ownership.OWNED:
        return refused("ce processus est déjà possédé par le lanceur")
    if item.ownership is not Ownership.RECOGNIZED:
        return refused(f"le processus (pid {item.pid}) n'est pas reconnu comme étant de ce dépôt : il n'est pas adopté")
    live = next((process for process in processes.processes() if process.pid == item.pid), None)
    if live is None or live.created_at is None:
        return refused("l'identité du processus ne peut pas être prouvée (heure de création inconnue)")
    registry.record(
        OwnedProcess(
            component=component,
            pid=live.pid,
            created_at=live.created_at,
            command_line=live.command_line,
            started_at=live.created_at,
            working_directory=None,
            log_path=None,
            correlation_id=correlation_id,
        )
    )
    events.emit(
        EventType.LAUNCHER_PROCESS_ADOPTED,
        component=component.value,
        correlation_id=correlation_id,
        diagnostic=redact(f"pid {live.pid} adopté (démarré à la main)"),
    )
    return AdoptOutcome(
        component=component, adopted=True, detail=f"pid {live.pid} adopté : « launcher stop » peut maintenant l'arrêter"
    )
