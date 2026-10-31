"""Validation of an execution request, before and independently of the agent's own local barriers.

Order of concerns: who (account integrity), whether (trading enabled, agent reachable and able), what (shape of the
request) and under whose authority (the Risk Engine's approved decision, which the command must not exceed).
Returns *every* violation, not just the first, so the audit trail explains a refusal completely.
"""

from __future__ import annotations

from datetime import datetime

from trading_os.domain.execution.commands import CommandKind, ExecutionRequest
from trading_os.domain.execution.reasons import RejectCode, Rejection
from trading_os.domain.primitives import DomainModel, Side
from trading_os.domain.risk.decision import RiskDecision
from trading_os.domain.strategy.intent import OrderKind

# Capability strings the agent announces in its hello. OPEN is the original command and needs none; the others exist
# only when the agent has a handler for them (today it has none: they are refused rather than sent into the void).
CAPABILITY_BY_KIND = {
    CommandKind.MODIFY: "modify",
    CommandKind.CLOSE: "close",
    CommandKind.PARTIAL_CLOSE: "close",
    CommandKind.CANCEL: "cancel",
}


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
    if not ctx.account_trading_enabled:
        problems.append(_reject(RejectCode.TRADING_DISABLED, "trading is disabled for this account"))
    if ctx.halted:
        problems.append(_reject(RejectCode.HALTED, "the system is halted"))
    if not ctx.agent_registered:
        problems.append(_reject(RejectCode.AGENT_UNREACHABLE, "no execution agent is registered for this account"))
    else:
        needed = CAPABILITY_BY_KIND.get(request.kind)
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
    elif request.kind in {CommandKind.MODIFY, CommandKind.CLOSE, CommandKind.PARTIAL_CLOSE} and not request.position_id:
        problems.append(_reject(RejectCode.INVALID_REQUEST, f"{request.kind} needs a position_id"))
    elif request.kind is CommandKind.CANCEL and not request.order_id:
        problems.append(_reject(RejectCode.INVALID_REQUEST, "CANCEL needs an order_id"))
    if request.kind is CommandKind.PARTIAL_CLOSE and not request.volume:
        problems.append(_reject(RejectCode.INVALID_REQUEST, "PARTIAL_CLOSE needs a volume"))

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
    if request.order_type is not OrderKind.MARKET:
        problems.append(_reject(RejectCode.ORDER_TYPE_UNSUPPORTED, "the agent protocol only carries market orders"))
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
