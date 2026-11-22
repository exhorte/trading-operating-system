"""The journal of a terminal's deployment state (ADR 0039 § 3.5): one ``MT5_STATE_TRANSITION`` event per change of state, ``MT5_STATE_ANOMALY`` when the change is
a jump the table does not know, and the last state kept in the registry — only to check the table and to recognise a disconnection, never as proof."""

from __future__ import annotations

from trading_os.launcher.events import EventLog, EventSeverity, EventType
from trading_os.launcher.mt5.model import StateRecord, TerminalEntry
from trading_os.launcher.mt5.states import StateDecision
from trading_os.launcher.mt5.terminals import TerminalRegistry
from trading_os.shared.time import Clock


class StateJournal:
    def __init__(self, registry: TerminalRegistry, events: EventLog, clock: Clock) -> None:
        self._registry = registry
        self._events = events
        self._clock = clock

    def record(self, entry: TerminalEntry, decision: StateDecision, *, trigger: str, correlation_id: str) -> bool:
        """Journal a state if it is not the one already journalled. True when something was written."""
        previous = entry.last_state.state if entry.last_state is not None else None
        if previous == decision.state.value:
            return False
        reasons = ", ".join(decision.codes) or "aucun"
        self._events.emit(
            EventType.MT5_STATE_TRANSITION,
            component="mt5",
            correlation_id=correlation_id,
            instance_id=entry.terminal_id,
            account_id=entry.declared.account_id,
            diagnostic=f"{previous or '—'} → {decision.state.value} ; motifs : {reasons} ; déclencheur : {trigger}",
        )
        if decision.anomaly:
            self._events.emit(
                EventType.MT5_STATE_ANOMALY,
                component="mt5",
                correlation_id=correlation_id,
                severity=EventSeverity.WARNING,
                instance_id=entry.terminal_id,
                account_id=entry.declared.account_id,
                diagnostic=f"saut observé hors de la table : {previous or '—'} → {decision.state.value}",
            )
        self._registry.record_state(
            entry.terminal_id, StateRecord(state=decision.state.value, at=self._clock.now(), codes=decision.codes)
        )
        return True
