"""S01 on more than one price scale (ADR 0043): the symbols are a setting, and a symbol whose price is not on the EURUSD's scale is evaluated with its own
posed thresholds — never with pips applied to a 68 000 USD bitcoin."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from trading_os.app.config import Settings
from trading_os.domain.strategy.s01.config import BTCUSD_SCALE, XAUUSD_SCALE, S01Config
from trading_os.domain.strategy.s02.config import S02Config


def test_the_eurusd_keeps_its_own_values_and_the_bitcoin_gets_its_scale() -> None:
    config = S01Config(symbols=("EURUSD", "BTCUSD"))
    eurusd, bitcoin = config.for_symbol("EURUSD"), config.for_symbol("BTCUSD")
    assert eurusd is config  # untouched: the EURUSD-scale values are the fields themselves
    assert (bitcoin.equal_level_tolerance, bitcoin.min_fvg_size, bitcoin.spread_buffer, bitcoin.level_decimals) == (
        18.0,
        6.0,
        8.0,
        0,
    )
    assert (
        bitcoin.min_risk_reward == config.min_risk_reward and bitcoin.trading_windows == config.trading_windows
    )  # only the price-unit values move


def test_the_bitcoin_spread_buffer_covers_the_spread_measured_on_the_demo() -> None:
    assert BTCUSD_SCALE.spread_buffer > 6.40  # a stop inside the spread would be hit by the spread alone


def test_gold_gets_its_own_scale_posed_like_the_bitcoins() -> None:
    """XAUUSD (2026-11-22, Exhorte: « nous allons nous spécialiser sur le XAUUSD »): the EURUSD's geometry carried by the price ratio measured on
    the demo (3 540.18 / 1.09678 ≈ 3 228): 3 pips → 0.97 → 1.0 USD, 1 pip → 0.32 → 0.3 USD; levels kept to the cent, the original strategy's
    and gold's own two decimals."""
    gold = S01Config(symbols=("XAUUSD",)).for_symbol("XAUUSD")
    assert (gold.equal_level_tolerance, gold.min_fvg_size, gold.spread_buffer, gold.level_decimals) == (
        1.0,
        0.3,
        0.3,
        2,
    )
    assert gold.min_risk_reward == S01Config().min_risk_reward  # only the price-unit values move
    assert Settings(_env_file=None, strategy_s01_symbols="XAUUSD").s01_symbols == ("XAUUSD",)


def test_the_gold_spread_buffer_covers_the_spread_measured_on_the_demo() -> None:
    assert (
        XAUUSD_SCALE.spread_buffer >= 1.25 * 0.24
    )  # 0.24 USD: the XAUUSDm spread read on the terminal, as 1.25 × for the bitcoin


def test_a_symbol_without_a_scale_and_an_unknown_name_use_the_eurusd_values() -> None:
    config = S01Config()
    assert config.for_symbol("GBPUSD") is config and config.for_symbol(None) is config


def test_s02_inherits_the_scales() -> None:
    assert S02Config().for_symbol("BTCUSD").min_fvg_size == BTCUSD_SCALE.min_fvg_size


def test_the_symbols_are_a_setting_read_in_canonical_names() -> None:
    assert Settings(_env_file=None, strategy_s01_symbols=" eurusd , BTCUSD ").s01_symbols == ("EURUSD", "BTCUSD")
    assert Settings(_env_file=None).s01_symbols == ()  # empty = S01's own default


def test_a_symbol_the_core_does_not_know_stops_it_at_start() -> None:
    with pytest.raises(ValidationError, match="unknown symbol"):
        Settings(_env_file=None, strategy_s01_symbols="EURUSD,DOGEUSD")
