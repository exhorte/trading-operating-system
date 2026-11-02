"""What the Account Guardian watches beyond the loss limits (ADR 0032) — pure: readings, alerts and the reasons to ask for a reconciliation.
No threshold is invented: the spread is judged against the user's own cap, the slippage against the account's own cost threshold."""

from __future__ import annotations

from trading_os.domain.guardian.watch import (
    HealthFinding,
    SpreadReading,
    adverse_slippage,
    alerts,
    exposure_by_symbol,
    reconciliation_reason,
    slippage_reading,
    spread_readings,
    wide_spread_symbols,
)
from trading_os.domain.positions.models import PendingOrder, Position
from trading_os.domain.primitives import Side


def position(
    side: Side = Side.BUY, *, entry: float = 1.1000, volume: float = 0.1, symbol: str = "EURUSDm", pid: str = "1"
) -> Position:
    return Position(
        position_id=pid, account_id="A", symbol=symbol, side=side, volume=volume, entry_price=entry, stop_loss=1.0990
    )


def order(symbol: str = "EURUSDm", oid: str = "9") -> PendingOrder:
    return PendingOrder(
        order_id=oid, account_id="A", symbol=symbol, side=Side.BUY, order_type="limit", volume=0.1, price=1.0990
    )


class TestSpread:
    def test_it_is_judged_against_the_cap_the_user_wrote_and_only_where_the_core_is_exposed(self) -> None:
        readings = spread_readings({"EURUSDm": 0.0004, "XAUUSDm": 0.5}, {"EURUSDm": 0.00025}, {"EURUSDm"})
        assert [(r.symbol, r.spread, r.cap, r.over_cap) for r in readings] == [("EURUSDm", 0.0004, 0.00025, True)]
        assert wide_spread_symbols(readings) == {"EURUSDm"}

    def test_a_symbol_with_no_cap_is_read_never_judged(self) -> None:
        (reading,) = spread_readings({"XAUUSDm": 0.5}, {}, {"XAUUSDm"})
        assert reading.cap is None and not reading.over_cap and wide_spread_symbols([reading]) == set()

    def test_at_the_cap_is_not_over_it(self) -> None:
        assert not SpreadReading(symbol="EURUSDm", spread=0.00025, cap=0.00025, exposed=True).over_cap

    def test_a_symbol_without_a_quote_has_no_reading(self) -> None:
        assert spread_readings({}, {"EURUSDm": 0.00025}, {"EURUSDm"}) == []


class TestSlippage:
    def test_only_a_worse_fill_is_slippage(self) -> None:
        assert adverse_slippage(Side.BUY, 1.1000, 1.1004) == 0.0004  # bought higher than asked
        assert adverse_slippage(Side.SELL, 1.1000, 1.0996) == 0.0004  # sold lower than asked
        assert adverse_slippage(Side.BUY, 1.1000, 1.0998) == 0.0  # a better fill is not slippage
        assert adverse_slippage(Side.SELL, 1.1000, 1.1002) == 0.0

    def test_it_is_measured_as_a_share_of_the_risk_of_the_trade(self) -> None:
        reading = slippage_reading(position(entry=1.1004), 1.1000, 1.0990)
        assert reading is not None and reading.adverse_price == 0.0004 and reading.share_of_risk == 0.4

    def test_a_market_order_names_no_price_so_nothing_is_measured_or_guessed(self) -> None:
        assert slippage_reading(position(entry=1.1004), None, 1.0990) is None

    def test_without_a_distance_to_the_stop_the_share_is_unknown_not_zero(self) -> None:
        reading = slippage_reading(position(entry=1.1004), 1.1000, None)
        assert reading is not None and reading.share_of_risk is None


class TestExposure:
    def test_it_is_reported_per_symbol_whoever_opened_it_and_is_not_limited(self) -> None:
        rows = exposure_by_symbol(
            [position(pid="1"), position(Side.SELL, volume=0.05, pid="2"), position(symbol="XAUUSDm", pid="3")],
            [order()],
        )
        assert [(r.symbol, r.positions, r.long_lots, r.short_lots, r.resting_orders) for r in rows] == [
            ("EURUSDm", 2, 0.1, 0.05, 1),
            ("XAUUSDm", 1, 0.1, 0.0, 0),
        ]


class TestAlerts:
    wide = SpreadReading(symbol="EURUSDm", spread=0.0004, cap=0.00025, exposed=True)

    def test_a_wide_spread_while_exposed_is_an_alert(self) -> None:
        (text,) = alerts(spreads=[self.wide], slippage=[], slippage_threshold=0.25, unhealthy=[], exposed=True)
        assert "EURUSDm" in text and "over the cap" in text

    def test_slippage_above_the_accounts_cost_threshold_is_an_alert_and_below_it_is_not(self) -> None:
        big = slippage_reading(position(entry=1.1004), 1.1000, 1.0990)  # 40 % of the risk
        small = slippage_reading(position(entry=1.1001, pid="2"), 1.1000, 1.0990)  # 10 %
        assert big is not None and small is not None
        out = alerts(spreads=[], slippage=[big, small], slippage_threshold=0.25, unhealthy=[], exposed=True)
        assert len(out) == 1 and "40%" in out[0] and "worse than asked" in out[0]

    def test_ill_health_is_only_worth_an_alert_while_something_is_exposed(self) -> None:
        down = [HealthFinding(source="agent", ok=False, detail="no execution agent connected for this account")]
        assert alerts(spreads=[], slippage=[], slippage_threshold=0.25, unhealthy=down, exposed=False) == []
        (text,) = alerts(spreads=[], slippage=[], slippage_threshold=0.25, unhealthy=down, exposed=True)
        assert text.startswith("agent:")


class TestAskingForAReconciliation:
    def test_nothing_to_settle_means_no_request(self) -> None:
        assert reconciliation_reason(doubtful_commands=0, unreadable_runs=0, agent_came_back=False) is None

    def test_each_reason_only_a_comparison_with_the_broker_can_settle_is_named(self) -> None:
        text = reconciliation_reason(doubtful_commands=2, unreadable_runs=3, agent_came_back=True)
        assert text is not None
        assert "2 command(s) in doubt" in text and "3 reconciliation run(s)" in text and "agent reconnected" in text
        assert reconciliation_reason(doubtful_commands=0, unreadable_runs=0, agent_came_back=True) is not None
