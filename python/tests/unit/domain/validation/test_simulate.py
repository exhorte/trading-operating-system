"""One proposed trade played forward (ADR 0026): fills, stops, targets, costs, and the pessimism applied where a candle cannot say."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from trading_os.domain.market.models import Candle
from trading_os.domain.positions.manager import ExitPlan
from trading_os.domain.primitives import Side, Timeframe
from trading_os.domain.validation.simulate import SimulationSettings, TradeCosts, TradeSpec, simulate_trade

T0 = datetime(2026, 11, 2, 12, 10, tzinfo=UTC)  # Monday 07:10 New York: inside the NY AM window
COSTS = TradeCosts(spread=0.00008, commission=0.00002, stop_slippage=0.00001)
RISK = 0.0010


def candle(minute: int, high: float, low: float, close: float | None = None, *, start: datetime = T0) -> Candle:
    return Candle(
        symbol="EURUSDm", timeframe=Timeframe.M1, open_time=start + timedelta(minutes=minute), open=(high + low) / 2,
        high=high, low=low, close=(high + low) / 2 if close is None else close, closed=True,
    )  # fmt: skip


def buy(**changes: object) -> TradeSpec:
    base: dict[str, object] = {
        "symbol": "EURUSDm", "side": Side.BUY, "entry": 1.1000, "stop": 1.0990, "target": 1.1030, "placed_at": T0,
    }  # fmt: skip
    base.update(changes)
    return TradeSpec(**base)


def sell(**changes: object) -> TradeSpec:
    return buy(side=Side.SELL, entry=1.1000, stop=1.1010, target=1.0970, **changes)


class TestBuy:
    def test_filled_then_target_reached_costs_only_the_commission(self) -> None:
        trade = simulate_trade(buy(), [candle(0, 1.1005, 1.0999, 1.1002), candle(1, 1.1031, 1.1002)], COSTS)
        assert trade.outcome == "target" and trade.taken
        assert trade.r_gross == pytest.approx(3.0) and trade.r_net == pytest.approx(3.0 - 0.02)
        assert trade.window == "new_york_am" and trade.minutes_held == pytest.approx(2.0)

    def test_a_stop_costs_one_r_plus_slippage_and_commission(self) -> None:
        trade = simulate_trade(buy(), [candle(0, 1.1005, 1.0999, 1.1002), candle(1, 1.1004, 1.0989)], COSTS)
        assert trade.outcome == "stop"
        assert trade.r_gross == pytest.approx(-1.01) and trade.r_net == pytest.approx(-1.03)

    def test_the_ask_must_reach_the_limit_not_the_bid(self) -> None:
        # a bid low of 1.09995 means an ask of 1.10003: above the buy limit, so no fill; a bid low of 1.09992 gives exactly 1.1000
        assert simulate_trade(buy(), [candle(0, 1.1005, 1.09995)], COSTS).outcome == "unfilled"
        assert simulate_trade(buy(), [candle(0, 1.1005, 1.09992)], COSTS).taken

    def test_filled_and_stopped_on_the_same_candle_is_a_loss(self) -> None:
        trade = simulate_trade(buy(), [candle(0, 1.1040, 1.0985)], COSTS)
        assert trade.outcome == "stop" and trade.r_net is not None and trade.r_net < -1

    def test_the_fill_candle_never_takes_the_profit(self) -> None:
        # it fills and reaches the target in the same candle: nobody knows the order, so only the next candles can win
        trade = simulate_trade(buy(), [candle(0, 1.1040, 1.0999, 1.1020), candle(1, 1.1010, 1.1000)], COSTS)
        assert trade.outcome == "time" and trade.filled_at == T0

    def test_a_target_seen_before_the_price_invalidates_the_order(self) -> None:
        trade = simulate_trade(buy(), [candle(0, 1.1031, 1.1010)], COSTS)
        assert trade.outcome == "invalidated" and not trade.taken

    def test_an_order_that_waits_too_long_is_cancelled(self) -> None:
        waiting = [candle(m, 1.1010, 1.1005) for m in range(0, 40)]
        assert simulate_trade(buy(), waiting, COSTS, SimulationSettings(max_wait_minutes=30)).outcome == "expired"

    def test_an_order_still_waiting_when_the_data_ends_is_unfilled(self) -> None:
        assert simulate_trade(buy(), [candle(m, 1.1010, 1.1005) for m in range(5)], COSTS).outcome == "unfilled"

    def test_candles_before_the_order_do_not_count(self) -> None:
        early = candle(-5, 1.1005, 1.0980)  # would have filled and stopped — before the order existed
        assert simulate_trade(buy(), [early, candle(0, 1.1010, 1.1005)], COSTS).outcome == "unfilled"


class TestSell:
    def test_a_short_fills_when_the_bid_reaches_the_limit_and_wins_at_the_target(self) -> None:
        trade = simulate_trade(sell(), [candle(0, 1.1001, 1.0995, 1.0998), candle(1, 1.0999, 1.0962)], COSTS)
        assert trade.outcome == "target" and trade.r_gross == pytest.approx(3.0)

    def test_its_stop_is_an_ask_level(self) -> None:
        # the bid high is 1.10095, ask = +0.8 pip = 1.10103 >= 1.1010: stopped although the bid never reached it
        trade = simulate_trade(sell(), [candle(0, 1.1001, 1.0995), candle(1, 1.10095, 1.0998)], COSTS)
        assert trade.outcome == "stop" and trade.r_gross == pytest.approx(-1.01)


class TestManagement:
    def test_break_even_is_applied_then_a_return_to_it_stops_for_a_small_gain(self) -> None:
        candles = [
            candle(0, 1.1005, 1.0999, 1.1002),
            candle(1, 1.1013, 1.1003, 1.1012),  # +1.2 R at the close: the stop goes to entry + costs (1.1001)
            candle(2, 1.1010, 1.1000, 1.1005),  # comes back through 1.1001
        ]
        trade = simulate_trade(buy(), candles, COSTS)
        assert trade.outcome == "stop"
        assert trade.r_gross == pytest.approx(0.09) and trade.r_net == pytest.approx(0.07)

    def test_without_the_plan_the_same_path_is_not_stopped(self) -> None:
        candles = [
            candle(0, 1.1005, 1.0999, 1.1002),
            candle(1, 1.1013, 1.1003, 1.1012),
            candle(2, 1.1010, 1.1000, 1.1005),
        ]
        off = SimulationSettings(plan=ExitPlan(breakeven_at_r=None, close_outside_windows=False))
        assert simulate_trade(buy(), candles, COSTS, off).outcome == "time"

    def test_a_partial_close_pays_half_at_the_first_target_and_the_rest_at_the_second(self) -> None:
        candles = [
            candle(0, 1.1005, 1.0999, 1.1002),
            candle(1, 1.1013, 1.1003, 1.1012),
            candle(2, 1.1031, 1.1005, 1.1020),
        ]
        trade = simulate_trade(buy(), candles, COSTS, SimulationSettings(plan=ExitPlan(partial_at_r=1.0)))
        assert trade.outcome == "target"
        assert trade.r_gross == pytest.approx(0.5 * 1.2 + 0.5 * 3.0)

    def test_the_position_is_closed_before_the_window_ends(self) -> None:
        start = datetime(2026, 11, 2, 14, 50, tzinfo=UTC)  # 09:50 New York, the window closes at 10:00
        spec = buy(placed_at=start)
        candles = [candle(m, 1.1005, 1.0999 if m == 0 else 1.1001, 1.1002, start=start) for m in range(0, 9)]
        trade = simulate_trade(spec, candles, COSTS)
        assert trade.outcome == "window" and trade.closed_at is not None
        assert trade.closed_at <= datetime(2026, 11, 2, 14, 56, tzinfo=UTC)

    def test_a_position_held_too_long_is_closed_at_the_market(self) -> None:
        candles = [candle(0, 1.1005, 1.0999, 1.1002)] + [candle(m, 1.1006, 1.1001, 1.1003) for m in range(1, 8)]
        trade = simulate_trade(
            buy(), candles, COSTS, SimulationSettings(max_hold_minutes=5, plan=ExitPlan(breakeven_at_r=None))
        )
        assert trade.outcome == "time" and trade.minutes_held == pytest.approx(6.0)


def test_a_zero_distance_stop_cannot_be_played() -> None:
    assert simulate_trade(buy(stop=1.1000), [candle(0, 1.1005, 1.0999)], COSTS).outcome == "unfilled"
