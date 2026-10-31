"""The supervisor (mission § 26): every couple of seconds it looks at every part of the core, turns what it sees into
*findings*, and applies the remedy the policy table (``domain/system/supervision``) assigns to each.

    collect ─▶ findings ─▶ actions_for(finding, autonomy mode) ─▶ SAFE · RECONNECT · RECONCILE · DISARM · HALT
                    └─▶ incidents (opened while a fault lasts, resolved when it clears)  └─▶ SystemHealthChanged

What each action means here:

* **SAFE** — block new entries. Nothing is stopped; the Risk Engine reads ``degraded_for`` and answers ``system_degraded``
  to every intent while any reason stands. It lifts by itself when the fault clears.
* **RECONNECT** — bring the terminal back: re-attach the account with a back-off (5 s, doubling, capped at a minute). The
  accounts the user connected are *wanted* until the user disconnects them: a lost link is retried, not forgotten.
* **RECONCILE** — compare with the broker now (throttled).
* **DISARM** — drop the automatic modes to OBSERVE; a human climbs again.
* **HALT** — autonomy HALTED, the execution agents told, an incident open; leaving it takes a human. Done once per
  transition (and re-told to an agent that connects while halted), not on every tick.

A fault is *persisting* once it has outlasted a minute; that is what escalates a lost terminal to DISARM and a failing
reconciliation to HALT. What the supervisor does **not** do: place, modify or close anything, or lift a halt.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from trading_os.domain.autonomy.state import AUTOMATIC_MODES, AutonomyMode
from trading_os.domain.events import (
    AccountConnected,
    AccountDisconnected,
    HeartbeatMissed,
    IncidentOpened,
    IncidentResolved,
    SystemHealthChanged,
)
from trading_os.domain.execution.commands import CommandState
from trading_os.domain.positions.reconciliation import MismatchKind, MismatchSeverity
from trading_os.domain.system.incidents import Incident
from trading_os.domain.system.supervision import Action, Finding, Severity, actions_for, worst
from trading_os.infrastructure.database.pool import Database
from trading_os.infrastructure.database.repositories import Repositories
from trading_os.runtime.scheduler import Scheduler
from trading_os.services.accounts import AccountService
from trading_os.services.autonomy import AutonomyService
from trading_os.services.execution import ExecutionService
from trading_os.services.market_data import MarketDataService
from trading_os.services.positions import PositionService
from trading_os.services.reconciliation import ReconciliationService
from trading_os.services.risk import RiskService
from trading_os.shared.errors import TradingOsError, Unavailable
from trading_os.shared.events.dispatcher import EventDispatcher
from trading_os.shared.ids import new_id
from trading_os.shared.time import Clock

logger = logging.getLogger(__name__)

PERSIST_AFTER = timedelta(seconds=60)  # a fault this old has outlived the grace of its first remedy
STARTUP_GRACE = timedelta(seconds=30)  # a connection this young has not had time to produce data yet
POSITIONS_STALE_AFTER = timedelta(seconds=15)
AGENT_SILENT_AFTER = timedelta(seconds=15)  # the agent beats every 5 s
RISK_STALE_AFTER = timedelta(seconds=20)
RECONCILE_STALE_AFTER = timedelta(seconds=90)
RECONCILE_FAILURES = 3  # consecutive unreadable runs
IN_DOUBT_AFTER = timedelta(seconds=30)  # a command silent for this long is genuinely in doubt, not just in flight
CRITICAL_JOB_STREAK = 5  # unexpected failures in a row of a critical job: a bug, not a condition
RECONNECT_BACKOFF = (5.0, 10.0, 20.0, 40.0, 60.0)
RECONCILE_EVERY = timedelta(seconds=10)
INCIDENT_FROM = Severity.HIGH


@dataclass
class _Backoff:
    attempts: int = 0
    next_at: datetime | None = None


@dataclass
class _State:
    since: dict[str, datetime] = field(default_factory=dict)  # finding key → first seen
    incidents: dict[str, Incident] = field(default_factory=dict)  # finding key → its open incident
    health: tuple[Severity, frozenset[str]] | None = None
    safe: dict[str | None, list[str]] = field(default_factory=dict)
    wanted: set[str] = field(default_factory=set)
    backoff: dict[str, _Backoff] = field(default_factory=dict)
    last_reconcile: dict[str, datetime] = field(default_factory=dict)
    agent_silent: set[str] = field(default_factory=set)


def _key(finding: Finding) -> str:
    return f"{finding.code}:{finding.account_id or '*'}"


class Supervisor:
    def __init__(
        self,
        *,
        accounts: AccountService,
        positions: PositionService,
        market: MarketDataService,
        risk: RiskService,
        execution: ExecutionService,
        reconciliation: ReconciliationService,
        autonomy: AutonomyService,
        db: Database,
        scheduler: Scheduler,
        repos: Repositories,
        events: EventDispatcher,
        clock: Clock,
    ) -> None:
        self._accounts = accounts
        self._positions = positions
        self._market = market
        self._risk = risk
        self._execution = execution
        self._reconciliation = reconciliation
        self._autonomy = autonomy
        self._db = db
        self._scheduler = scheduler
        self._repos = repos
        self._events = events
        self._clock = clock
        self._state = _State()
        self._current: list[Finding] = []
        self._pending_missed: list[HeartbeatMissed] = []
        self.last_tick_at: datetime | None = None

    # ------------------------------------------------------------------------------------------ wiring
    def subscribe(self) -> None:
        """Remember which accounts the user wants connected: a link that drops is retried, one the user closed is not."""
        self._events.subscribe(AccountConnected, self._on_connected)
        self._events.subscribe(AccountDisconnected, self._on_disconnected)

    def _on_connected(self, event: AccountConnected) -> None:
        if event.account_id is not None:
            self._state.wanted.add(event.account_id)

    def _on_disconnected(self, event: AccountDisconnected) -> None:
        if event.account_id is not None and event.reason in {"user", "shutdown"}:
            self._state.wanted.discard(event.account_id)
            self._state.backoff.pop(event.account_id, None)

    async def start(self) -> None:
        """Pick up the incidents that were open when the core last stopped; the first tick resolves those that are over."""
        try:
            for incident in await self._repos.incidents.open_incidents():
                self._state.incidents[f"{incident.code}:{incident.account_id or '*'}"] = incident
        except Unavailable:
            logger.warning("supervisor: open incidents could not be read at startup")

    # ------------------------------------------------------------------------------------------ reading
    @property
    def findings(self) -> list[Finding]:
        return list(self._current)

    def status(self) -> Severity:
        return worst(self._current)

    def degraded_for(self, account_id: str) -> list[str]:
        """Why entries are blocked for this account right now (empty = not in SAFE mode)."""
        return [*self._state.safe.get(None, []), *self._state.safe.get(account_id, [])]

    def wanted(self) -> set[str]:
        return set(self._state.wanted)

    def open_incidents(self) -> list[Incident]:
        return list(self._state.incidents.values())

    # ------------------------------------------------------------------------------------------ the cycle
    async def tick(self) -> None:
        now = self._clock.now()
        raw = await self._collect(now)
        findings = self._with_persistence(raw, now)
        self._current = findings
        self.last_tick_at = now
        await self._act(findings, now)
        await self._track_incidents(findings, now)
        await self._publish_health(findings)

    def _with_persistence(self, raw: list[Finding], now: datetime) -> list[Finding]:
        keys = {_key(f) for f in raw}
        for key in [k for k in self._state.since if k not in keys]:
            del self._state.since[key]
        out: list[Finding] = []
        for finding in raw:
            first = self._state.since.setdefault(_key(finding), now)
            out.append(finding.model_copy(update={"persisting": now - first >= PERSIST_AFTER}))
        return out

    # ------------------------------------------------------------------------------------------ collecting
    async def _collect(self, now: datetime) -> list[Finding]:
        found = self._core(now)
        if (down := await self._database(now)) is not None:
            found.append(down)
        connected = set(self._accounts.connected_ids())
        for account_id in sorted(connected):
            found += await self._account(account_id, now)
        for account_id in sorted(self._state.wanted - connected):
            found.append(
                Finding(
                    code="mt5_disconnected", component="mt5", severity=Severity.HIGH, observed_at=now,
                    account_id=account_id, detail="the account is not connected and is being retried",
                )
            )  # fmt: skip
        return found

    def _core(self, now: datetime) -> list[Finding]:
        found: list[Finding] = []
        for job in self._scheduler.overdue(now):
            age = (now - (job.last_finished_at or job.registered_at or now)).total_seconds()
            found.append(
                Finding(
                    code="scheduler_stalled", component=f"job:{job.name}", severity=Severity.HIGH, observed_at=now,
                    detail=f"{job.name} has not finished a run for {age:.0f}s (every {job.interval_s:g}s)",
                )
            )  # fmt: skip
        for job in self._scheduler.stats():
            if job.critical and job.unexpected_streak >= CRITICAL_JOB_STREAK:
                found.append(
                    Finding(
                        code="critical_error", component=f"job:{job.name}", severity=Severity.CRITICAL,
                        observed_at=now,
                        detail=f"{job.name} failed {job.unexpected_streak} times in a row unexpectedly: {job.last_error}",
                    )
                )  # fmt: skip
        return found

    async def _database(self, now: datetime) -> Finding | None:
        if await self._db.ping():
            return None
        return Finding(
            code="database_unavailable", component="database", severity=Severity.HIGH, observed_at=now,
            detail=self._db.health.last_error or "the database does not answer",
        )  # fmt: skip

    async def _account(self, account_id: str, now: datetime) -> list[Finding]:
        session = self._accounts.session(account_id)
        if session is None:
            return []
        young = now - session.connected_at < STARTUP_GRACE
        found: list[Finding] = []

        def add(code: str, component: str, severity: Severity, detail: str) -> None:
            found.append(
                Finding(code=code, component=component, severity=severity, detail=detail, observed_at=now,
                        account_id=account_id)
            )  # fmt: skip

        # MT5: the reader answers, the poll is fresh, the terminal is connected to its trade server.
        failures, error = self._positions.failures(account_id)
        updated = self._positions.updated_at(account_id)
        if failures >= 2:
            add("mt5_disconnected", "mt5", Severity.HIGH, f"{failures} failed reads in a row: {error}")
        elif updated is not None and now - updated > POSITIONS_STALE_AFTER:
            add("mt5_disconnected", "mt5", Severity.HIGH, f"last read {(now - updated).total_seconds():.0f}s ago")
        elif updated is None and not young:
            add("mt5_disconnected", "mt5", Severity.HIGH, "the terminal has not been read since the connection")
        elif updated is not None and not self._positions.terminal_connected(account_id):
            add("mt5_disconnected", "mt5", Severity.HIGH, "the terminal is not connected to its trade server")

        fresh, detail = self._market.feed_status(account_id, now)
        if not fresh and not (young and detail == "market data not started"):
            add("stale_market_data", "market_data", Severity.MEDIUM, detail)

        last_cycle = self._risk.last_cycle_at
        if self._risk.last_error:
            add("risk_engine_error", "risk", Severity.HIGH, self._risk.last_error)
        elif not young and (last_cycle is None or now - last_cycle > RISK_STALE_AFTER):
            add("risk_engine_stale", "risk", Severity.MEDIUM, "no risk cycle has completed recently")

        if self._execution.last_error:
            add("execution_failure", "execution", Severity.HIGH, self._execution.last_error)
        found += await self._in_doubt(account_id, now)
        found += self._agent(account_id, session.account.login, now, young)
        found += self._reconciliation_findings(account_id, now, young)
        return found

    async def _in_doubt(self, account_id: str, now: datetime) -> list[Finding]:
        try:
            doubtful = [
                c for c in await self._execution.in_doubt(account_id)
                if c.state in (CommandState.UNKNOWN, CommandState.RECONCILING)
            ]  # fmt: skip
        except Unavailable:
            return []  # the database finding already says so
        if not doubtful:
            return []
        oldest = min(c.sent_at or c.created_at for c in doubtful)
        if now - oldest < IN_DOUBT_AFTER:
            return []
        return [
            Finding(
                code="unknown_command", component="execution", severity=Severity.HIGH, observed_at=now,
                account_id=account_id,
                detail=f"{len(doubtful)} command(s) in doubt, the oldest for {(now - oldest).total_seconds():.0f}s",
            )
        ]  # fmt: skip

    def _agent(self, account_id: str, login: int, now: datetime, young: bool) -> list[Finding]:
        """Only the active account, and only in modes that send through the agent: elsewhere its absence is not a fault."""
        needs = self._autonomy.mode in (AutonomyMode.CONFIRM, *AUTOMATIC_MODES)
        if not needs or account_id != self._accounts.active_account_id:
            self._state.agent_silent.discard(account_id)
            return []
        status = self._execution.agent_status(str(login))
        if status is None:
            if young:
                return []
            return [self._silent_agent(account_id, now, None, "no execution agent is connected for this account")]
        beat = self._execution.last_heartbeat(str(login))
        age = None if beat is None else now - beat
        if age is not None and age <= AGENT_SILENT_AFTER:
            self._state.agent_silent.discard(account_id)
            return []
        return [self._silent_agent(account_id, now, age, "the execution agent has gone silent")]

    def _silent_agent(self, account_id: str, now: datetime, age: timedelta | None, why: str) -> Finding:
        seconds = None if age is None else age.total_seconds()
        if account_id not in self._state.agent_silent:
            self._state.agent_silent.add(account_id)
            self._pending_missed.append(
                HeartbeatMissed(account_id=account_id, component="execution-agent", age_seconds=seconds)
            )
        detail = why if seconds is None else f"{why} ({seconds:.0f}s without a heartbeat)"
        return Finding(
            code="agent_heartbeat_stale", component="execution-agent", severity=Severity.HIGH, observed_at=now,
            account_id=account_id, detail=detail,
        )  # fmt: skip

    def _reconciliation_findings(self, account_id: str, now: datetime, young: bool) -> list[Finding]:
        found: list[Finding] = []

        def add(code: str, severity: Severity, detail: str) -> None:
            found.append(
                Finding(code=code, component="reconciliation", severity=severity, detail=detail, observed_at=now,
                        account_id=account_id)
            )  # fmt: skip

        failures = self._reconciliation.consecutive_failures(account_id)
        last_ok = self._reconciliation.last_success_at(account_id)
        if failures >= RECONCILE_FAILURES:
            add("reconciliation_failed", Severity.HIGH, f"{failures} runs in a row could not read MT5 or the database")
        elif not young and (last_ok is None or now - last_ok > RECONCILE_STALE_AFTER):
            add("reconciliation_failed", Severity.HIGH, "no reconciliation has completed recently")
        report = self._reconciliation.last_readable_report(account_id)  # (a run that could not read clears nothing)
        if report is None:
            return found
        stray = [m for m in report.critical if m.kind is MismatchKind.UNEXPECTED_POSITION or (
            m.kind is MismatchKind.ORDER_MISMATCH)]  # fmt: skip
        if stray:
            add("unexpected_position", Severity.CRITICAL, "; ".join(m.detail for m in stray[:3]))
        wrong_account = [m for m in report.critical if m.kind is MismatchKind.ACCOUNT_MISMATCH]
        if wrong_account:
            add("account_mismatch", Severity.HIGH, wrong_account[0].detail)
        diverged = [
            m for m in report.critical
            if m.severity is MismatchSeverity.CRITICAL
            and m.kind not in (MismatchKind.UNEXPECTED_POSITION, MismatchKind.ORDER_MISMATCH,
                               MismatchKind.ACCOUNT_MISMATCH, MismatchKind.UNKNOWN_EXECUTION)
        ]  # fmt: skip
        if diverged:
            add("reconciliation_mismatch", Severity.HIGH, "; ".join(m.detail for m in diverged[:3]))
        return found

    # ------------------------------------------------------------------------------------------ acting
    async def _act(self, findings: list[Finding], now: datetime) -> None:
        mode = self._autonomy.mode
        safe: dict[str | None, list[str]] = {}
        reconnect: set[str] = set()
        reconcile: set[str] = set()
        disarm: list[Finding] = []
        halt: list[Finding] = []
        for finding in findings:
            for action in actions_for(finding, mode):
                if action is Action.SAFE:
                    safe.setdefault(finding.account_id, []).append(f"{finding.code}: {finding.detail}")
                elif action is Action.RECONNECT and finding.account_id:
                    reconnect.add(finding.account_id)
                elif action is Action.RECONCILE and finding.account_id:
                    reconcile.add(finding.account_id)
                elif action is Action.DISARM:
                    disarm.append(finding)
                elif action is Action.HALT:
                    halt.append(finding)
        self._state.safe = safe
        for account_id in [a for a in self._state.backoff if a not in reconnect]:
            del self._state.backoff[account_id]  # healthy again: the next loss starts from a short delay
        await self._flush_missed()
        await self._reconnect(sorted(reconnect), now)
        await self._reconcile(sorted(reconcile), now)
        if halt:
            if not self._autonomy.halted():
                reason = "; ".join(f"{f.code} ({f.detail})" for f in halt)[:400]
                await self._autonomy.halt(reason, actor="supervisor")
        elif disarm and mode in AUTOMATIC_MODES:
            reason = "; ".join(f"{f.code} ({f.detail})" for f in disarm)[:400]
            await self._autonomy.disarm(AutonomyMode.OBSERVE, reason=f"supervisor: {reason}", actor="supervisor")
        await self._enforce_halt()

    async def _flush_missed(self) -> None:
        pending, self._pending_missed = self._pending_missed, []
        for event in pending:
            await self._events.publish(event)

    async def _reconnect(self, account_ids: list[str], now: datetime) -> None:
        for account_id in account_ids:
            state = self._state.backoff.setdefault(account_id, _Backoff())
            if state.next_at is not None and now < state.next_at:
                continue
            delay = RECONNECT_BACKOFF[min(state.attempts, len(RECONNECT_BACKOFF) - 1)]
            state.attempts += 1
            state.next_at = now + timedelta(seconds=delay)
            try:
                if self._accounts.is_connected(account_id):
                    await self._accounts.reconnect(account_id)
                else:
                    await self._accounts.connect(account_id)
                logger.info("supervisor: %s re-attached (attempt %d)", account_id, state.attempts)
            except TradingOsError as error:
                logger.warning(
                    "supervisor: reconnecting %s failed (attempt %d): %s",
                    account_id,
                    state.attempts,
                    error.safe_message,
                )

    async def _reconcile(self, account_ids: list[str], now: datetime) -> None:
        for account_id in account_ids:
            last = self._state.last_reconcile.get(account_id)
            if last is not None and now - last < RECONCILE_EVERY:
                continue
            self._state.last_reconcile[account_id] = now
            try:
                await self._reconciliation.reconcile(account_id)
            except TradingOsError as error:
                logger.warning("supervisor: reconciling %s failed: %s", account_id, error.safe_message)

    async def _enforce_halt(self) -> None:
        """A halt is only worth anything if every agent is halted. One that connected after the halt was never told."""
        if not self._autonomy.halted():
            return
        for login in self._execution.registered_logins():
            status = self._execution.agent_status(login)
            if status is not None and status.halted is not True:
                await self._execution.halt_agents("autonomy is HALTED")
                return

    # ------------------------------------------------------------------------------------------ incidents and health
    async def _track_incidents(self, findings: list[Finding], now: datetime) -> None:
        present = {_key(f): f for f in findings if f.severity in (Severity.HIGH, Severity.CRITICAL)}
        for key, finding in present.items():
            existing = self._state.incidents.get(key)
            if existing is not None:
                continue
            incident = Incident(
                incident_id=new_id("inc"), code=finding.code, component=finding.component, severity=finding.severity,
                detail=finding.detail, opened_at=self._state.since.get(key, now), account_id=finding.account_id,
            )  # fmt: skip
            try:
                await self._repos.incidents.open(incident)
            except Unavailable:
                continue  # retried next tick, with the original opening time
            self._state.incidents[key] = incident
            await self._events.publish(IncidentOpened(account_id=incident.account_id, incident=incident))
        for key in [k for k in self._state.incidents if k not in present]:
            incident = self._state.incidents[key]
            try:
                await self._repos.incidents.resolve(incident.incident_id, now, "the condition cleared")
            except Unavailable:
                continue
            del self._state.incidents[key]
            resolved = incident.model_copy(update={"resolved_at": now, "resolution": "the condition cleared"})
            await self._events.publish(IncidentResolved(account_id=incident.account_id, incident=resolved))

    async def _publish_health(self, findings: list[Finding]) -> None:
        signature = (worst(findings), frozenset(f"{_key(f)}:{f.severity.value}" for f in findings))
        if signature == self._state.health:
            return
        self._state.health = signature
        await self._events.publish(SystemHealthChanged(status=signature[0], findings=findings))
