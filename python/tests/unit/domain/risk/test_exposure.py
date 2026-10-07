"""Open risk from broker specs (port of ``open-risk.test.ts``, without the gold factor) and correlated exposure."""

from __future__ import annotations

import pytest

from tests.unit.domain.risk.fixtures import EURUSD, GBPUSD, SPECS, XAUUSD, position
from trading_os.domain.primitives import Side
from trading_os.domain.risk.exposure import (
    currency_exposure,
    currency_legs,
    max_correlated_exposure,
    open_risk,
    position_risk_amount,
)


class TestPositionRisk:
    def test_xauusd_stop_distance_in_account_currency(self) -> None:
        # 10.00 × 0.1 lot × 100 oz = 100 USD (the figure of the legacy test, now from the broker spec)
        pos = position("1", "XAUUSDm", Side.BUY, 0.1, 3300.0, 3290.0)
        assert position_risk_amount(pos, XAUUSD) == pytest.approx(100.0)

    def test_eurusd_is_not_priced_as_gold(self) -> None:
        pos = position("1", "EURUSDm", Side.BUY, 0.5, 1.1000, 1.0980)  # 20 pips × 0.5 lot
        assert position_risk_amount(pos, EURUSD) == pytest.approx(100.0)

    def test_sell_side(self) -> None:
        pos = position("1", "EURUSDm", Side.SELL, 1.0, 1.0990, 1.1000)
        assert position_risk_amount(pos, EURUSD) == pytest.approx(100.0)

    def test_a_stop_beyond_break_even_carries_no_risk(self) -> None:
        trailed = position("1", "EURUSDm", Side.BUY, 1.0, 1.1000, 1.1010)
        assert position_risk_amount(trailed, EURUSD) == 0.0

    def test_no_stop_means_unbounded_not_zero(self) -> None:
        assert position_risk_amount(position("1", "EURUSDm", Side.BUY, 1.0, 1.1000, 0.0), EURUSD) is None


class TestOpenRisk:
    def test_sums_as_a_percent_of_balance(self) -> None:
        positions = [
            position("1", "XAUUSDm", Side.BUY, 0.1, 3300.0, 3290.0),  # 100 USD
            position("2", "XAUUSDm", Side.BUY, 0.2, 3310.0, 3305.0),  # 100 USD
        ]
        report = open_risk(positions, SPECS, 10_000.0)
        assert report.percent == 2.0 and report.total_amount == pytest.approx(200.0) and report.complete

    def test_unprotected_and_unmeasured_positions_are_reported_not_ignored(self) -> None:
        positions = [
            position("1", "EURUSDm", Side.BUY, 1.0, 1.1, 0.0),
            position("2", "ZZZ", Side.BUY, 1.0, 1.0, 0.9),
            position("3", "EURUSDm", Side.BUY, 1.0, 1.1000, 1.0990),
        ]
        report = open_risk(positions, SPECS, 10_000.0)
        assert report.unprotected == ["1"] and report.unknown_spec == ["2"] and not report.complete
        assert report.total_amount == pytest.approx(100.0)

    def test_zero_balance_gives_zero_percent(self) -> None:
        assert open_risk([], SPECS, 0.0).percent == 0.0


class TestCorrelation:
    def test_buy_is_long_base_short_profit_currency(self) -> None:
        assert currency_legs(EURUSD, Side.BUY) == (("EUR", "long"), ("USD", "short"))
        assert currency_legs(EURUSD, Side.SELL) == (("EUR", "short"), ("USD", "long"))

    def test_long_eurusd_and_long_gbpusd_are_short_usd_twice(self) -> None:
        positions = [
            position("a", "EURUSDm", Side.BUY, 0.5, 1.1000, 1.0980),  # 100 USD
            position("b", "GBPUSDm", Side.BUY, 0.5, 1.2500, 1.2480),  # 100 USD
        ]
        amounts = {"a": 100.0, "b": 100.0}
        percent, key = max_correlated_exposure(
            currency_exposure(positions, {"EURUSDm": EURUSD, "GBPUSDm": GBPUSD}, amounts, 10_000.0)
        )
        assert key == ("USD", "short") and percent == pytest.approx(2.0)

    def test_opposite_directions_do_not_stack(self) -> None:
        positions = [
            position("a", "EURUSDm", Side.BUY, 0.5, 1.1000, 1.0980),
            position("b", "GBPUSDm", Side.SELL, 0.5, 1.2480, 1.2500),
        ]
        buckets = currency_exposure(
            positions, {"EURUSDm": EURUSD, "GBPUSDm": GBPUSD}, {"a": 100.0, "b": 100.0}, 10_000.0
        )
        assert max_correlated_exposure(buckets) == (0.0, None)

    def test_gold_and_a_dollar_pair_share_the_dollar(self) -> None:
        positions = [
            position("a", "XAUUSDm", Side.BUY, 0.1, 3300.0, 3290.0),
            position("b", "EURUSDm", Side.BUY, 0.5, 1.1000, 1.0980),
        ]
        buckets = currency_exposure(
            positions, {"XAUUSDm": XAUUSD, "EURUSDm": EURUSD}, {"a": 100.0, "b": 100.0}, 10_000.0
        )
        assert max_correlated_exposure(buckets)[1] == ("USD", "short")

    def test_a_lone_position_is_not_a_correlation(self) -> None:
        pos = position("a", "EURUSDm", Side.BUY, 0.5, 1.1000, 1.0980)
        assert max_correlated_exposure(currency_exposure([pos], {"EURUSDm": EURUSD}, {"a": 100.0}, 10_000.0)) == (
            0.0,
            None,
        )

    def test_unmeasured_positions_are_skipped(self) -> None:
        pos = position("a", "EURUSDm", Side.BUY, 0.5, 1.1000, 0.0)
        assert currency_exposure([pos], {"EURUSDm": EURUSD}, {}, 10_000.0) == {}
