"""What the Account Guardian watches beyond the loss limits (ADR 0032, plan §9) — pure.

Three kinds of output, none of them an entry: a *reading* (a number, shown), an *alert* (a sentence, shown), and the two things the Guardian
may ask for because they only ever reduce what is exposed or only look — the cancellation of the core's resting orders where the spread is
over the cap the user wrote (off unless he switches it on), and a reconciliation (read-only towards the broker).

Nothing here invents a threshold: the spread is judged against the account's own per-symbol caps (``ExecutionLimits.max_spread_by_symbol``),
the slippage against the account's own cost threshold (``cost_threshold``, the share of a trade's risk costs may eat), and a symbol with no
cap is *read*, never judged. Exposure by symbol is reported and not limited — the user removed the per-symbol limit (ADR 0022).
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Literal

from pydantic import Field

from trading_os.domain.positions.models import PendingOrder, Position
from trading_os.domain.primitives import DomainModel, Side

HealthSource = Literal["terminal", "market_data", "agent", "broker", "reconciliation", "system"]


class HealthFinding(DomainModel):
    source: HealthSource
    ok: bool
    detail: str


class SymbolExposure(DomainModel):
    symbol: str
    positions: int = 0
    long_lots: float = 0.0
    short_lots: float = 0.0
    resting_orders: int = 0


class SpreadReading(DomainModel):
    symbol: str
    spread: float  # price units
    cap: float | None = None  # the user's ceiling for the symbol; None = none written, so nothing to judge it against
    exposed: bool = False  # a position or a resting order of the core is on this symbol

    @property
    def over_cap(self) -> bool:
        return self.cap is not None and self.cap > 0 and self.spread > self.cap + 1e-12


class SlippageReading(DomainModel):
    position_id: str
    symbol: str
    requested_price: float
    filled_price: float
    adverse_price: float  # > 0 = filled worse than asked; never negative (a better fill is not slippage)
    share_of_risk: float | None = (
        None  # adverse_price / the distance from the requested price to the stop; None = no distance to measure
    )


class GuardianWatch(DomainModel):
    """The figures and findings of one cycle — read model, never an input of a decision other than the ones named above."""

    equity: float | None = None
    balance: float | None = None
    daily_loss_used_percent: float | None = None
    daily_loss_limit_percent: float | None = None
    weekly_loss_used_percent: float | None = None
    weekly_loss_limit_percent: float | None = None
    total_loss_used_percent: float | None = None
    total_loss_limit_percent: float | None = None
    open_risk_percent: float | None = None
    open_risk_limit_percent: float | None = None
    positions: int = 0
    trades_today: int | None = None
    max_trades_per_day: int | None = None
    entries_allowed: bool | None = (
        None  # what the Risk Engine would answer now to « may a new trade open? » — read, never decided here
    )
    entries_blocked_by: list[str] = Field(default_factory=list)
    exposure: list[SymbolExposure] = Field(default_factory=list)
    spreads: list[SpreadReading] = Field(default_factory=list)
    slippage: list[SlippageReading] = Field(default_factory=list)
    health: list[HealthFinding] = Field(default_factory=list)

    @property
    def unhealthy(self) -> list[HealthFinding]:
        return [finding for finding in self.health if not finding.ok]


def exposure_by_symbol(positions: Sequence[Position], orders: Sequence[PendingOrder]) -> list[SymbolExposure]:
    """Lots long and short and resting orders per symbol — every position on the account, whoever opened it. Reported, not limited."""
    counts: dict[str, dict[str, float]] = {}
    for position in positions:
        row = counts.setdefault(position.symbol, {"positions": 0, "long": 0.0, "short": 0.0, "orders": 0})
        row["positions"] += 1
        row["long" if position.side is Side.BUY else "short"] += position.volume
    for order in orders:
        counts.setdefault(order.symbol, {"positions": 0, "long": 0.0, "short": 0.0, "orders": 0})["orders"] += 1
    return [
        SymbolExposure(
            symbol=symbol,
            positions=int(row["positions"]),
            long_lots=round(row["long"], 8),
            short_lots=round(row["short"], 8),
            resting_orders=int(row["orders"]),
        )
        for symbol, row in sorted(counts.items())
    ]


def spread_readings(
    spreads: Mapping[str, float], caps: Mapping[str, float], exposed_symbols: set[str]
) -> list[SpreadReading]:
    """One reading per symbol the core is exposed on (the others are not the Guardian's business). The cap is the user's own."""
    return [
        SpreadReading(symbol=symbol, spread=spreads[symbol], cap=caps.get(symbol), exposed=True)
        for symbol in sorted(exposed_symbols)
        if symbol in spreads
    ]


def wide_spread_symbols(readings: Sequence[SpreadReading]) -> set[str]:
    return {reading.symbol for reading in readings if reading.exposed and reading.over_cap}


def adverse_slippage(side: Side, requested: float, filled: float) -> float:
    """How much worse than ``requested`` the fill was, in price units; 0 when it was as good or better."""
    worse = filled - requested if side is Side.BUY else requested - filled
    return max(0.0, round(worse, 10))


def slippage_reading(
    position: Position, requested_price: float | None, opening_stop: float | None
) -> SlippageReading | None:
    """Slippage of a position that opened from a LIMIT order (the only opening that names a price to compare with). A market order names
    none: its slippage is bounded at the agent (``deviation``), not measurable here, and is not guessed."""
    if requested_price is None or requested_price <= 0:
        return None
    adverse = adverse_slippage(position.side, requested_price, position.entry_price)
    distance = abs(requested_price - opening_stop) if opening_stop else 0.0
    return SlippageReading(
        position_id=position.position_id,
        symbol=position.symbol,
        requested_price=requested_price,
        filled_price=position.entry_price,
        adverse_price=adverse,
        share_of_risk=round(adverse / distance, 6) if distance > 0 else None,
    )


def alerts(
    *,
    spreads: Sequence[SpreadReading],
    slippage: Sequence[SlippageReading],
    slippage_threshold: float,
    unhealthy: Sequence[HealthFinding],
    exposed: bool,
) -> list[str]:
    """The sentences the verdict carries. Health is only worth an alert while something is exposed: with nothing open, the Risk Engine's own
    gates already say what is wrong, and the readiness report lists it."""
    out: list[str] = []
    for reading in spreads:
        if reading.exposed and reading.over_cap:
            out.append(
                f"{reading.symbol}: spread {reading.spread:g} is over the cap {reading.cap:g} while the core is exposed on it"
            )
    for slip in slippage:
        if slip.share_of_risk is not None and slip.share_of_risk > slippage_threshold + 1e-9:
            out.append(
                f"{slip.symbol} {slip.position_id}: filled {slip.adverse_price:g} worse than asked "
                f"({slip.share_of_risk:.0%} of its risk, the account's cost threshold is {slippage_threshold:.0%})"
            )
    if exposed:
        out += [f"{finding.source}: {finding.detail}" for finding in unhealthy]
    return out


def reconciliation_reason(*, doubtful_commands: int, unreadable_runs: int, agent_came_back: bool) -> str | None:
    """Why the Guardian asks for a reconciliation now, or ``None``. All three are things only a comparison with the broker can settle."""
    reasons: list[str] = []
    if doubtful_commands:
        reasons.append(f"{doubtful_commands} command(s) in doubt (UNKNOWN or RECONCILING)")
    if unreadable_runs:
        reasons.append(f"the last {unreadable_runs} reconciliation run(s) could not read the broker")
    if agent_came_back:
        reasons.append("the execution agent reconnected: what it did while away is not known")
    return "; ".join(reasons) or None


__all__ = [
    "GuardianWatch",
    "HealthFinding",
    "SlippageReading",
    "SpreadReading",
    "SymbolExposure",
    "adverse_slippage",
    "alerts",
    "exposure_by_symbol",
    "reconciliation_reason",
    "slippage_reading",
    "spread_readings",
    "wide_spread_symbols",
]
