"""Where the sixteen readiness checks get their facts (``domain/autonomy/readiness`` maps them to a verdict).

Every check answers from what the services *observe now* — an age, a count, a status — and says in one line why it is red.
None of them is given the benefit of the doubt: a component that has not spoken yet is not healthy, and a check that
cannot be evaluated is red, not green.

Two checks are red on purpose until their pieces exist, and say so:

* ``strategy_valid`` — no strategy is registered in the Python core yet (S01 is being ported); a ``strategy`` provider
  replaces the default when the strategy service exists;
* ``position_management`` — S01 defines no exit management (debt TD-09): an automatic position could not be managed.
  Autonomy refuses to start over that, deliberately.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timedelta

from trading_os.domain.accounts.models import Account
from trading_os.domain.autonomy.readiness import Fact, ReadinessFacts
from trading_os.domain.execution.commands import CommandState
from trading_os.domain.system.supervision import Severity
from trading_os.infrastructure.database.pool import Database
from trading_os.runtime.heartbeat import Heartbeat
from trading_os.runtime.scheduler import Scheduler
from trading_os.runtime.supervisor import Supervisor
from trading_os.services.accounts import AccountService
from trading_os.services.execution import ExecutionService
from trading_os.services.market_data import MarketDataService
from trading_os.services.positions import PositionService
from trading_os.services.reconciliation import ReconciliationService
from trading_os.services.risk import RiskService
from trading_os.shared.errors import NotFound, Unavailable
from trading_os.shared.time import Clock

CORE_BEAT_FRESH = timedelta(seconds=10)
SUPERVISOR_FRESH = timedelta(seconds=10)
POSITIONS_FRESH = timedelta(seconds=15)
AGENT_FRESH = timedelta(seconds=15)
RISK_FRESH = timedelta(seconds=20)
RECONCILIATION_FRESH = timedelta(seconds=90)

AccountCheck = Callable[[Account], Fact]

NO_STRATEGY = Fact(ok=False, detail="no strategy is registered in the Python core yet (S01 is not ported)")
NO_EXITS = Fact(
    ok=False, detail="S01 defines no exit management yet (TD-09): an automatic position could not be managed"
)


def _red(detail: str) -> Fact:
    return Fact(ok=False, detail=detail)


def _green(detail: str) -> Fact:
    return Fact(ok=True, detail=detail)


def _age(now: datetime, then: datetime | None) -> timedelta | None:
    return None if then is None else now - then


class ReadinessCollector:
    def __init__(
        self,
        *,
        accounts: AccountService,
        positions: PositionService,
        market: MarketDataService,
        risk: RiskService,
        execution: ExecutionService,
        reconciliation: ReconciliationService,
        supervisor: Supervisor,
        scheduler: Scheduler,
        heartbeat: Heartbeat,
        db: Database,
        clock: Clock,
        strategy: AccountCheck | None = None,
        exits: AccountCheck | None = None,
    ) -> None:
        self._accounts = accounts
        self._positions = positions
        self._market = market
        self._risk = risk
        self._execution = execution
        self._reconciliation = reconciliation
        self._supervisor = supervisor
        self._scheduler = scheduler
        self._heartbeat = heartbeat
        self._db = db
        self._clock = clock
        self._strategy = strategy
        self._exits = exits

    async def __call__(self) -> ReadinessFacts:
        now = self._clock.now()
        base = {"python_core": self._core(now), "database": await self._database()}
        account_id = self._accounts.active_account_id
        if account_id is None:
            return ReadinessFacts(**base, **self._without_account("no active account"))
        try:
            account = await self._accounts.effective(account_id)
        except NotFound:
            return ReadinessFacts(**base, **self._without_account("the active account no longer exists"))
        return ReadinessFacts(
            **base,
            mt5_connected=self._mt5(account, now),
            correct_account=await self._correct_account(account),
            symbols_available=self._symbols(account),
            risk_engine=self._risk_engine(account, now),
            sizing_valid=self._sizing(account),
            reconciliation=await self._reconciliation_fact(account, now),
            kill_switch_available=self._kill_switch(account),
            heartbeat=self._agent_heartbeat(account, now),
            supervisor=self._supervisor_fact(now),
            execution_engine=self._execution_engine(),
            strategy_valid=self._strategy(account) if self._strategy else NO_STRATEGY,
            position_management=self._exits(account) if self._exits else NO_EXITS,
            no_critical_incident=self._incidents(),
            account_limits_configured=self._limits(account),
        )

    @staticmethod
    def _without_account(why: str) -> dict[str, Fact]:
        names = (
            "mt5_connected", "correct_account", "symbols_available", "risk_engine", "sizing_valid", "reconciliation",
            "kill_switch_available", "heartbeat", "supervisor", "execution_engine", "strategy_valid",
            "position_management", "no_critical_incident", "account_limits_configured",
        )  # fmt: skip
        return {name: _red(why) for name in names}

    # ------------------------------------------------------------------------------------------ the checks
    def _core(self, now: datetime) -> Fact:
        age = _age(now, self._heartbeat.last_beat_at)
        if age is None or age > CORE_BEAT_FRESH:
            return _red("the core heartbeat has not beaten recently")
        stalled = self._scheduler.overdue(now)
        if stalled:
            return _red("jobs are not keeping up: " + ", ".join(s.name for s in stalled))
        return _green("the core is beating and its jobs are on time")

    async def _database(self) -> Fact:
        if await self._db.ping():
            return _green("the database answers")
        return _red(self._db.health.last_error or "the database does not answer")

    def _mt5(self, account: Account, now: datetime) -> Fact:
        if self._accounts.session(account.id) is None:
            return _red("the account is not connected")
        failures, error = self._positions.failures(account.id)
        if failures:
            return _red(f"{failures} failed read(s) in a row: {error}")
        age = _age(now, self._positions.updated_at(account.id))
        if age is None or age > POSITIONS_FRESH:
            return _red("the terminal has not been read recently")
        if not self._positions.terminal_connected(account.id):
            return _red("the terminal is not connected to its trade server")
        return _green(f"terminal read {age.total_seconds():.0f}s ago")

    async def _correct_account(self, account: Account) -> Fact:
        attached = await self._accounts.attached_account_id(account.id)
        if attached == account.id:
            return _green("the terminal is on the active account")
        return _red(f"the terminal reports {attached or 'no account'}, not {account.id}")

    def _symbols(self, account: Account) -> Fact:
        watched = self._market.watchlist(account.id)
        if not watched:
            return _red("no symbol is watched")
        missing = [
            s for s in watched if self._market.spec(account.id, s) is None or self._market.tick(account.id, s) is None
        ]
        if missing:
            return _red("no specification or quote yet for " + ", ".join(missing))
        return _green(f"{len(watched)} symbol(s) available")

    def _sizing(self, account: Account) -> Fact:
        watched = self._market.watchlist(account.id)
        if not watched:
            return _red("no symbol is watched")
        bad = []
        for symbol in watched:
            spec = self._market.spec(account.id, symbol)
            if (
                spec is None
                or spec.tick_size <= 0
                or spec.loss_tick_value <= 0
                or spec.volume_step <= 0
                or not spec.trade_allowed
            ):
                bad.append(symbol)
        if bad:
            return _red("the broker's specification cannot size " + ", ".join(bad))
        return _green("tick value, step and limits known for every watched symbol")

    def _risk_engine(self, account: Account, now: datetime) -> Fact:
        if self._risk.last_error:
            return _red(self._risk.last_error)
        age = _age(now, self._risk.last_cycle_at)
        if age is None or age > RISK_FRESH or self._risk.status(account.id) is None:
            return _red("the Risk Engine has not completed a cycle recently")
        return _green(f"last cycle {age.total_seconds():.0f}s ago")

    async def _reconciliation_fact(self, account: Account, now: datetime) -> Fact:
        failures = self._reconciliation.consecutive_failures(account.id)
        if failures:
            return _red(f"{failures} reconciliation run(s) in a row could not read their inputs")
        age = _age(now, self._reconciliation.last_success_at(account.id))
        if age is None or age > RECONCILIATION_FRESH:
            return _red("no reconciliation has completed recently")
        report = self._reconciliation.last_readable_report(account.id)
        if report is not None and report.critical:
            return _red(f"{len(report.critical)} critical divergence(s): {report.critical[0].detail}")
        try:
            doubtful = [
                c for c in await self._execution.in_doubt(account.id)
                if c.state in (CommandState.UNKNOWN, CommandState.RECONCILING)
            ]  # fmt: skip
        except Unavailable:
            return _red("commands in doubt cannot be checked: database unavailable")
        if doubtful:
            return _red(f"{len(doubtful)} command(s) in doubt")
        return _green(f"reconciled {age.total_seconds():.0f}s ago, nothing in doubt")

    def _kill_switch(self, account: Account) -> Fact:
        status = self._execution.agent_status(str(account.login))
        if status is None:
            return _red("no execution agent is connected: the kill switch cannot be set")
        if not status.can("halt"):
            return _red("the execution agent does not announce the halt capability")
        return _green("the execution agent can be halted")

    def _agent_heartbeat(self, account: Account, now: datetime) -> Fact:
        login = str(account.login)
        if self._execution.agent_status(login) is None:
            return _red("no execution agent is connected")
        age = _age(now, self._execution.last_heartbeat(login))
        if age is None or age > AGENT_FRESH:
            return _red("the execution agent has gone silent")
        return _green(f"agent heartbeat {age.total_seconds():.0f}s ago")

    def _supervisor_fact(self, now: datetime) -> Fact:
        age = _age(now, self._supervisor.last_tick_at)
        if age is None or age > SUPERVISOR_FRESH:
            return _red("the supervisor has not run recently")
        if self._supervisor.status() in (Severity.HIGH, Severity.CRITICAL):
            worst = next(f for f in self._supervisor.findings if f.severity in (Severity.HIGH, Severity.CRITICAL))
            return _red(f"{worst.code}: {worst.detail}")
        return _green("the supervisor is running and sees nothing serious")

    def _execution_engine(self) -> Fact:
        if self._execution.last_error:
            return _red(self._execution.last_error)
        return _green("the execution engine records its commands")

    def _incidents(self) -> Fact:
        critical = [i for i in self._supervisor.open_incidents() if i.severity is Severity.CRITICAL]
        if critical:
            return _red(f"{len(critical)} critical incident(s) open: {critical[0].code}")
        return _green("no critical incident is open")

    @staticmethod
    def _limits(account: Account) -> Fact:
        missing = []
        if not account.risk_profile.configured:
            missing.append("the risk limits have not been written by the user (ADR 0015)")
        if account.risk_profile.drawdown.reference_balance is None:
            missing.append("the reference capital is not fixed")
        if missing:
            return _red("; ".join(missing))
        return _green("limits and reference capital are set")
