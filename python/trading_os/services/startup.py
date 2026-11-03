"""« Démarrer le système » (ADR 0034): bring the trading system from stopped to a *verified* starting mode, and say plainly what
works and what blocks.

The core already starts all its engines when the process starts (``runtime/engine.py``) and the autonomy always begins OFF. So « start »
is not a second launcher: it **verifies** each component in the order of the mission (application, services, database, terminal,
account, agent, reconciliation, market data, strategy, guardian, risk, autonomy), forces the two things that are only cheap to do on
purpose — a fresh read of the terminal and a reconciliation — and then climbs the autonomy ladder from OFF to OBSERVE (or, when asked,
PAPER / CONFIRM). It never climbs further: authorising automatic trading is :meth:`authorize_automatic`, a separate gesture.

Nothing here sends an order, connects with a password, or arms by itself on a restart. The only connection it attempts is the one the
terminal already holds (no secret), for the account the trader selected.
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import timedelta

from trading_os import __version__
from trading_os.domain.accounts.models import Account, Environment
from trading_os.domain.autonomy import plan_modes
from trading_os.domain.autonomy.plan_modes import PlanMode
from trading_os.domain.autonomy.readiness import ReadinessReport
from trading_os.domain.autonomy.state import AutonomyMode, rank
from trading_os.domain.events import SystemStartFinished, SystemStartRequested
from trading_os.domain.execution.commands import CommandState
from trading_os.domain.system.startup import (
    REAL_ACCOUNT_BANNER,
    START_TARGETS,
    AccountPanel,
    EntryCheck,
    StartupRun,
    StartupRunState,
    StartupStage,
    StartupStageState,
    StartupStatus,
)
from trading_os.infrastructure.database.pool import Database
from trading_os.runtime.heartbeat import Heartbeat
from trading_os.runtime.supervisor import Supervisor
from trading_os.services.accounts import AccountService
from trading_os.services.autonomy import AutonomyService
from trading_os.services.execution import ExecutionService
from trading_os.services.guardian import AccountGuardianService
from trading_os.services.market_data import MarketDataService
from trading_os.services.positions import PositionService
from trading_os.services.reconciliation import ReconciliationService
from trading_os.services.risk import RiskService
from trading_os.services.strategy import StrategyService
from trading_os.shared.errors import Conflict, Forbidden, TradingOsError, ValidationFailed
from trading_os.shared.events.dispatcher import EventDispatcher
from trading_os.shared.time import Clock

logger = logging.getLogger(__name__)

GUARDIAN_FRESH = timedelta(seconds=30)
STAGE_LABELS = {
    "application": "Application (cockpit et cœur)",
    "services": "Services backend",
    "database": "Base de données",
    "terminal": "Terminal MT5",
    "account": "Compte",
    "agent": "Agent MQL5",
    "reconciliation": "Réconciliation positions et ordres",
    "market_data": "Market Data Engine",
    "strategy": "Strategy Engine",
    "guardian": "Account Guardian",
    "risk": "Risk Engine",
    "autonomy": "Mode d'autonomie",
    "trading": "Autorisation de prendre des positions",
}
BLOCKING_STAGES = frozenset({"database", "terminal", "account"})


@dataclass(frozen=True)
class Timings:
    """How long the sequence waits for a component that is still warming up (agent connecting, first quotes)."""

    agent_wait_s: float = 5.0
    market_wait_s: float = 10.0
    step_s: float = 1.0


class StartupService:
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
        guardian: AccountGuardianService,
        strategy: StrategyService,
        supervisor: Supervisor,
        heartbeat: Heartbeat,
        db: Database,
        events: EventDispatcher,
        clock: Clock,
        timings: Timings | None = None,
    ) -> None:
        self._accounts = accounts
        self._positions = positions
        self._market = market
        self._risk = risk
        self._execution = execution
        self._reconciliation = reconciliation
        self._autonomy = autonomy
        self._guardian = guardian
        self._strategy = strategy
        self._supervisor = supervisor
        self._heartbeat = heartbeat
        self._db = db
        self._events = events
        self._clock = clock
        self._timings = timings or Timings()
        self._run: StartupRun | None = None
        self._task: asyncio.Task[None] | None = None

    # ------------------------------------------------------------------------------------------ starting
    async def begin(
        self, target: AutonomyMode = AutonomyMode.OBSERVE, *, acknowledge_real_account: bool = False
    ) -> StartupRun:
        """Start the sequence in the background and return at once; the cockpit follows it through :meth:`status`. A second call while
        a run is going on returns that run — a double click starts nothing twice."""
        if target not in START_TARGETS:
            raise ValidationFailed(
                f"starting climbs to OBSERVE, PAPER or CONFIRM at most, not {target.value}: authorising automatic trading is a separate gesture",
                code="invalid_target",
            )
        if self._run is not None and self._run.state is StartupRunState.RUNNING:
            return self._run
        account = await self._selected_account()
        if (
            account is not None
            and account.environment is Environment.LIVE
            and rank(target) >= rank(AutonomyMode.CONFIRM)
            and not acknowledge_real_account
        ):
            raise Forbidden(
                "real account: starting up to CONFIRM needs the explicit confirmation of the trader",
                code="real_account_confirmation_required",
            )
        run = StartupRun(
            run_id=uuid.uuid4().hex[:12],
            state=StartupRunState.RUNNING,
            target_mode=target,
            started_at=self._clock.now(),
        )
        self._run = run
        await self._events.publish(
            SystemStartRequested(
                account_id=account.id if account else None, correlation_id=run.run_id, run_id=run.run_id,
                target_mode=target,
            )
        )  # fmt: skip
        self._task = asyncio.create_task(self._execute(run.run_id, target), name=f"startup-{run.run_id}")
        return run

    async def join(self) -> None:
        """Wait for the run in progress, if any (tests, and a graceful stop)."""
        if self._task is not None:
            await asyncio.shield(self._task)

    async def _execute(self, run_id: str, target: AutonomyMode) -> None:
        try:
            state, reached, message, blocked_on = await self._sequence(target)
        except asyncio.CancelledError:
            raise
        except Exception as error:  # a bug must never leave a run « RUNNING » for ever
            logger.exception("startup: the sequence failed unexpectedly")
            state, reached, message, blocked_on = (
                StartupRunState.BLOCKED, None, f"the start-up failed unexpectedly ({type(error).__name__})", [],
            )  # fmt: skip
        self._finish(state, reached, message, blocked_on)
        run = self._run
        account = await self._selected_account_quietly()
        await self._events.publish(
            SystemStartFinished(
                account_id=account.id if account else None, correlation_id=run_id, run_id=run_id,
                outcome={StartupRunState.DONE: "done", StartupRunState.PARTIAL: "partial"}.get(state, "blocked"),
                reached_mode=run.reached_mode if run else None, message=message, blocked_on=blocked_on,
            )
        )  # fmt: skip

    def _finish(
        self, state: StartupRunState, reached: AutonomyMode | None, message: str, blocked_on: list[str]
    ) -> None:
        if self._run is None:
            return
        self._run = self._run.model_copy(
            update={
                "state": state, "finished_at": self._clock.now(), "current_stage": None, "reached_mode": reached,
                "message": message, "blocked_on": blocked_on,
            }
        )  # fmt: skip

    def _at(self, stage_id: str) -> None:
        if self._run is not None:
            self._run = self._run.model_copy(update={"current_stage": stage_id})

    # ------------------------------------------------------------------------------------------ the sequence
    async def _sequence(self, target: AutonomyMode) -> tuple[StartupRunState, AutonomyMode | None, str, list[str]]:
        blocked = StartupRunState.BLOCKED
        # 1-3. the application, its services, the database
        self._at("application")
        self._at("services")
        self._at("database")
        if not await self._db.ping():
            return (
                blocked,
                None,
                "the database does not answer: nothing can be recorded, so nothing starts",
                ["database"],
            )
        if self._autonomy.halted():
            return (
                blocked,
                None,
                "the system is HALTED: acknowledge the halt (it lands on OFF) before starting",
                ["autonomy"],
            )

        # 4-5. the account, then the terminal it is read from
        self._at("account")
        account = await self._selected_account()
        if account is None:
            return blocked, None, "no account is selected: register or select one in Settings", ["account"]
        if self._accounts.session(account.id) is None:
            try:
                await self._accounts.connect(
                    account.id
                )  # no password: the terminal already holds its session (ADR 0013)
            except TradingOsError as error:
                return blocked, None, f"the account could not be connected: {error.safe_message}", ["account"]
        self._at("terminal")
        if not await self._read_terminal(account.id):
            return (
                blocked,
                None,
                "the terminal could not be read, or is not connected to its trade server",
                ["terminal"],
            )
        attached = await self._accounts.attached_account_id(account.id)
        if attached != account.id:
            return (
                blocked, None, f"the terminal is on {attached or 'no account'}, not on the selected account {account.id}",
                ["account"],
            )  # fmt: skip

        # 6. the agent: it connects by itself, give it a moment
        self._at("agent")
        await self._wait(lambda: self._agent_ok(account), self._timings.agent_wait_s)
        # 7. the broker, compared with the database — on purpose, now
        self._at("reconciliation")
        try:
            await self._reconciliation.reconcile(account.id)
        except TradingOsError as error:
            logger.warning("startup: the reconciliation could not run: %s", error.safe_message)
        # 8. market data
        self._at("market_data")
        await self._market.poll_ticks(account.id)
        await self._wait(
            lambda: self._market.feed_status(account.id, self._clock.now())[0], self._timings.market_wait_s
        )
        # 9-11. the engines that judge: one pass each, now
        self._at("strategy")
        self._at("guardian")
        try:
            await self._guardian.guard(account.id)
        except TradingOsError as error:
            logger.warning("startup: the guardian could not run: %s", error.safe_message)
        self._at("risk")
        try:
            await self._risk.evaluate(account.id)
        except TradingOsError as error:
            logger.warning("startup: the risk cycle could not run: %s", error.safe_message)

        # 12. the autonomy ladder, one rung at a time, never beyond CONFIRM
        self._at("autonomy")
        reached = self._autonomy.mode
        for rung in (AutonomyMode.OBSERVE, AutonomyMode.PAPER, AutonomyMode.CONFIRM):
            if rank(rung) > rank(target) or rank(rung) <= rank(reached):
                continue
            if rung is AutonomyMode.CONFIRM:  # the first rung that can send an order: every condition of § 2.2
                red = [
                    c for c in await self._entry_checks(account, fresh=True) if not c.ok
                ]  # at this instant, not from the cache
                if red:
                    ids = [c.check_id for c in red]
                    return (
                        StartupRunState.PARTIAL, reached,
                        f"started in {reached.value}; CONFIRM is held back by {len(red)} check(s): {', '.join(ids)}", ids,
                    )  # fmt: skip
            try:
                await self._autonomy.arm(rung, actor="startup")
            except TradingOsError as error:
                return (
                    StartupRunState.PARTIAL if reached is not AutonomyMode.OFF else blocked,
                    reached,
                    error.safe_message,
                    ["autonomy"],
                )
            reached = rung
        self._at("trading")
        return StartupRunState.DONE, reached, f"the system is running in {reached.value}", []

    async def _wait(self, ready: Callable[[], bool], seconds: float) -> bool:
        waited = 0.0
        while not ready():
            if waited >= seconds:
                return False
            await asyncio.sleep(self._timings.step_s)
            waited += self._timings.step_s
        return True

    async def _read_terminal(self, account_id: str) -> bool:
        try:
            read = await self._positions.poll(account_id)
        except TradingOsError:
            return False
        return read and self._positions.terminal_connected(account_id)

    # ------------------------------------------------------------------------------------------ authorising automatic trading
    async def authorize_automatic(self, *, acknowledge_real_account: bool = False) -> tuple[AutonomyMode, PlanMode]:
        """Climb one rung from CONFIRM to ARMED, or from ARMED to AUTONOMOUS (DEMO_AUTO / LIVE_AUTO in the plan's words). Explicit,
        one rung, and only with every condition green *now*; a real account needs the trader's explicit confirmation."""
        account = await self._selected_account()
        if account is None:
            raise Conflict("no account is selected", code="no_active_account")
        mode = self._autonomy.effective_mode(account)
        nxt = _next_automatic(mode)
        if nxt is None:
            raise ValidationFailed(
                f"automatic trading is authorised from CONFIRM (or ARMED), not from {mode.value}: start the system and climb first",
                code="not_a_step_up",
            )
        if account.environment is Environment.LIVE and not acknowledge_real_account:
            raise Forbidden(
                "real account: authorising automatic trading needs the explicit confirmation of the trader",
                code="real_account_confirmation_required",
            )
        red = [c for c in await self._entry_checks(account, fresh=True) if not c.ok]
        if red:
            raise Forbidden(
                "not every condition holds: " + ", ".join(c.check_id for c in red), code="not_ready",
                details={"blockers": [c.check_id for c in red], "checks": [c.model_dump(mode="json") for c in red]},
            )  # fmt: skip
        await self._autonomy.arm(nxt, actor="user")
        return nxt, plan_modes.plan_mode(nxt, account.environment)

    # ------------------------------------------------------------------------------------------ the picture
    async def status(self) -> StartupStatus:
        now = self._clock.now()
        account = await self._selected_account_quietly()
        ceiling = await self._autonomy.ceiling()
        mode = self._autonomy.effective_mode(account) if account else self._autonomy.mode
        environment = account.environment if account else Environment.DEMO
        plan = plan_modes.plan_mode(mode, environment)
        halted = self._autonomy.halted()
        checks = await self._entry_checks(account)
        blockers = [c.check_id for c in checks if not c.ok]
        green = not blockers
        rights = plan_modes.rights(plan)
        stages = await self._stages(account, checks, mode, plan, halted)
        nxt = _next_automatic(mode)
        authorize_blockers = list(blockers)
        if nxt is not None and rank(nxt) > rank(ceiling):
            authorize_blockers.append("ceiling")
        if halted:
            authorize_blockers.append("halted")
        return StartupStatus(
            evaluated_at=now, run=self._run, stages=self._overlay(stages), checks=checks, checks_green=green,
            blockers=blockers, mode=mode, plan_mode=plan, rights=rights, ladder=plan_modes.ladder(environment),
            ceiling=ceiling, halted=halted, halted_reason=self._autonomy.state.halted_reason,
            entries_authorized=self._entries_ok(rights.sends_orders, green, halted),
            entries_reason=self._entries_reason(mode, plan, rights.sends_orders, blockers, halted),
            real_account=environment is Environment.LIVE and account is not None,
            real_account_banner=REAL_ACCOUNT_BANNER if account and environment is Environment.LIVE else None,
            account=self._panel(account, ceiling) if account else None,
            can_start=not halted and (self._run is None or self._run.state is not StartupRunState.RUNNING),
            next_automatic_mode=nxt,
            can_authorize_automatic=nxt is not None and not authorize_blockers,
            authorize_blockers=authorize_blockers if nxt is not None else [],
        )  # fmt: skip

    @staticmethod
    def _entries_ok(sends_orders: bool, green: bool, halted: bool) -> bool:
        return sends_orders and green and not halted

    @staticmethod
    def _entries_reason(
        mode: AutonomyMode, plan: PlanMode, sends_orders: bool, blockers: list[str], halted: bool
    ) -> str:
        if halted:
            return "the system is halted: new entries are cut"
        if not sends_orders:
            return f"mode {plan.value}: analysis only, no order reaches the broker"
        if blockers:
            return f"{len(blockers)} condition(s) not met: {', '.join(blockers)}"
        return f"mode {plan.value}: every condition holds"

    def _overlay(self, stages: list[StartupStage]) -> list[StartupStage]:
        """While the sequence is on a stage, that stage reads STARTING unless it is already working."""
        run = self._run
        if run is None or run.state is not StartupRunState.RUNNING or run.current_stage is None:
            return stages
        return [
            s.model_copy(update={"state": StartupStageState.STARTING})
            if s.stage_id == run.current_stage and s.state not in {StartupStageState.READY, StartupStageState.RUNNING}
            else s
            for s in stages
        ]

    async def _stages(
        self, account: Account | None, checks: list[EntryCheck], mode: AutonomyMode, plan: PlanMode, halted: bool
    ) -> list[StartupStage]:
        by_id = {c.check_id: c for c in checks}
        out: list[StartupStage] = []

        def add(stage_id: str, state: StartupStageState, detail: str) -> None:
            out.append(
                StartupStage(
                    stage_id=stage_id,
                    order=len(out) + 1,
                    label=STAGE_LABELS[stage_id],
                    state=state,
                    detail=detail,
                    blocking=stage_id in BLOCKING_STAGES,
                )
            )

        def from_check(
            stage_id: str,
            check_id: str,
            *,
            red: StartupStageState,
            green: StartupStageState = StartupStageState.RUNNING,
        ) -> None:
            check = by_id.get(check_id)
            if check is None:
                add(stage_id, StartupStageState.STOPPED, "no account selected")
            else:
                add(stage_id, green if check.ok else red, check.detail)

        add(
            "application",
            StartupStageState.RUNNING,
            f"core {__version__} up for {int(self._heartbeat.uptime_seconds())}s",
        )
        python_core, supervisor = by_id.get("python_core"), by_id.get("supervisor")
        reds = [c for c in (python_core, supervisor) if c is not None and not c.ok]
        add(
            "services",
            StartupStageState.DEGRADED if reds else StartupStageState.RUNNING,
            reds[0].detail
            if reds
            else "the core is beating, its jobs are on time, the supervisor sees nothing serious",
        )
        from_check("database", "database", red=StartupStageState.FAILED)
        if account is None:
            add("terminal", StartupStageState.STOPPED, "no account selected")
            add("account", StartupStageState.FAILED, "no account is selected: register or select one in Settings")
        else:
            connected = self._accounts.session(account.id) is not None
            terminal = by_id["mt5_connected"]
            add(
                "terminal",
                StartupStageState.STOPPED
                if not connected
                else (StartupStageState.RUNNING if terminal.ok else StartupStageState.FAILED),
                "the account is not connected" if not connected else terminal.detail,
            )
            correct = by_id["correct_account"]
            if not connected:
                add("account", StartupStageState.STOPPED, f"{account.name}: not connected")
            elif not correct.ok:
                add("account", StartupStageState.FAILED, correct.detail)
            elif not account.trading_enabled:
                add("account", StartupStageState.DEGRADED, "trading is switched off for this account by the trader")
            else:
                add(
                    "account",
                    StartupStageState.READY,
                    f"{account.name} ({account.environment.value}) identified and authorised",
                )
        from_check("agent", "heartbeat", red=StartupStageState.FAILED)
        reconciliation = by_id.get("reconciliation")
        if reconciliation is None:
            add("reconciliation", StartupStageState.STOPPED, "no account selected")
        elif reconciliation.ok:
            add("reconciliation", StartupStageState.READY, reconciliation.detail)
        else:
            never = account is not None and self._reconciliation.last_success_at(account.id) is None
            add(
                "reconciliation",
                StartupStageState.STOPPED if never else StartupStageState.FAILED,
                reconciliation.detail,
            )
        from_check("market_data", "market_data_fresh", red=StartupStageState.DEGRADED)
        if halted:
            add("strategy", StartupStageState.HALTED, "the system is halted: no new setup is acted on")
        elif mode is AutonomyMode.OFF:
            add("strategy", StartupStageState.STOPPED, "OFF: the strategies do not evaluate")
        else:
            from_check("strategy", "strategy_valid", red=StartupStageState.DEGRADED)
        from_check("guardian", "guardian_running", red=StartupStageState.DEGRADED)
        risk = by_id.get("risk_engine")
        if risk is None:
            add("risk", StartupStageState.STOPPED, "no account selected")
        elif not risk.ok:
            add("risk", StartupStageState.FAILED, risk.detail)
        else:
            limits = by_id["risk_limits_loaded"]
            add(
                "risk",
                StartupStageState.RUNNING if limits.ok else StartupStageState.DEGRADED,
                limits.detail if not limits.ok else risk.detail,
            )
        if halted:
            add("autonomy", StartupStageState.HALTED, self._autonomy.state.halted_reason or "halted")
        elif mode is AutonomyMode.OFF:
            add(
                "autonomy",
                StartupStageState.STOPPED,
                f"OFF: the system starts stopped and never resumes by itself (ceiling {(await self._autonomy.ceiling()).value})",
            )
        else:
            add("autonomy", StartupStageState.RUNNING, f"{plan.value} ({mode.value})")
        rights = plan_modes.rights(plan)
        red_ids = [c.check_id for c in checks if not c.ok]
        if halted:
            add("trading", StartupStageState.HALTED, "halted: new entries are cut; closing stays available")
        elif mode is AutonomyMode.OFF:
            add("trading", StartupStageState.STOPPED, "no position can be taken: the system is OFF")
        elif not rights.sends_orders:
            add("trading", StartupStageState.READY, f"{plan.value}: analysis only, no order reaches the broker")
        elif red_ids:
            add("trading", StartupStageState.DEGRADED, f"held back by: {', '.join(red_ids)}")
        else:
            add("trading", StartupStageState.RUNNING, f"{plan.value}: every condition holds")
        return out

    # ------------------------------------------------------------------------------------------ the conditions of § 2.2
    async def _entry_checks(self, account: Account | None, *, fresh: bool = False) -> list[EntryCheck]:
        report: ReadinessReport = await self._autonomy.readiness(fresh=fresh)
        checks = [
            EntryCheck(check_id=c.check_id, label=c.label, ok=c.ok, detail=c.detail, source="readiness")
            for c in report.checks
        ]
        if account is None:
            checks.append(
                EntryCheck(
                    check_id="account",
                    label="Account identified",
                    ok=False,
                    detail="no account is selected",
                    source="startup",
                )
            )
            return checks
        now = self._clock.now()

        def add(check_id: str, label: str, ok: bool, detail: str) -> None:
            checks.append(EntryCheck(check_id=check_id, label=label, ok=ok, detail=detail, source="startup"))

        fresh_feed, feed_detail = self._market.feed_status(account.id, now)
        add("market_data_fresh", "Market data fresh", fresh_feed, feed_detail)

        guardian = self._guardian.report(account.id)
        guarding = guardian.ran and guardian.at is not None and now - guardian.at <= GUARDIAN_FRESH
        add(
            "guardian_running", "Account Guardian running", guarding,
            f"last cycle {int((now - guardian.at).total_seconds())}s ago" if guardian.at and guarding else "the Guardian has not completed a cycle recently",
        )  # fmt: skip

        try:
            doubtful = [
                c for c in await self._execution.in_doubt(account.id)
                if c.state in (CommandState.UNKNOWN, CommandState.RECONCILING)
            ]  # fmt: skip
        except TradingOsError:
            add(
                "no_unknown_commands",
                "No unresolved UNKNOWN command",
                False,
                "commands in doubt cannot be checked: database unavailable",
            )
        else:
            add(
                "no_unknown_commands", "No unresolved UNKNOWN command", not doubtful,
                f"{len(doubtful)} command(s) in doubt: reconcile, never resend" if doubtful else "no command is in doubt",
            )  # fmt: skip

        status = self._risk.status(account.id)
        reference = account.risk_profile.drawdown.reference_balance
        if status is None:
            add(
                "risk_limits_loaded",
                "Daily and weekly limits, initial capital loaded",
                False,
                "the Risk Engine has not evaluated this account yet",
            )
        elif reference is None:
            add(
                "risk_limits_loaded",
                "Daily and weekly limits, initial capital loaded",
                False,
                "the initial capital (reference balance) is not fixed",
            )
        else:
            add(
                "risk_limits_loaded", "Daily and weekly limits, initial capital loaded", True,
                f"daily {status.daily_loss_limit_percent:g}%, weekly {status.weekly_loss_limit_percent:g}%, capital {reference:g}",
            )  # fmt: skip

        blocks = list(self._supervisor.degraded_for(account.id))
        if self._autonomy.halted():
            blocks.append("the system is halted")
        if status is not None and status.lockout_reason:
            blocks.append(f"lockout: {status.lockout_reason}")
        add(
            "no_safety_block",
            "No lockout, halt or safety block",
            not blocks,
            "; ".join(blocks) if blocks else "nothing blocks entries",
        )

        ceiling = self._autonomy.ceiling_for(account)
        add(
            "mode_authorized", "Autonomy mode explicitly authorised", rank(ceiling) >= rank(AutonomyMode.CONFIRM),
            f"the ceiling of this account is {ceiling.value}"
            + ("" if rank(ceiling) >= rank(AutonomyMode.CONFIRM) else ": raise it in Settings to go beyond observation"),
        )  # fmt: skip
        return checks

    def _agent_ok(self, account: Account) -> bool:
        login = str(account.login)
        return self._execution.agent_status(login) is not None and self._execution.last_heartbeat(login) is not None

    # ------------------------------------------------------------------------------------------ helpers
    async def _selected_account(self) -> Account | None:
        """The account the trader selected: the active one — or the only one registered."""
        active = self._accounts.active_account_id
        if active is not None:
            return await self._accounts.effective(active)
        registered = await self._accounts.accounts()
        return await self._accounts.effective(registered[0].id) if len(registered) == 1 else None

    async def _selected_account_quietly(self) -> Account | None:
        try:
            return await self._selected_account()
        except TradingOsError:
            return None

    def _panel(self, account: Account, ceiling: AutonomyMode) -> AccountPanel:
        from trading_os.domain.execution.close_all import mask_login

        figures = self._positions.snapshot(account.id)
        status = self._execution.agent_status(str(account.login))
        return AccountPanel(
            account_id=account.id, name=account.name, provider=account.provider.value, server=account.server,
            account_type=account.account_type.value, environment=account.environment, currency=account.currency,
            login_masked=mask_login(account.login), connected=self._accounts.session(account.id) is not None,
            status=account.status.value, status_detail=account.status_detail,
            balance=figures.balance if figures else None, equity=figures.equity if figures else None,
            leverage=figures.leverage if figures else None,
            terminal_trade_allowed=figures.trade_allowed if figures else None, trading_enabled=account.trading_enabled,
            agent_connected=status is not None, agent_tradable=status.tradable if status else None, ceiling=ceiling,
        )  # fmt: skip


def _next_automatic(mode: AutonomyMode) -> AutonomyMode | None:
    if mode is AutonomyMode.CONFIRM:
        return AutonomyMode.ARMED
    if mode is AutonomyMode.ARMED:
        return AutonomyMode.AUTONOMOUS
    return None


__all__ = ["StartupService", "Timings"]
