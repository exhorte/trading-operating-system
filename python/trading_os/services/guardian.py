"""AccountGuardianService — the independent watch over what the core has open (ADR 0025).

It reads the account again each cycle (the Risk Engine's use of the loss limits, the positions, the pending orders) and answers three
questions with ``domain/guardian``: is a loss limit reached (then the core's positions are flattened), is a position of the core left
without a stop (then it is closed once the Position Manager has had its time), is anything open that is not the core's (then it is
only said). It acts through ``ExecutionService.submit`` like everything else — never around it — and only as far as the mode lets it.

Since ADR 0032 it also *watches* what plan §9 lists beyond the limits — the spread and the slippage of what the core holds, the health of the
terminal, the market feed, the agent, the broker and the reconciliation, the exposure by symbol, whether a new trade would be allowed — and
*asks for a reconciliation* when something only a comparison with the broker can settle shows up. None of that opens or widens anything.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta

from trading_os.domain.accounts.models import Account
from trading_os.domain.execution.commands import CommandKind, CommandState, ExecutionRequest
from trading_os.domain.execution.trace import is_trace
from trading_os.domain.guardian.report import GuardianAction, GuardianReport
from trading_os.domain.guardian.rules import GuardianInputs, GuardianPlan, LimitUse, judge
from trading_os.domain.guardian.watch import (
    GuardianWatch,
    HealthFinding,
    alerts,
    exposure_by_symbol,
    reconciliation_reason,
    slippage_reading,
    spread_readings,
    wide_spread_symbols,
)
from trading_os.domain.positions.models import PendingOrder, Position
from trading_os.domain.risk.state import RiskMode
from trading_os.infrastructure.database.repositories import Repositories
from trading_os.services.accounts import AccountService
from trading_os.services.attempts import MAX_ATTEMPTS, next_attempt
from trading_os.services.autonomy import AutonomyService
from trading_os.services.execution import ExecutionService
from trading_os.services.market_data import MarketDataService
from trading_os.services.position_manager import ACTING_MODES, SHOWING_MODES
from trading_os.services.positions import PositionService
from trading_os.services.reconciliation import ReconciliationService
from trading_os.services.risk import RiskService
from trading_os.shared.errors import TradingOsError
from trading_os.shared.time import Clock

logger = logging.getLogger(__name__)

SNAPSHOT_FRESH_FOR = timedelta(
    seconds=15
)  # the age the Risk Engine tolerates before it calls the account snapshot stale

_WAITING_TEXT = {
    "in_flight": "a command for this is already on its way",
    "waiting": "the last attempt ended; asking again after a pause",
    "gave_up": f"refused {MAX_ATTEMPTS} times: a human has to look",
}


class AccountGuardianService:
    def __init__(
        self,
        *,
        accounts: AccountService,
        positions: PositionService,
        risk: RiskService,
        execution: ExecutionService,
        autonomy: AutonomyService,
        repos: Repositories,
        clock: Clock,
        plan: GuardianPlan | None = None,
        market: MarketDataService | None = None,
        reconciliation: ReconciliationService | None = None,
    ) -> None:
        self._accounts = accounts
        self._positions = positions
        self._risk = risk
        self._execution = execution
        self._autonomy = autonomy
        self._repos = repos
        self._clock = clock
        self.plan = plan or GuardianPlan()
        self._market = market
        self._reconciliation = reconciliation
        self._agent_was_up: dict[str, bool] = {}
        self._reconciliation_asked: dict[str, tuple[datetime, str]] = {}
        self._reports: dict[str, GuardianReport] = {}
        self._without_stop_since: dict[tuple[str, str], datetime] = {}
        self._recovered: set[str] = set()

    # ------------------------------------------------------------------------------------------ reading
    def report(self, account_id: str) -> GuardianReport:
        return self._reports.get(account_id) or GuardianReport(account_id=account_id)

    # ------------------------------------------------------------------------------------------ the cycle
    async def run(self) -> int:
        """Guard every connected account; one failing never skips the others, the first failure is re-raised for the scheduler."""
        submitted = 0
        failure: Exception | None = None
        for account_id in list(self._accounts.connected_ids()):
            try:
                submitted += await self.guard(account_id)
            except Exception as error:
                logger.exception("guardian: account %s failed", account_id)
                failure = failure or error
        if failure is not None:
            raise failure
        return submitted

    async def guard(self, account_id: str) -> int:
        if not self._positions.baselined(account_id):
            return 0  # the broker's exposure has not been read: no judgement on a blank
        account = await self._accounts.effective(account_id)
        mode = self._autonomy.effective_mode(account)
        now = self._clock.now()
        if mode not in ACTING_MODES and mode not in SHOWING_MODES:
            self._reports[account_id] = GuardianReport(account_id=account_id, ran=True, at=now, mode=mode.value)
            return 0

        managed, external = await self._split(account_id, self._positions.positions(account_id))
        core_orders = [o for o in self._positions.orders(account_id) if is_trace(o.comment)]
        self._track_stops(account_id, managed, now)
        verdict = judge(
            GuardianInputs(
                limits=self._limits(account_id),
                managed=managed,
                external=external,
                unprotected_for_seconds={
                    p.position_id: (now - self._without_stop_since[(account_id, p.position_id)]).total_seconds()
                    for p in managed
                    if (account_id, p.position_id) in self._without_stop_since
                },
            ),
            self.plan,
        )
        watch = await self._watch(account, mode.value, managed, external, core_orders, now)
        if extra := alerts(
            spreads=watch.spreads, slippage=watch.slippage, slippage_threshold=account.execution_profile.limits.cost_threshold,
            unhealthy=watch.unhealthy, exposed=bool(managed or core_orders),
        ):  # fmt: skip
            verdict = verdict.model_copy(update={"alerts": [*verdict.alerts, *extra]})
        wide = wide_spread_symbols(watch.spreads) if self.plan.cancel_orders_on_wide_spread else set()
        wanted = self._wanted(managed, core_orders, bool(verdict.breached), verdict.close_without_stop, wide)
        actions: list[GuardianAction] = []
        submitted = 0
        for action in wanted:
            if mode in ACTING_MODES:
                action, sent = await self._act(account, action, now)
                submitted += sent
            actions.append(action)
        if mode in ACTING_MODES and any(a.status == "gave_up" for a in actions):
            # Plan §9: the Guardian can put the system in HALTED. It does so only as a last resort — a protective exit was refused
            # five times — because a halted system refuses every command (ADR 0025): it stops new risk and calls a human.
            gave_up = next(a for a in actions if a.status == "gave_up")
            await self._autonomy.halt(
                f"guardian: {gave_up.kind} of {gave_up.target_id} ({gave_up.reason}) was refused {MAX_ATTEMPTS} times",
                actor="guardian",
            )
        asked = await self._ask_for_reconciliation(account, now, gave_up=any(a.status == "gave_up" for a in actions))
        recovery = None if account_id in self._recovered else self._recovery(managed, external, account_id)
        self._recovered.add(account_id)
        previous = self._reports.get(account_id)
        last_asked = self._reconciliation_asked.get(account_id)
        self._reports[account_id] = GuardianReport(
            account_id=account_id, ran=True, at=now, mode=mode.value, verdict=verdict, actions=actions,
            recovery=recovery or (previous.recovery if previous else None), watch=watch,
            reconciliation_asked=asked or (previous.reconciliation_asked if previous else None),
            reconciliation_asked_at=last_asked[0] if last_asked else None,
        )  # fmt: skip
        return submitted

    # ------------------------------------------------------------------------------------------ inputs
    async def _split(self, account_id: str, found: list[Position]) -> tuple[list[Position], list[Position]]:
        managed: list[Position] = []
        external: list[Position] = []
        for position in found:
            opening = await self._repos.execution.for_position(account_id, position.position_id)
            (managed if opening is not None and opening.request.kind is CommandKind.OPEN else external).append(position)
        return managed, external

    def _track_stops(self, account_id: str, managed: list[Position], now: datetime) -> None:
        live = {(account_id, p.position_id) for p in managed if not p.has_stop}
        for key in [k for k in self._without_stop_since if k[0] == account_id and k not in live]:
            del self._without_stop_since[key]
        for key in live:
            self._without_stop_since.setdefault(key, now)

    def _limits(self, account_id: str) -> list[LimitUse]:
        status = self._risk.status(account_id)
        if status is None:
            return []
        return [
            LimitUse(
                name="daily loss", used_percent=status.daily_loss_used_percent,
                limit_percent=status.daily_loss_limit_percent,
            ),
            LimitUse(
                name="weekly loss", used_percent=status.weekly_loss_used_percent,
                limit_percent=status.weekly_loss_limit_percent,
            ),
            LimitUse(
                name="total loss", used_percent=status.max_drawdown_used_percent,
                limit_percent=status.max_drawdown_limit_percent,
            ),
        ]  # fmt: skip

    # ------------------------------------------------------------------------------------------ what to ask for
    def _wanted(
        self,
        managed: list[Position],
        core_orders: list[PendingOrder],
        breached: bool,
        without_stop: list[str],
        wide_spread: set[str],
    ) -> list[GuardianAction]:
        wanted: list[GuardianAction] = []
        for position in managed:
            if breached:
                reason = "a loss limit is reached"
            elif position.position_id in without_stop:
                reason = "no stop past the grace period"
            else:
                continue
            wanted.append(
                GuardianAction(
                    kind="close", target_id=position.position_id, symbol=position.symbol, reason=reason, status="shown"
                )
            )
        if breached:  # plan §6.5: pending orders are withdrawn whether or not a position is open
            wanted += [
                GuardianAction(
                    kind="cancel",
                    target_id=o.order_id,
                    symbol=o.symbol,
                    reason="a loss limit is reached",
                    status="shown",
                )
                for o in core_orders
            ]
        else:  # ADR 0032, only if the user switched it on: a resting order of the core where the spread is over HIS cap
            wanted += [
                GuardianAction(
                    kind="cancel", target_id=o.order_id, symbol=o.symbol, reason="spread over the cap", status="shown"
                )
                for o in core_orders
                if o.symbol in wide_spread
            ]
        return wanted

    async def _act(self, account: Account, action: GuardianAction, now: datetime) -> tuple[GuardianAction, int]:
        code = "limit" if "limit" in action.reason else "spread" if "spread" in action.reason else "nostop"
        command_id, status = await next_attempt(self._repos, f"gd-{action.kind}-{code}-{action.target_id}", now)
        if command_id is None:
            return action.model_copy(update={"status": status, "detail": _WAITING_TEXT[status]}), 0
        request = ExecutionRequest(
            command_id=command_id, account_id=account.id,
            kind=CommandKind.CLOSE if action.kind == "close" else CommandKind.CANCEL,
            symbol=action.symbol, strategy_id="guardian",
            position_id=action.target_id if action.kind == "close" else None,
            order_id=action.target_id if action.kind == "cancel" else None,
        )  # fmt: skip
        try:
            outcome = await self._execution.submit(request, automatic=True)
        except TradingOsError as error:
            logger.warning("guardian: %s could not be submitted: %s", command_id, error)
            return action.model_copy(update={"status": "skipped", "command_id": command_id, "detail": str(error)}), 0
        detail = (
            "; ".join(f"{r.code.value}: {r.detail}" for r in outcome.rejections)
            if outcome.rejections
            else outcome.command.state.value
        )
        return action.model_copy(update={"status": "submitted", "command_id": command_id, "detail": detail}), 1

    # ------------------------------------------------------------------------------------------ what it watches (ADR 0032)
    async def _watch(
        self,
        account: Account,
        mode: str,
        managed: list[Position],
        external: list[Position],
        core_orders: list[PendingOrder],
        now: datetime,
    ) -> GuardianWatch:
        account_id = account.id
        positions = [*managed, *external]
        status = self._risk.status(account_id)
        snapshot = self._positions.snapshot(account_id)
        exposed = {p.symbol for p in managed} | {o.symbol for o in core_orders}
        spreads: dict[str, float] = {}
        if self._market is not None:
            for symbol in exposed:
                tick = self._market.tick(account_id, symbol)
                if tick is not None:
                    spreads[symbol] = tick.spread
        slippage = []
        for position in managed:
            opening = await self._repos.execution.for_position(account_id, position.position_id)
            if opening is None:
                continue
            reading = slippage_reading(position, opening.request.price, opening.request.stop_loss)
            if reading is not None:
                slippage.append(reading)
        blocked: list[str] = []
        if status is not None:
            blocked = [f"{g.label}: {g.detail}" for g in status.gates if g.blocked]
            if status.allowance.status != "allowed":
                blocked.append(f"risk allowance: {status.allowance.detail}")
            if status.state is RiskMode.LOCKED and not blocked:
                blocked.append(f"locked: {status.lockout_reason or 'a limit is reached'}")
        return GuardianWatch(
            equity=snapshot.equity if snapshot else None,
            balance=snapshot.balance if snapshot else None,
            daily_loss_used_percent=status.daily_loss_used_percent if status else None,
            daily_loss_limit_percent=status.daily_loss_limit_percent if status else None,
            weekly_loss_used_percent=status.weekly_loss_used_percent if status else None,
            weekly_loss_limit_percent=status.weekly_loss_limit_percent if status else None,
            total_loss_used_percent=status.max_drawdown_used_percent if status else None,
            total_loss_limit_percent=status.max_drawdown_limit_percent if status else None,
            open_risk_percent=status.open_risk_percent if status else None,
            open_risk_limit_percent=status.open_risk_limit_percent if status else None,
            positions=len(positions),
            trades_today=status.trades_today if status else None,
            max_trades_per_day=status.max_trades_per_day if status else None,
            entries_allowed=None if status is None else not blocked,
            entries_blocked_by=blocked,
            exposure=exposure_by_symbol(positions, self._positions.orders(account_id)),
            spreads=spread_readings(spreads, account.execution_profile.limits.max_spread_by_symbol, exposed),
            slippage=slippage,
            health=self._health(account, mode, now),
        )

    def _health(self, account: Account, mode: str, now: datetime) -> list[HealthFinding]:
        """The state of everything the core stands on, as the Guardian reads it itself — never from a component's own verdict on itself."""
        account_id = account.id
        found: list[HealthFinding] = []
        failures, last_error = self._positions.failures(account_id)
        connected = self._positions.terminal_connected(account_id)
        if connected and failures == 0:
            found.append(HealthFinding(source="terminal", ok=True, detail="MT5 terminal read"))
        else:
            what = "not connected" if not connected else f"failed {failures} read(s) in a row"
            found.append(
                HealthFinding(
                    source="terminal",
                    ok=False,
                    detail=f"MT5 terminal {what}" + (f" ({last_error})" if last_error else ""),
                )
            )
        if self._market is not None:
            fresh, detail = self._market.feed_status(account_id, now)
            found.append(HealthFinding(source="market_data", ok=fresh, detail=detail))
        agent = self._execution.agent_status(str(account.login))
        if agent is None:
            found.append(
                HealthFinding(source="agent", ok=False, detail="no execution agent connected for this account")
            )
        elif not agent.healthy_for_orders:
            found.append(
                HealthFinding(
                    source="agent",
                    ok=False,
                    detail=f"{agent.agent_id}: identity {agent.identity}, tradable {agent.tradable}, halted {agent.halted}, "
                    f"permissions {'ok' if agent.permissions_ok else 'refused'}",
                )
            )
        else:
            found.append(
                HealthFinding(source="agent", ok=True, detail=f"{agent.agent_id} {agent.agent_version} ready".strip())
            )
        snapshot = self._positions.snapshot(account_id)
        if snapshot is None:
            found.append(HealthFinding(source="broker", ok=False, detail="no account snapshot yet"))
        elif now - snapshot.observed_at > SNAPSHOT_FRESH_FOR:
            age = int((now - snapshot.observed_at).total_seconds())
            found.append(HealthFinding(source="broker", ok=False, detail=f"account snapshot is {age}s old"))
        elif snapshot.trade_allowed is False:
            found.append(
                HealthFinding(
                    source="broker", ok=False, detail="the terminal says trading is not allowed on this account"
                )
            )
        else:
            found.append(HealthFinding(source="broker", ok=True, detail="account read, trading allowed"))
        if self._reconciliation is not None:
            last = self._reconciliation.last_readable_report(account_id)
            unreadable = self._reconciliation.consecutive_failures(account_id)
            if unreadable:
                detail = f"{unreadable} run(s) in a row could not read the broker"
                found.append(HealthFinding(source="reconciliation", ok=False, detail=detail))
            elif last is not None and last.critical:
                detail = f"{len(last.critical)} critical divergence(s): {last.critical[0].detail}"
                found.append(HealthFinding(source="reconciliation", ok=False, detail=detail))
            else:
                found.append(
                    HealthFinding(
                        source="reconciliation", ok=True, detail="no divergence" if last is not None else "no run yet"
                    )
                )
        found.append(HealthFinding(source="system", ok=True, detail=f"autonomy mode {mode}"))
        return found

    async def _ask_for_reconciliation(self, account: Account, now: datetime, *, gave_up: bool) -> str | None:
        """Plan §9, « demander une réconciliation »: when only a comparison with the broker can settle what was seen — a command in doubt,
        unreadable runs, an agent that came back, a protective exit refused for good. At most once per ``reconcile_min_interval_seconds``;
        read-only towards the broker (the service never places, modifies or closes anything)."""
        if self._reconciliation is None:
            return None
        account_id = account.id
        up = self._execution.agent_status(str(account.login)) is not None
        came_back = up and self._agent_was_up.get(account_id) is False
        self._agent_was_up[account_id] = up
        try:
            in_doubt = await self._repos.execution.in_states([CommandState.UNKNOWN, CommandState.RECONCILING])
            doubtful = [c for c in in_doubt if c.account_id == account_id]
        except TradingOsError:
            doubtful = []
        reason = reconciliation_reason(
            doubtful_commands=len(doubtful),
            unreadable_runs=self._reconciliation.consecutive_failures(account_id),
            agent_came_back=came_back,
        )
        if gave_up:
            reason = "; ".join(filter(None, [reason, "a protective exit was refused for good"]))
        if reason is None:
            return None
        previous = self._reconciliation_asked.get(account_id)
        if previous is not None and now - previous[0] < timedelta(seconds=self.plan.reconcile_min_interval_seconds):
            return None
        self._reconciliation_asked[account_id] = (now, reason)
        try:
            await self._reconciliation.reconcile(account_id)
        except TradingOsError as error:
            logger.warning("guardian: the reconciliation it asked for could not run: %s", error)
            return f"{reason} (it could not run: {error})"
        return reason

    def _recovery(self, managed: list[Position], external: list[Position], account_id: str) -> str:
        naked = [p for p in managed if not p.has_stop]
        orders = [o for o in self._positions.orders(account_id) if is_trace(o.comment)]
        return (
            f"core started: {len(managed)} position(s) of the core found ({len(naked)} without a stop), "
            f"{len(orders)} resting order(s) of the core, {len(external)} position(s) not opened by the core"
        )


__all__ = ["AccountGuardianService"]
