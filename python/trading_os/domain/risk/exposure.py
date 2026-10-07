"""Open risk and correlated exposure, computed from broker specifications (no hard-coded contract factor).

* **Open risk** — what the open positions lose if every stop is hit. A position **without a stop has unbounded
  risk**: it is reported as unprotected and blocks new entries (no trade without a stop), instead of being silently
  counted as zero as the previous engine did.
* **Correlated exposure** — a position is long its base currency and short its profit currency (reverse for a sell).
  Risk riding on the *same currency in the same direction* adds up: long EURUSD + long GBPUSD is short USD twice.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field

from trading_os.domain.market.models import SymbolSpec
from trading_os.domain.positions.models import Position
from trading_os.domain.primitives import Side
from trading_os.domain.risk.sizing import loss_per_lot


def position_risk_amount(position: Position, spec: SymbolSpec) -> float | None:
    """Loss at the stop (account currency), 0 when the stop already locks in a profit, ``None`` without a stop."""
    if not position.has_stop:
        return None
    distance = max(0.0, (position.entry_price - position.stop_loss) * position.side.direction)
    return loss_per_lot(spec, distance) * position.volume


@dataclass
class OpenRiskReport:
    total_amount: float = 0.0
    percent: float = 0.0
    unprotected: list[str] = field(default_factory=list)  # position ids with no stop
    unknown_spec: list[str] = field(default_factory=list)  # position ids whose symbol spec we do not have
    per_position: dict[str, float] = field(default_factory=dict)

    @property
    def complete(self) -> bool:
        """True when every open position's risk is known and bounded."""
        return not self.unprotected and not self.unknown_spec


def open_risk(positions: Iterable[Position], specs: Mapping[str, SymbolSpec], balance: float) -> OpenRiskReport:
    report = OpenRiskReport()
    for position in positions:
        spec = specs.get(position.symbol)
        if spec is None:
            report.unknown_spec.append(position.position_id)
            continue
        amount = position_risk_amount(position, spec)
        if amount is None:
            report.unprotected.append(position.position_id)
            continue
        report.per_position[position.position_id] = amount
        report.total_amount += amount
    if balance > 0:
        report.percent = round(report.total_amount / balance * 100, 2)
    return report


def currency_legs(symbol_spec: SymbolSpec, side: Side) -> tuple[tuple[str, str], tuple[str, str]]:
    """((currency, 'long'|'short'), …): a buy is long the base and short the profit currency; a sell reverses it."""
    base, profit = symbol_spec.currency_base, symbol_spec.currency_profit
    if side is Side.BUY:
        return (base, "long"), (profit, "short")
    return (base, "short"), (profit, "long")


@dataclass
class ExposureBucket:
    """Risk (percent of balance) riding on one (currency, direction), and which positions carry it."""

    percent: float = 0.0
    position_ids: list[str] = field(default_factory=list)


def currency_exposure(
    positions: Iterable[Position],
    specs: Mapping[str, SymbolSpec],
    risk_amounts: Mapping[str, float],
    balance: float,
) -> dict[tuple[str, str], ExposureBucket]:
    buckets: dict[tuple[str, str], ExposureBucket] = defaultdict(ExposureBucket)
    if balance <= 0:
        return {}
    for position in positions:
        spec = specs.get(position.symbol)
        amount = risk_amounts.get(position.position_id)
        if spec is None or amount is None:
            continue
        for leg in currency_legs(spec, position.side):
            buckets[leg].percent += amount / balance * 100
            buckets[leg].position_ids.append(position.position_id)
    return dict(buckets)


def max_correlated_exposure(
    buckets: Mapping[tuple[str, str], ExposureBucket],
) -> tuple[float, tuple[str, str] | None]:
    """Largest exposure carried by **two or more** positions on the same (currency, direction).

    A lone position is not a correlation: its own size is the per-trade limit's business.
    """
    shared = {key: bucket for key, bucket in buckets.items() if len(bucket.position_ids) >= 2}
    if not shared:
        return 0.0, None
    key = max(shared, key=lambda k: shared[k].percent)
    return round(shared[key].percent, 4), key
