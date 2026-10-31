"""The single control point before execution (ADR 0007): « CAN_I_TRADE? » and the ``RiskDecision`` on an intent.

``can_i_trade`` answers with explainable checks — each failed one contributes a stable reason code:

    {"decision": "DENIED", "reasons": ["daily_risk_budget_exceeded", "news_restriction", ...]}

``decide`` adds what only an intent can fail: wrong-side or too-close stop, cost ratio, sizing from the broker's
specification, and the open/correlated risk *after* the new position. A decision is valid for a short time
(``expires_at``): the market moves, and the execution engine refuses a stale approval.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Literal

from pydantic import Field

from trading_os.domain.market.models import SymbolSpec
from trading_os.domain.positions.models import Position
from trading_os.domain.primitives import AccountId, DomainModel, Side, SymbolCode
from trading_os.domain.risk.evaluate import RiskInputs, evaluate_risk_state
from trading_os.domain.risk.exposure import currency_exposure, max_correlated_exposure, position_risk_amount
from trading_os.domain.risk.gates import symbol_gate
from trading_os.domain.risk.lockout import KILL_SWITCH_REASON, ActiveLockout, is_lockout_expired
from trading_os.domain.risk.sizing import SizingResult, commission_in_price, cost_ratio, size_position
from trading_os.domain.risk.state import GateResult, RiskState
from trading_os.domain.strategy.intent import TradeIntent
from trading_os.shared.errors import SizingError
from trading_os.shared.ids import new_id

DEFAULT_DECISION_TTL = timedelta(seconds=60)


class HealthFlags(DomainModel):
    """The non-numeric facts about the account's plumbing, gathered by the services."""

    account_healthy: bool = True  # fresh account snapshot, trading allowed on the account, margin sane
    broker_connected: bool = True  # the terminal's connection to the trade server
    mt5_healthy: bool = True  # reader process alive, data fresh
    execution_agent_healthy: bool = True  # EA registered for this account, identity ok, tradable, not halted
    account_trading_enabled: bool = True  # the user's « Disable Trading » switch (and the account's status)
    kill_switch_active: bool = False
    autonomy_permits_entries: bool = True


class TradingContext(DomainModel):
    risk: RiskInputs
    health: HealthFlags = HealthFlags()
    allowed_symbols: frozenset[str] | None = None  # None = every symbol the broker offers
    active_lockout: ActiveLockout | None = None
    # Open positions and the specs of their symbols are needed again for the "after" exposure of an intent.
    positions: tuple[Position, ...] = ()  # open positions (full objects), for the exposure *after* a new trade
    specs: dict[str, SymbolSpec] = Field(default_factory=dict)


class CheckResult(DomainModel):
    check_id: str
    label: str
    ok: bool
    reason: str | None = None  # stable machine code, set when not ok
    detail: str = ""


class CanITradeResult(DomainModel):
    decision: Literal["ALLOWED", "DENIED"]
    reasons: list[str]
    checks: list[CheckResult]
    evaluated_at: datetime


def _from_gate(check_id: str, label: str, gate: GateResult, reason: str) -> CheckResult:
    ok = not gate.blocked
    return CheckResult(check_id=check_id, label=label, ok=ok, reason=None if ok else reason, detail=gate.detail)


def _flag(check_id: str, label: str, ok: bool, reason: str, detail: str) -> CheckResult:
    return CheckResult(check_id=check_id, label=label, ok=ok, reason=None if ok else reason, detail=detail)


def _gate(state: RiskState, gate_id: str) -> GateResult:
    return next(g for g in state.gates if g.gate_id == gate_id)


def _checks(ctx: TradingContext, state: RiskState, symbol: str | None) -> list[CheckResult]:
    h = ctx.health
    now = ctx.risk.now
    lockout = ctx.active_lockout
    live_lockout = lockout is not None and not is_lockout_expired(lockout, now)
    kill = h.kill_switch_active or (live_lockout and lockout is not None and lockout.reason == KILL_SWITCH_REASON)
    other_lock = live_lockout and not kill

    results = [
        _flag(
            "account_healthy",
            "Account healthy",
            h.account_healthy,
            "account_unhealthy",
            "account snapshot fresh and tradable",
        ),
        _flag(
            "broker_connected", "Broker connected", h.broker_connected, "broker_disconnected", "terminal ↔ trade server"
        ),
        _flag("mt5_healthy", "MT5 healthy", h.mt5_healthy, "mt5_unhealthy", "reader process and data freshness"),
        _flag(
            "account_rules",
            "Account rules satisfied",
            h.account_trading_enabled,
            "account_trading_disabled",
            "trading enabled for this account",
        ),
        _from_gate(
            "daily_loss", "Daily loss budget available", _gate(state, "gate-daily-loss"), "daily_risk_budget_exceeded"
        ),
        _from_gate("max_drawdown", "Max drawdown safe", _gate(state, "gate-total-dd"), "max_drawdown_reached"),
        _from_gate("open_risk", "Open risk acceptable", _gate(state, "gate-open-risk"), "open_risk_too_high"),
        _from_gate(
            "correlation",
            "Correlated risk acceptable",
            _gate(state, "gate-correlation"),
            "correlated_exposure_too_high",
        ),
        _from_gate("news", "No news restriction", _gate(state, "gate-news"), "news_restriction"),
        _from_gate(
            "spread",
            "Spread acceptable",
            _gate(state, "gate-spread"),
            "no_live_tick" if ctx.risk.spread is None else "spread_too_wide",
        ),
        _from_gate("session", "Session acceptable", _gate(state, "gate-session"), "outside_trading_session"),
    ]
    if symbol is not None:
        results.append(
            _from_gate("symbol", "Symbol allowed", symbol_gate(symbol, ctx.allowed_symbols), "symbol_not_allowed")
        )
    results += [
        _from_gate("position_limit", "Position limit", _gate(state, "gate-position-limit"), "position_limit_reached"),
        _from_gate("max_trades", "Max trades not reached", _gate(state, "gate-max-trades"), "max_trades_reached"),
        _from_gate(
            "consecutive_losses",
            "Loss streak under limit",
            _gate(state, "gate-consec-loss"),
            "consecutive_losses_limit",
        ),
        _flag(
            "kill_switch", "Kill switch off", not kill, "kill_switch_active", "kill switch engaged" if kill else "off"
        ),
        _flag(
            "account_lock",
            "No active lockout",
            not other_lock,
            "account_locked",
            f"locked: {lockout.reason}" if other_lock and lockout else "none",
        ),
        _flag(
            "autonomy",
            "Autonomy permits entries",
            h.autonomy_permits_entries,
            "autonomy_not_permitting",
            "autonomy state",
        ),
        _flag(
            "execution_agent",
            "Execution agent healthy",
            h.execution_agent_healthy and not _gate(state, "gate-connection").blocked,
            "execution_agent_unhealthy",
            "EA registered, identity ok, tradable, not halted",
        ),
    ]
    return results


def can_i_trade(ctx: TradingContext, symbol: str | None = None) -> CanITradeResult:
    """Account-level answer, with an optional symbol. With a symbol a live tick is required (an order is in view)."""
    risk = ctx.risk.model_copy(update={"require_tick": symbol is not None})
    state = evaluate_risk_state(risk)
    checks = _checks(ctx.model_copy(update={"risk": risk}), state, symbol)
    reasons = [c.reason for c in checks if c.reason]
    return CanITradeResult(
        decision="DENIED" if reasons else "ALLOWED", reasons=reasons, checks=checks, evaluated_at=ctx.risk.now
    )


class RiskDecision(DomainModel):
    decision_id: str
    intent_id: str | None
    account_id: AccountId
    approved: bool
    approved_volume: float | None
    # The terms that were reviewed. An execution command must not deviate from them (symbol and side equal, volume
    # at most the approved one, stop at least as tight): the approval covers *this* trade, not any trade.
    symbol: SymbolCode | None = None
    side: Side | None = None
    entry_price: float | None = None
    stop_loss: float | None = None
    take_profit: float | None = None
    reasons: list[str]
    checks: list[CheckResult]
    sizing: SizingResult | None
    gates: list[GateResult]
    decided_at: datetime
    expires_at: datetime


class IntentReview(DomainModel):
    """What only the intent needs (the account-level context is the ``TradingContext``)."""

    spec: SymbolSpec | None
    spread: float | None  # live, price units
    commission_per_lot_round_trip: float = 0.0
    cost_threshold: float = 0.25  # S01 « porte de coût » — evaluated at decision and again at fill
    max_volume_per_order: float | None = None
    ttl: timedelta = DEFAULT_DECISION_TTL


def _intent_failures(intent: TradeIntent, review: IntentReview) -> list[CheckResult]:
    failures: list[CheckResult] = []
    spec = review.spec
    if spec is None:
        failures.append(
            CheckResult(
                check_id="symbol_spec",
                label="Symbol specification known",
                ok=False,
                reason="symbol_spec_missing",
                detail=f"no broker specification for {intent.symbol}",
            )
        )
        return failures
    stop_distance = (intent.entry_price - intent.stop_loss) * intent.side.direction
    if stop_distance <= 0:
        failures.append(
            CheckResult(
                check_id="stop_side",
                label="Stop on the losing side",
                ok=False,
                reason="stop_wrong_side",
                detail=f"stop {intent.stop_loss:g} vs entry {intent.entry_price:g}",
            )
        )
    if intent.take_profit > 0 and (intent.take_profit - intent.entry_price) * intent.side.direction <= 0:
        failures.append(
            CheckResult(
                check_id="target_side",
                label="Target on the winning side",
                ok=False,
                reason="target_wrong_side",
                detail=f"target {intent.take_profit:g} vs entry {intent.entry_price:g}",
            )
        )
    if stop_distance > 0 and review.spread is not None:
        commission = commission_in_price(review.commission_per_lot_round_trip, spec)
        ratio = cost_ratio(review.spread, commission, stop_distance)
        if ratio > review.cost_threshold:
            failures.append(
                CheckResult(
                    check_id="cost_gate",
                    label="Cost ratio acceptable",
                    ok=False,
                    reason="cost_too_high",
                    detail=f"c = {ratio:.3f} > {review.cost_threshold:g}",
                )
            )
    return failures


def decide(ctx: TradingContext, intent: TradeIntent, review: IntentReview) -> RiskDecision:
    """Review one intent. Always returns a decision (approved or not) so the trail explains every refusal."""
    base = can_i_trade(ctx, symbol=intent.symbol)
    checks = list(base.checks)
    failures = _intent_failures(intent, review)
    sizing: SizingResult | None = None

    if not failures and review.spec is not None:
        profile = ctx.risk.profile
        try:
            sizing = size_position(
                balance=ctx.risk.balance,
                risk_percent=profile.max_risk_per_trade_percent,
                side=intent.side,
                entry_price=intent.entry_price,
                stop_loss=intent.stop_loss,
                spec=review.spec,
                spread=review.spread or 0.0,
                commission_per_lot_round_trip=review.commission_per_lot_round_trip,
                volume_cap=review.max_volume_per_order or profile.positions.max_volume_per_order,
            )
        except SizingError as error:
            failures.append(
                CheckResult(
                    check_id="sizing",
                    label="Sized from broker specification",
                    ok=False,
                    reason=error.code,
                    detail=error.safe_message,
                )
            )
        if sizing is not None and ctx.risk.balance > 0:
            after_percent = ctx.risk.open_risk_percent + sizing.risk_at_stop / ctx.risk.balance * 100
            if after_percent > profile.max_open_risk_percent:
                failures.append(
                    CheckResult(
                        check_id="open_risk_after",
                        label="Open risk after this trade",
                        ok=False,
                        reason="open_risk_too_high",
                        detail=f"{after_percent:.2f}% > {profile.max_open_risk_percent:g}%",
                    )
                )
            shared = _correlated_after(ctx, intent, review.spec, sizing)
            if shared > profile.max_correlated_risk_percent:
                failures.append(
                    CheckResult(
                        check_id="correlation_after",
                        label="Correlated risk after this trade",
                        ok=False,
                        reason="correlated_exposure_too_high",
                        detail=f"{shared:.2f}% > {profile.max_correlated_risk_percent:g}%",
                    )
                )

    checks += failures
    reasons: list[str] = []
    for check in checks:
        if check.reason and check.reason not in reasons:
            reasons.append(check.reason)
    approved = not reasons and sizing is not None
    state = evaluate_risk_state(ctx.risk.model_copy(update={"require_tick": True}))
    return RiskDecision(
        decision_id=new_id("risk"),
        intent_id=intent.intent_id,
        account_id=intent.account_id,
        approved=approved,
        approved_volume=sizing.volume if approved and sizing else None,
        symbol=intent.symbol,
        side=intent.side,
        entry_price=intent.entry_price,
        stop_loss=intent.stop_loss,
        take_profit=intent.take_profit,
        reasons=reasons,
        checks=checks,
        sizing=sizing if approved else None,
        gates=state.gates,
        decided_at=ctx.risk.now,
        expires_at=ctx.risk.now + review.ttl,
    )


def _correlated_after(ctx: TradingContext, intent: TradeIntent, spec: SymbolSpec, sizing: SizingResult) -> float:
    """Largest shared (same currency, same direction) exposure once the intended position is added."""
    balance = ctx.risk.balance
    candidate = Position(
        position_id="__candidate__",
        account_id=intent.account_id,
        symbol=intent.symbol,
        side=intent.side,
        volume=sizing.volume,
        entry_price=intent.entry_price,
        stop_loss=intent.stop_loss,
    )
    positions = [*ctx.positions, candidate]
    specs = {**ctx.specs, intent.symbol: spec}
    amounts = {}
    for position in positions:
        position_spec = specs.get(position.symbol)
        if position_spec is not None:
            amount = position_risk_amount(position, position_spec)
            if amount is not None:
                amounts[position.position_id] = amount
    percent, _ = max_correlated_exposure(currency_exposure(positions, specs, amounts, balance))
    return percent


__all__ = [
    "CanITradeResult",
    "CheckResult",
    "HealthFlags",
    "IntentReview",
    "RiskDecision",
    "TradingContext",
    "can_i_trade",
    "decide",
]
