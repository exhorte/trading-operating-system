"""After-the-fact compliance (T07): did a closed trade respect the rules? Pure — port of ``lib/compliance``, now judged by the
server (the browser and the MCP no longer evaluate rules).

This is *review*, exactly as ADR 0005 scopes it: it classifies, it never orders and decides nothing live (that is the Risk
Engine, ADR 0007). Three closed-taxonomy questions, each about one trade:

* **LOCKOUT_ACTIVE** — was a lockout in force when the position opened? Generalises « locked right now » to an arbitrary
  past instant: it had begun, had not been cleared, had not expired — all evaluated *at that instant*;
* **SESSION_WINDOW** — did it open outside the account's trading windows? (A deliberate change from the browser version,
  which read fixed UTC buckets: the question is judged with the very predicate the live session gate uses — the
  user's killzones in New York time — so the review and the gate cannot disagree.)
* **SIZE_POLICY** — was the size above what the risk policy would have approved, from the symbol's own tick size and value?

Honest nulls, never a false pass or a false violation: no opening time → nothing can be judged; no stop, no balance or
no symbol specification → the size check is skipped (the other two still run).
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import datetime

from trading_os.domain.journal.models import (
    ComplianceSummary,
    JournalTrade,
    Violation,
    ViolationType,
)
from trading_os.domain.market.models import SymbolSpec
from trading_os.domain.market.sessions import NY_TIME_ZONE, TradingWindow, in_trading_window
from trading_os.domain.risk.lockout import LockoutWindow
from trading_os.domain.risk.sizing import loss_per_lot
from trading_os.shared.errors import SizingError

# A trade within this factor of the approved maximum is not flagged: sizing floors the volume to the broker's step, so a
# trade taken at exactly the approved size can land a hair above the raw maximum computed here.
SIZE_TOLERANCE = 1.05


def detect_lockout_violation(opened_at: datetime, lockouts: Sequence[LockoutWindow]) -> Violation | None:
    for window in lockouts:
        if window.since > opened_at:
            continue
        if window.cleared_at is not None and window.cleared_at <= opened_at:
            continue
        if window.until is not None and window.until <= opened_at:
            continue
        return Violation(type=ViolationType.LOCKOUT_ACTIVE, detail=f"{window.reason} (lockout {window.lockout_id})")
    return None


def detect_session_violation(opened_at: datetime, windows: Sequence[TradingWindow]) -> Violation | None:
    if in_trading_window(opened_at, windows):
        return None
    local = opened_at.astimezone(NY_TIME_ZONE)
    return Violation(
        type=ViolationType.SESSION_WINDOW,
        detail=f"opened {local:%a %H:%M} New York time, outside the trading windows",
    )


def detect_size_violation(
    *,
    volume: float,
    entry_price: float,
    stop_loss: float,
    balance: float,
    max_risk_percent: float,
    spec: SymbolSpec,
) -> Violation | None:
    if stop_loss <= 0:  # 0 is MT5's « no stop », not a level
        return None
    distance = abs(entry_price - stop_loss)
    if distance <= 0:
        return None
    try:
        per_lot = loss_per_lot(spec, distance)
    except SizingError:
        return None  # the broker gave no tick value: cannot judge, will not guess
    if per_lot <= 0:
        return None
    maximum = balance * max_risk_percent / 100 / per_lot
    if volume <= maximum * SIZE_TOLERANCE:
        return None
    return Violation(
        type=ViolationType.SIZE_POLICY,
        detail=f"{volume:.2f} lot exceeds the {max_risk_percent:g}% risk budget (~{maximum:.2f} lot max, current balance)",
    )


def evaluate_trade(
    trade: JournalTrade,
    lockouts: Sequence[LockoutWindow],
    windows: Sequence[TradingWindow],
    *,
    balance: float | None,
    max_risk_percent: float,
    spec: SymbolSpec | None,
) -> list[Violation]:
    """All applicable violations for one trade. An unknown opening time means lockout and session cannot be judged at
    all — an empty result, not a guessed pass (the same honest null the journal shows)."""
    if trade.opened_at is None:
        return []
    found: list[Violation] = []
    for violation in (
        detect_lockout_violation(trade.opened_at, lockouts),
        detect_session_violation(trade.opened_at, windows),
    ):
        if violation is not None:
            found.append(violation)
    if balance is not None and spec is not None and trade.entry_price is not None and trade.stop_loss is not None:
        size = detect_size_violation(
            volume=trade.volume,
            entry_price=trade.entry_price,
            stop_loss=trade.stop_loss,
            balance=balance,
            max_risk_percent=max_risk_percent,
            spec=spec,
        )
        if size is not None:
            found.append(size)
    return found


def compliance_rate(violations_per_trade: Sequence[Sequence[Violation]]) -> float:
    """Trades with no violation ÷ all trades; 1 on an empty window (nothing to violate is not a bad score)."""
    if not violations_per_trade:
        return 1.0
    return sum(1 for v in violations_per_trade if not v) / len(violations_per_trade)


def summarize_compliance(
    trades: Sequence[JournalTrade],
    lockouts: Sequence[LockoutWindow],
    windows: Sequence[TradingWindow],
    *,
    balance: float | None,
    max_risk_percent: float,
    specs: Mapping[str, SymbolSpec],
) -> ComplianceSummary:
    by_trade: dict[str, list[Violation]] = {}
    for trade in trades:
        by_trade[trade.broker_position_id] = evaluate_trade(
            trade, lockouts, windows, balance=balance, max_risk_percent=max_risk_percent, spec=specs.get(trade.symbol)
        )
    by_type = dict.fromkeys(ViolationType, 0)
    for violations in by_trade.values():
        for violation in violations:
            by_type[violation.type] += 1
    return ComplianceSummary(
        rate=compliance_rate(list(by_trade.values())),
        trade_count=len(by_trade),
        breached_count=sum(1 for v in by_trade.values() if v),
        by_type=by_type,
        by_trade=by_trade,
    )


def r_multiple(trade: JournalTrade) -> float | None:
    """What came back, in units of the risk taken at the stop. ``None`` when the entry or the stop were not recorded."""
    if trade.entry_price is None or trade.stop_loss is None or trade.stop_loss <= 0:
        return None
    risk = abs(trade.entry_price - trade.stop_loss)
    if risk <= 0:
        return None
    return round((trade.exit_price - trade.entry_price) * trade.side.direction / risk, 2)
