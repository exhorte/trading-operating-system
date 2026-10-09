"""S01 step 7 — the stop loss: beyond the sweep's wick extreme plus a spread buffer (port of ``lib/setup/stop.ts``).

If the resulting distance exceeds the symbol's calibrated ceiling the setup is refused — but that ceiling is not a fixed number anywhere
in S01 (« plafond calibré du symbole », to come from the account profile), so ``max_distance`` is optional: omitted, no ceiling applies
yet, as the cost gate's own threshold is a parameter with a provisional default rather than a hard-coded constant.
"""

from __future__ import annotations

from trading_os.domain.primitives import DomainModel, Side


class StopLossResult(DomainModel):
    price: float
    distance: float


def compute_stop_loss(
    side: Side, sweep_wick_extreme: float, spread_buffer: float, entry_price: float, max_distance: float | None = None
) -> StopLossResult | None:
    price = sweep_wick_extreme - spread_buffer if side is Side.BUY else sweep_wick_extreme + spread_buffer
    distance = abs(entry_price - price)
    if max_distance is not None and distance > max_distance:
        return None  # stop too wide for this symbol's calibrated ceiling
    return StopLossResult(price=price, distance=distance)
