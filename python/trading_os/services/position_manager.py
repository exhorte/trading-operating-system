"""PositionManagerService — applies the ``ExitPlan`` to the positions the core opened (ADR 0023).

* **It manages only what it opened.** A position counts when an OPEN command of the core names it (``for_position``); one opened by hand
  in MT5, or by anything else, is left alone. A resting limit order counts when it carries one of our traces.
* **It acts only as far as the mode lets it.** OFF and HALTED: nothing. OBSERVE and PAPER: the plan is computed and *shown* (what the
  manager would ask for), no command is created — nothing rests at a broker in those modes. CONFIRM, ARMED, AUTONOMOUS: each action is
  an ordinary ``ExecutionRequest`` through ``ExecutionService.submit`` — the same validation, the same mode routing, the same trace.
* **It does not repeat itself.** A command already in flight is waited for; a command that ended without effect is asked again only
  after ``RETRY_AFTER``, under a new ordinal (``pm-<action>-<position>-<n>``), and only ``MAX_ATTEMPTS`` times — a refusal that keeps
  coming back is a fact for the cockpit, not a loop. The decision itself reads the broker's state (stop, volume), not a memory.
* **It fails closed on what it cannot see.** No quote or no symbol specification for a managed position: nothing is asked for it, and
  the failure is kept for the readiness check instead of hidden.
"""

from __future__ import annotations

import logging
from collections.abc import Mapping, Sequence
from datetime import datetime, timedelta

from trading_os.domain.accounts.models import Account
from trading_os.domain.autonomy.readiness import Fact
from trading_os.domain.autonomy.state import AutonomyMode
from trading_os.domain.execution.commands import CommandKind, ExecutionRequest
from trading_os.domain.execution.trace import is_trace
from trading_os.domain.market.sessions import TradingWindow, in_trading_window, minutes_until_window_end
from trading_os.domain.positions.manager import (
    ExitPlan,
    ManagedPosition,
    ManagementAction,
    Quote,
    SymbolConstraints,
    WindowState,
    plan_pending_order,
    plan_position,
)
from trading_os.domain.positions.models import PendingOrder, Position
from trading_os.domain.primitives import DomainModel
from trading_os.domain.risk.sizing import commission_in_price
from trading_os.infrastructure.database.repositories import Repositories
from trading_os.services.accounts import AccountService
from trading_os.services.attempts import MAX_ATTEMPTS, next_attempt
from trading_os.services.autonomy import AutonomyService
from trading_os.services.execution import ExecutionService
from trading_os.services.market_data import MarketDataService
from trading_os.services.positions import PositionService
from trading_os.shared.errors import TradingOsError, Unavailable
from trading_os.shared.time import Clock

logger = logging.getLogger(__name__)

ACTING_MODES = frozenset({AutonomyMode.CONFIRM, AutonomyMode.ARMED, AutonomyMode.AUTONOMOUS})
SHOWING_MODES = frozenset({AutonomyMode.OBSERVE, AutonomyMode.PAPER})
STALE_AFTER = timedelta(minutes=2)  # the manager did not run for this long while it should have


class PlannedAction(DomainModel):
    """One thing the manager wants, and what became of it."""

    account_id: str
    action: ManagementAction
    status: str  # shown | submitted | in_flight | waiting | gave_up | skipped
    command_id: str | None = None
    detail: str = ""
    at: datetime


class PositionManagerService:
    def __init__(
        self,
        *,
        accounts: AccountService,
        positions: PositionService,
        market: MarketDataService,
        execution: ExecutionService,
        autonomy: AutonomyService,
        repos: Repositories,
        clock: Clock,
        plan: ExitPlan | None = None,
        strategy_windows: Mapping[str, Sequence[TradingWindow]] | None = None,
    ) -> None:
        self._accounts = accounts
        self._positions = positions
        self._market = market
        self._execution = execution
        self._autonomy = autonomy
        self._repos = repos
        self._clock = clock
        self.plan = plan or ExitPlan()
        # strategy id → its own trading windows (ADR 0030): a position closes at the end of the window of the strategy that opened it
        # (or of the account's envelope, whichever comes first), not of a window that belongs to another strategy.
        self._strategy_windows = dict(strategy_windows or {})
        self._last: dict[str, list[PlannedAction]] = {}
        self._last_run_at: dict[str, datetime] = {}
        self._failure: dict[str, str] = {}

    # ------------------------------------------------------------------------------------------ reading
    def last_plan(self, account_id: str) -> list[PlannedAction]:
        return list(self._last.get(account_id, []))

    def readiness(self, account: Account) -> Fact:
        """The ``position_management`` fact: the plan is valid, the manager has run lately, and nothing it needs is missing.
        Says nothing about profitability — an exit plan cannot."""
        failure = self._failure.get(account.id)
        if failure is not None:
            return Fact(ok=False, detail=f"the Position Manager cannot act on a position: {failure}")
        ran = self._last_run_at.get(account.id)
        if ran is None:
            return Fact(ok=False, detail="the Position Manager has not run for this account yet")
        age = self._clock.now() - ran
        if age > STALE_AFTER:
            return Fact(ok=False, detail=f"the Position Manager has been silent for {int(age.total_seconds())}s")
        gave_up = [p for p in self._last.get(account.id, []) if p.status == "gave_up"]
        if gave_up:
            first = gave_up[0]
            return Fact(
                ok=False, detail=f"{first.action.code} on {first.action.symbol} was refused {MAX_ATTEMPTS} times"
            )
        plan = self.plan
        return Fact(
            ok=True,
            detail=(
                f"break-even {'at +' + format(plan.breakeven_at_r, 'g') + ' R' if plan.breakeven_at_r else 'off'}, "
                f"flat {plan.flat_minutes_before_window_end} min before the window closes; ran {int(age.total_seconds())}s ago"
            ),
        )

    # ------------------------------------------------------------------------------------------ the cycle
    async def run(self) -> int:
        """Manage every connected account. One failing never skips the others; the first failure is re-raised for the scheduler."""
        done = 0
        failure: Exception | None = None
        for account_id in list(self._accounts.connected_ids()):
            try:
                done += await self.manage(account_id)
            except Exception as error:  # a bug must not stop the other accounts, nor go unseen
                logger.exception("position manager: account %s failed", account_id)
                self._failure[account_id] = type(error).__name__
                failure = failure or error
        if failure is not None:
            raise failure
        return done

    async def manage(self, account_id: str) -> int:
        """One pass over one account; returns how many commands were submitted."""
        if not self._positions.baselined(account_id):
            return 0  # the broker's exposure has not been read yet: nothing to judge
        account = await self._accounts.effective(account_id)
        mode = self._autonomy.effective_mode(account)
        now = self._clock.now()
        if mode not in ACTING_MODES and mode not in SHOWING_MODES:
            self._last[account_id] = []
            self._last_run_at[account_id] = now
            self._failure.pop(account_id, None)
            return 0
        window = self._window(account, now)
        planned: list[PlannedAction] = []
        problem: str | None = None
        for position in self._positions.positions(account_id):
            try:
                entries = await self._position_actions(account, position, now)
            except _CannotManage as error:
                problem = f"{position.symbol} {position.position_id}: {error}"
                continue
            planned += entries
        for order in self._positions.orders(account_id):
            if is_trace(order.comment):
                tick = self._market.tick(account_id, order.symbol)
                quote = Quote(bid=tick.bid, ask=tick.ask) if tick is not None else None
                action = plan_pending_order(order, self.plan, window, self._age_minutes(order, now), quote)
                if action is not None:
                    planned.append(PlannedAction(account_id=account_id, action=action, status="shown", at=now))
        submitted = 0
        final: list[PlannedAction] = []
        for entry in planned:
            if mode in ACTING_MODES:
                entry, sent = await self._act(account, entry, now)
                submitted += sent
            final.append(entry)
        self._last[account_id] = final
        self._last_run_at[account_id] = now
        if problem is None:
            self._failure.pop(account_id, None)
        else:
            self._failure[account_id] = problem
        return submitted

    # ------------------------------------------------------------------------------------------ one position
    async def _position_actions(self, account: Account, position: Position, now: datetime) -> list[PlannedAction]:
        opening = await self._repos.execution.for_position(account.id, position.position_id)
        if opening is None or opening.request.kind is not CommandKind.OPEN:
            return []  # not ours: a position opened by hand, or by another tool, is never touched
        window = self._window(account, now, opening.request.strategy_id)  # the opening strategy's hours, not another's
        stop = opening.request.stop_loss
        volume = opening.filled_volume or opening.request.volume
        if stop is None or stop <= 0 or volume is None or volume <= 0:
            raise _CannotManage("its opening command carries no stop or volume to measure from")
        tick = self._market.tick(account.id, position.symbol)
        if tick is None:
            raise _CannotManage("no live quote")
        spec = self._market.spec(account.id, position.symbol)
        if spec is None:
            raise _CannotManage("no symbol specification")
        limits = account.execution_profile.limits
        buffer = tick.spread + commission_in_price(limits.commission_per_lot_round_trip, spec)
        actions = plan_position(
            ManagedPosition(position=position, initial_stop=stop, initial_volume=volume, command_id=opening.command_id),
            Quote(bid=tick.bid, ask=tick.ask),
            self.plan,
            window,
            SymbolConstraints(volume_step=spec.volume_step, volume_min=spec.volume_min, price_decimals=spec.digits),
            buffer,
        )
        return [PlannedAction(account_id=account.id, action=a, status="shown", at=now) for a in actions]

    def _window(self, account: Account, now: datetime, strategy_id: str | None = None) -> WindowState:
        """Where ``now`` stands in the trading day. The account's windows are the envelope; the opening strategy's own windows, when
        it has some, narrow it: in a window means in both, and the end that counts is the nearer of the two. All in New York time."""
        sets = [account.trading_rules.trading_windows]
        own = self._strategy_windows.get(strategy_id) if strategy_id else None
        if own is not None:
            sets.append(tuple(own))
        in_window = all(in_trading_window(now, windows) for windows in sets)
        ends = [minutes_until_window_end(now, windows) for windows in sets]
        nearest = min((m for m in ends if m is not None), default=None)
        return WindowState(in_window=in_window, minutes_to_end=nearest if in_window else None)

    @staticmethod
    def _age_minutes(order: PendingOrder, now: datetime) -> float | None:
        return None if order.placed_at is None else (now - order.placed_at).total_seconds() / 60

    # ------------------------------------------------------------------------------------------ asking
    async def _act(self, account: Account, entry: PlannedAction, now: datetime) -> tuple[PlannedAction, int]:
        action = entry.action
        subject = action.position_id or action.order_id or "?"
        command_id, status = await next_attempt(self._repos, f"pm-{action.code}-{subject}", now)
        if command_id is None:
            return entry.model_copy(update={"status": status, "detail": _STATUS_TEXT[status]}), 0
        opening = (
            await self._repos.execution.for_position(account.id, action.position_id) if action.position_id else None
        )
        request = ExecutionRequest(
            command_id=command_id,
            account_id=account.id,
            kind=action.kind,
            symbol=action.symbol,
            volume=action.volume,
            stop_loss=action.stop_loss,
            strategy_id=opening.request.strategy_id if opening else "manager",
            strategy_version=opening.request.strategy_version if opening else "0",
            position_id=action.position_id,
            order_id=action.order_id,
        )
        try:
            outcome = await self._execution.submit(request, automatic=True)
        except (TradingOsError, Unavailable) as error:
            logger.warning("position manager: %s could not be submitted: %s", command_id, error)
            return entry.model_copy(update={"status": "skipped", "command_id": command_id, "detail": str(error)}), 0
        detail = (
            "; ".join(f"{r.code.value}: {r.detail}" for r in outcome.rejections)
            if outcome.rejections
            else outcome.command.state.value
        )
        return entry.model_copy(update={"status": "submitted", "command_id": command_id, "detail": detail}), 1


_STATUS_TEXT = {
    "in_flight": "a command for this is already on its way",
    "waiting": "the last attempt ended; asking again after a pause",
    "gave_up": f"refused {MAX_ATTEMPTS} times: a human has to look",
}


class _CannotManage(Exception):
    """A managed position the manager cannot judge (no quote, no specification, no opening numbers)."""


__all__ = ["ACTING_MODES", "PlannedAction", "PositionManagerService"]
