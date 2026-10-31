"""Broker-aware sizing on five instruments (XAUUSD, EURUSD, GBPUSD, GBPJPY, BTCUSD) — the case the old engine could not
get right: its hard-coded gold factor over-sized every other symbol by roughly 1000×."""

from __future__ import annotations

import math
from typing import Any

import pytest

from tests.unit.domain.risk.fixtures import BTCUSD, EURUSD, GBPJPY, GBPUSD, XAUUSD
from trading_os.domain.market.models import SymbolSpec
from trading_os.domain.primitives import Side
from trading_os.domain.risk.sizing import (
    SizingResult,
    commission_in_price,
    cost_ratio,
    floor_to_step,
    loss_per_lot,
    size_position,
)
from trading_os.shared.errors import SizingError


def size(
    spec: SymbolSpec,
    entry: float,
    stop: float,
    *,
    side: Side = Side.BUY,
    balance: float = 10_000.0,
    risk: float = 1.0,
    **kwargs: Any,
) -> SizingResult:
    return size_position(
        balance=balance, risk_percent=risk, side=side, entry_price=entry, stop_loss=stop, spec=spec, **kwargs
    )


class TestFiveInstruments:
    def test_eurusd_ten_pip_stop(self) -> None:
        result = size(EURUSD, 1.1000, 1.0990)
        assert result.volume == 1.0  # 100 USD budget ÷ 100 USD per lot (10 pips)
        assert result.risk_at_stop == pytest.approx(100.0)
        assert result.effective_risk_percent == pytest.approx(1.0)

    def test_gbpusd_twenty_pip_stop(self) -> None:
        result = size(GBPUSD, 1.2500, 1.2480)
        assert result.volume == 0.5 and result.risk_at_stop == pytest.approx(100.0)

    def test_xauusd_five_dollar_stop(self) -> None:
        # 5.00 ÷ 0.001 × 0.1 = 500 USD per lot → 0.2 lot
        result = size(XAUUSD, 3300.000, 3295.000)
        assert result.volume == 0.2 and result.risk_at_stop == pytest.approx(100.0)

    def test_gbpjpy_is_sized_from_its_own_tick_value_and_never_rounds_up(self) -> None:
        # 30 pips = 0.300 → 0.300 ÷ 0.001 × 0.66667 = 200.001 USD per lot; 100 ÷ 200.001 = 0.4999… → floor to 0.49
        result = size(GBPJPY, 190.000, 189.700)
        assert result.volume == 0.49
        assert result.risk_at_stop <= 100.0

    def test_btcusd_five_hundred_dollar_stop(self) -> None:
        result = size(BTCUSD, 60_000.00, 59_500.00)
        assert result.volume == 0.2 and result.risk_at_stop == pytest.approx(100.0)

    def test_a_sell_mirrors_a_buy(self) -> None:
        assert size(EURUSD, 1.0990, 1.1000, side=Side.SELL).volume == size(EURUSD, 1.1000, 1.0990).volume

    def test_the_old_gold_factor_would_have_been_wrong_here(self) -> None:
        """The previous engine sized EURUSD with ``risk / (distance × 100)``: 100 / (0.001 × 100) = 1000 lots."""
        legacy = 100.0 / (0.0010 * 100)
        assert legacy == pytest.approx(1000.0)
        assert size(EURUSD, 1.1000, 1.0990).volume == 1.0


class TestCostsAreInsideTheStop:
    def test_spread_and_commission_reduce_the_volume(self) -> None:
        # (0.0010 + 0.0001) ÷ 0.00001 = 110 USD per lot + 7 commission = 117 → 100 ÷ 117 = 0.854 → 0.85
        result = size(EURUSD, 1.1000, 1.0990, spread=0.00010, commission_per_lot_round_trip=7.0)
        assert result.volume == 0.85
        assert result.loss_per_lot == pytest.approx(117.0)
        assert result.risk_at_stop == pytest.approx(0.85 * 117.0, abs=0.01) and result.risk_at_stop <= 100.0

    def test_commission_as_a_price_distance(self) -> None:
        assert commission_in_price(7.0, EURUSD) == pytest.approx(0.00007)  # 0.7 pip
        assert commission_in_price(0.0, EURUSD) == 0.0

    def test_cost_ratio(self) -> None:
        assert cost_ratio(0.00008, 0.00007, 0.0006) == pytest.approx(0.25)
        assert cost_ratio(0.0001, 0.0, 0.0) == math.inf


class TestRefusals:
    def test_the_minimum_lot_over_the_budget_is_refused_not_rounded_up(self) -> None:
        with pytest.raises(SizingError) as caught:
            size(EURUSD, 1.1000, 1.0990, balance=100.0, risk=0.1)  # 0.10 USD budget, 100 USD per lot
        assert caught.value.code == "min_volume_exceeds_risk"

    def test_stop_on_the_wrong_side(self) -> None:
        with pytest.raises(SizingError) as caught:
            size(EURUSD, 1.1000, 1.1010)
        assert caught.value.code == "stop_wrong_side"
        with pytest.raises(SizingError):
            size(EURUSD, 1.1000, 1.0990, side=Side.SELL)

    def test_stop_under_the_broker_minimum_distance(self) -> None:
        tight = EURUSD.model_copy(update={"stops_level_points": 50})  # 50 × 0.00001 = 0.0005
        with pytest.raises(SizingError) as caught:
            size(tight, 1.1000, 1.0997)
        assert caught.value.code == "stop_too_close"

    def test_missing_tick_value_is_an_error_not_a_default(self) -> None:
        broken = EURUSD.model_copy(update={"tick_value": 0.0, "tick_value_loss": None})
        with pytest.raises(SizingError) as caught:
            size(broken, 1.1000, 1.0990)
        assert caught.value.code == "missing_tick_value"

    def test_invalid_inputs_and_untradable_symbols(self) -> None:
        with pytest.raises(SizingError):
            size(EURUSD, 1.1000, 1.0990, balance=0.0)
        with pytest.raises(SizingError):
            size(EURUSD, 1.1000, 1.0990, risk=0.0)
        with pytest.raises(SizingError) as caught:
            size(EURUSD.model_copy(update={"trade_allowed": False}), 1.1000, 1.0990)
        assert caught.value.code == "symbol_not_tradable"


class TestCaps:
    def test_per_order_volume_cap(self) -> None:
        result = size(EURUSD, 1.1000, 1.0990, volume_cap=0.5)
        assert result.volume == 0.5 and result.capped == "max_volume_per_order"

    def test_broker_maximum(self) -> None:
        result = size(EURUSD.model_copy(update={"volume_max": 0.3}), 1.1000, 1.0990)
        assert result.volume == 0.3 and result.capped == "volume_max"

    def test_tick_value_loss_wins_over_the_profit_side_value(self) -> None:
        asymmetric = EURUSD.model_copy(update={"tick_value": 1.0, "tick_value_loss": 1.2})
        assert loss_per_lot(asymmetric, 0.0010) == pytest.approx(120.0)


class TestFloorToStep:
    def test_no_binary_float_artefacts(self) -> None:
        assert 0.29 / 0.01 < 29  # the trap: 28.999999999999996
        assert floor_to_step(0.29, 0.01) == 0.29
        assert floor_to_step(1.0000000000011, 0.01) == 1.0
        assert floor_to_step(0.0999999, 0.01) == 0.09
        assert floor_to_step(0.5, 0.1) == 0.5
