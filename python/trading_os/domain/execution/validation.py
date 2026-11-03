"""Validation of an execution request, before and independently of the agent's own local barriers.

Order of concerns: who (account integrity), whether (trading enabled, agent reachable and able), what (shape of the
request) and under whose authority (the Risk Engine's approved decision, which the command must not exceed).
Returns *every* violation, not just the first, so the audit trail explains a refusal completely.
"""

from __future__ import annotations

from datetime import datetime

from trading_os.domain.execution.commands import CommandKind, ExecutionRequest
from trading_os.domain.execution.reasons import RejectCode, Rejection
from trading_os.domain.positions.models import PendingOrder, Position
from trading_os.domain.primitives import DomainModel, Side
from trading_os.domain.risk.decision import RiskDecision
from trading_os.domain.strategy.intent import OrderKind

# Capability strings the agent announces in its hello. A market OPEN is the original command and needs none; the others exist
# only when the agent has a handler for them (agent 1.11 has none: they are refused rather than sent into the void, ADR 0023).
CAPABILITY_BY_KIND = {
    CommandKind.MODIFY: "modify",
    CommandKind.CLOSE: "close",
    CommandKind.PARTIAL_CLOSE: "close",
    CommandKind.CANCEL: "cancel",
}
LIMIT_CAPABILITY = "limit"  # a pending (limit) order is a different broker request from a market order
VOLUME_EPSILON = 1e-9


class ValidationContext(DomainModel):
    now: datetime
    automatic: bool = False  # issued by the strategy pipeline, not by a human gesture
    account_exists: bool = True
    connected_account_id: str | None = None  # the account really attached to the terminal
    active_account_id: str | None = None
    account_trading_enabled: bool = True
    agent_registered: bool = False
    agent_capabilities: frozenset[str] = frozenset()
    halted: bool = False
    decision: RiskDecision | None = None  # the decision named by ``risk_decision_id``, as stored
    # What the core sees at the broker (ADR 0023). ``positions_known`` is False until a first snapshot exists: a target the core
    # cannot see is then "unverified", not "absent" — closing and cancelling go through, anything that needs the numbers does not.
    positions_known: bool = False
    position: Position | None = None  # the open position a MODIFY / CLOSE / PARTIAL_CLOSE names
    pending_order: PendingOrder | None = None  # the pending order a CANCEL names


def _reject(code: RejectCode, detail: str) -> Rejection:
    return Rejection(code=code, detail=detail)


def _stop_is_looser(side: Side, stop: float, approved_stop: float) -> bool:
    """A stop that allows more loss than the approved one (below it for a buy, above it for a sell)."""
    return stop < approved_stop if side is Side.BUY else stop > approved_stop


def validate(request: ExecutionRequest, ctx: ValidationContext) -> list[Rejection]:
    problems: list[Rejection] = []

    # --- who: the account must be the one really attached (ADR 0010: ACCOUNT_MISMATCH is a hard reject)
    if not ctx.account_exists:
        problems.append(_reject(RejectCode.ACCOUNT_NOT_CONNECTED, f"unknown account {request.account_id!r}"))
    elif ctx.connected_account_id is None:
        problems.append(_reject(RejectCode.ACCOUNT_NOT_CONNECTED, f"{request.account_id} is not connected"))
    elif request.account_id != ctx.connected_account_id:
        problems.append(
            _reject(
                RejectCode.ACCOUNT_MISMATCH,
                f"command for {request.account_id}, terminal is on {ctx.connected_account_id}",
            )
        )
    if ctx.automatic and ctx.active_account_id is not None and request.account_id != ctx.active_account_id:
        problems.append(_reject(RejectCode.NOT_ACTIVE_ACCOUNT, "only the active account receives automatic commands"))

    # --- whether
    human_exit = request.kind.reduces_risk_only and not ctx.automatic
    if not ctx.account_trading_enabled and not human_exit:  # ADR 0034: « Disable Trading » stops risk, not the way out
        problems.append(_reject(RejectCode.TRADING_DISABLED, "trading is disabled for this account"))
    if ctx.halted:
        # ADR 0033: a halt stops new risk, not the way out. A closing or a cancelling issued by a human gesture goes through; an opening,
        # a stop move and anything automatic (the Guardian, the Position Manager, a strategy) do not.
        if not request.kind.reduces_risk_only:
            problems.append(_reject(RejectCode.HALTED, "the system is halted"))
        elif ctx.automatic:
            problems.append(
                _reject(RejectCode.HALTED, "the system is halted: only a human gesture may close or cancel while it is")
            )
    if not ctx.agent_registered:
        problems.append(_reject(RejectCode.AGENT_UNREACHABLE, "no execution agent is registered for this account"))
    else:
        needed = CAPABILITY_BY_KIND.get(request.kind)
        if request.kind is CommandKind.OPEN and request.order_type is OrderKind.LIMIT:
            needed = LIMIT_CAPABILITY
        if needed is not None and needed not in ctx.agent_capabilities:
            problems.append(
                _reject(
                    RejectCode.AGENT_CAPABILITY_MISSING, f"the agent cannot handle {request.kind} (needs «{needed}»)"
                )
            )
    if request.expires_at is not None and request.expires_at <= ctx.now:
        problems.append(_reject(RejectCode.COMMAND_EXPIRED, "the command is already past its expiry"))

    # --- what
    if request.kind is CommandKind.OPEN:
        problems += _validate_open(request)
    else:
        problems += _validate_management(request, ctx)

    # --- under whose authority
    if request.kind is CommandKind.OPEN:
        problems += _validate_authority(request, ctx)
    return problems


def _validate_open(request: ExecutionRequest) -> list[Rejection]:
    problems: list[Rejection] = []
    if request.side is None:
        problems.append(_reject(RejectCode.INVALID_REQUEST, "OPEN needs a side"))
    if request.volume is None:
        problems.append(_reject(RejectCode.INVALID_REQUEST, "OPEN needs a volume"))
    if request.stop_loss is None or request.stop_loss <= 0:
        problems.append(_reject(RejectCode.STOP_REQUIRED, "a stop loss is mandatory: no trade without a stop"))
    if request.order_type is OrderKind.LIMIT:
        problems += _validate_limit(request)
    elif request.order_type is not OrderKind.MARKET:
        problems.append(
            _reject(RejectCode.ORDER_TYPE_UNSUPPORTED, "the agent protocol carries market and limit orders only")
        )
    return problems


def _validate_limit(request: ExecutionRequest) -> list[Rejection]:
    """A limit order rests at the broker until it fills or expires: its price must exist and its stop and target must sit on the
    right side of it, or the broker would refuse it (or worse, fill a stop that is already behind the entry)."""
    price = request.price
    if price is None or price <= 0:
        return [_reject(RejectCode.INVALID_REQUEST, "a LIMIT order needs a price")]
    problems: list[Rejection] = []
    if request.side is not None and request.stop_loss is not None and request.stop_loss > 0:
        wrong_stop = request.stop_loss >= price if request.side is Side.BUY else request.stop_loss <= price
        if wrong_stop:
            where = "below" if request.side is Side.BUY else "above"
            problems.append(_reject(RejectCode.INVALID_REQUEST, f"the stop must be {where} the limit price {price:g}"))
    if request.side is not None and request.take_profit is not None and request.take_profit > 0:
        wrong_target = request.take_profit <= price if request.side is Side.BUY else request.take_profit >= price
        if wrong_target:
            where = "above" if request.side is Side.BUY else "below"
            problems.append(
                _reject(RejectCode.INVALID_REQUEST, f"the target must be {where} the limit price {price:g}")
            )
    return problems


def _validate_management(request: ExecutionRequest, ctx: ValidationContext) -> list[Rejection]:
    """MODIFY / CLOSE / PARTIAL_CLOSE / CANCEL (ADR 0023): none of them may add exposure, and a stop only ever tightens."""
    kind = request.kind
    if kind is CommandKind.CANCEL:
        if not request.order_id:
            return [_reject(RejectCode.INVALID_REQUEST, "CANCEL needs an order_id")]
        if ctx.positions_known and ctx.pending_order is None:
            return [_reject(RejectCode.ORDER_NOT_FOUND, f"no pending order {request.order_id} at the broker")]
        return []
    if not request.position_id:
        return [_reject(RejectCode.INVALID_REQUEST, f"{kind} needs a position_id")]
    if kind is CommandKind.PARTIAL_CLOSE and not request.volume:
        return [_reject(RejectCode.INVALID_REQUEST, "PARTIAL_CLOSE needs a volume")]
    position = ctx.position
    if position is None:
        if ctx.positions_known:
            return [_reject(RejectCode.POSITION_NOT_FOUND, f"no open position {request.position_id}")]
        if kind in {CommandKind.MODIFY, CommandKind.PARTIAL_CLOSE}:
            return [
                _reject(
                    RejectCode.POSITION_NOT_FOUND,
                    f"{kind} needs the position's numbers and the core has no view of the broker yet",
                )
            ]
    problems: list[Rejection] = []
    if position is not None and position.symbol != request.symbol:
        problems.append(_reject(RejectCode.SYMBOL_MISMATCH, f"position {position.position_id} is on {position.symbol}"))
    partial_too_big = (
        kind is CommandKind.PARTIAL_CLOSE
        and position is not None
        and request.volume is not None
        and request.volume >= position.volume - VOLUME_EPSILON
    )
    if partial_too_big and position is not None and request.volume is not None:
        problems.append(
            _reject(
                RejectCode.VOLUME_INVALID,
                f"{request.volume:g} lot(s) is not less than the {position.volume:g} open: that is a CLOSE",
            )
        )
    if kind is CommandKind.MODIFY:
        problems += _validate_modify(request, position)
    return problems


def _validate_modify(request: ExecutionRequest, position: Position | None) -> list[Rejection]:
    if request.stop_loss is None and request.take_profit is None:
        return [_reject(RejectCode.INVALID_REQUEST, "MODIFY needs a new stop and/or target")]
    problems: list[Rejection] = []
    stop = request.stop_loss
    if stop is not None and stop <= 0:
        problems.append(_reject(RejectCode.STOP_REQUIRED, "a stop cannot be removed: no position without a stop"))
    if position is None or stop is None or stop <= 0:
        return problems
    if position.has_stop and _stop_is_looser(position.side, stop, position.stop_loss):
        problems.append(
            _reject(
                RejectCode.STOP_LOOSENED,
                f"stop {stop:g} lets the position lose more than its current stop {position.stop_loss:g}",
            )
        )
    price = position.current_price
    if price is not None and (stop >= price if position.side is Side.BUY else stop <= price):
        problems.append(_reject(RejectCode.INVALID_REQUEST, f"stop {stop:g} is not behind the price {price:g}"))
    return problems


def _validate_authority(request: ExecutionRequest, ctx: ValidationContext) -> list[Rejection]:
    """No order without the Risk Engine, and none that exceeds what it approved (ADR 0007)."""
    decision = ctx.decision
    if request.risk_decision_id is None or decision is None:
        return [_reject(RejectCode.RISK_NOT_APPROVED, "an OPEN command needs an approved risk decision")]
    problems: list[Rejection] = []
    if decision.decision_id != request.risk_decision_id or decision.account_id != request.account_id:
        problems.append(
            _reject(RejectCode.RISK_DECISION_MISMATCH, "the decision belongs to another account or command")
        )
    if not decision.approved:
        problems.append(
            _reject(RejectCode.RISK_NOT_APPROVED, f"the risk decision was refused: {', '.join(decision.reasons)}")
        )
        return problems
    if decision.expires_at <= ctx.now:
        problems.append(
            _reject(RejectCode.RISK_DECISION_EXPIRED, "the approval is stale: the market has moved, review again")
        )
    if decision.symbol is not None and decision.symbol != request.symbol:
        problems.append(
            _reject(RejectCode.SYMBOL_MISMATCH, f"approved on {decision.symbol}, command on {request.symbol}")
        )
    if decision.side is not None and request.side is not None and decision.side is not request.side:
        problems.append(_reject(RejectCode.RISK_DECISION_MISMATCH, "the command reverses the approved side"))
    if (
        decision.approved_volume is not None
        and request.volume is not None
        and request.volume > decision.approved_volume + 1e-9
    ):
        problems.append(
            _reject(
                RejectCode.RISK_DECISION_MISMATCH,
                f"volume {request.volume:g} exceeds the approved {decision.approved_volume:g}",
            )
        )
    if (
        decision.stop_loss is not None
        and request.stop_loss is not None
        and request.side is not None
        and _stop_is_looser(request.side, request.stop_loss, decision.stop_loss)
    ):
        problems.append(_reject(RejectCode.RISK_DECISION_MISMATCH, "the stop is looser than the approved one"))
    return problems
