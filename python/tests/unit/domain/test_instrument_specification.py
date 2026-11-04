"""The instrument as the terminal reports it: complete, and honest about what it did not say (ADR 0036)."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from trading_os.domain.market.instrument import InstrumentSpecification, specification_from_terminal
from trading_os.domain.market.models import SymbolSpec

NOW = datetime(2026, 11, 3, 12, 0, tzinfo=UTC)


def terminal_reply(**changes: Any) -> dict[str, Any]:
    """A ``symbol_info`` reply the way a market-execution terminal gives it (simulated values, not a live reading)."""
    raw: dict[str, Any] = {
        "name": "EURUSDm",
        "description": "Euro vs US Dollar",
        "currency_base": "EUR",
        "currency_profit": "USD",
        "currency_margin": "EUR",
        "digits": 5,
        "point": 0.00001,
        "trade_tick_size": 0.00001,
        "trade_tick_value": 1.0,
        "trade_tick_value_profit": 1.0,
        "trade_tick_value_loss": 1.0,
        "trade_contract_size": 100_000.0,
        "volume_min": 0.01,
        "volume_max": 200.0,
        "volume_step": 0.01,
        "volume_limit": 0.0,
        "trade_stops_level": 0,
        "trade_freeze_level": 0,
        "trade_mode": 4,
        "trade_exemode": 2,
        "filling_mode": 3,
        "swap_mode": 1,
        "swap_long": -6.5,
        "swap_short": 2.1,
        "swap_rollover3days": 3,
        "spread": 8,
        "spread_float": True,
        "bid": 1.1,
        "ask": 1.10008,
        "last": 0.0,
    }
    raw.update(changes)
    return raw


def build(raw: dict[str, Any]) -> InstrumentSpecification:
    spec = specification_from_terminal("EURUSDm", raw, now=NOW)
    assert spec is not None
    return spec


class TestACompleteReply:
    def test_everything_the_terminal_gave_is_kept_and_decoded(self) -> None:
        spec = build(terminal_reply())
        assert (spec.bid, spec.ask, spec.last) == (1.1, 1.10008, None)  # forex has no last price: none, not 0
        assert (spec.spread_points, spec.spread_floating) == (8, True)
        assert (spec.trade_mode, spec.execution_mode, spec.filling_modes) == ("FULL", "MARKET", ("FOK", "IOC"))
        assert (spec.swap_mode, spec.swap_long, spec.swap_short, spec.swap_triple_day) == (
            "POINTS",
            -6.5,
            2.1,
            "WEDNESDAY",
        )
        assert (spec.volume_limit, spec.stops_level_points, spec.freeze_level_points) == (0.0, 0, 0)
        assert (spec.currency_base, spec.currency_profit, spec.currency_margin) == ("EUR", "USD", "EUR")
        assert spec.updated_at == NOW and spec.provenance == "terminal"

    def test_it_is_a_symbol_spec_so_everything_that_sizes_an_order_still_reads_it(self) -> None:
        spec = build(terminal_reply())
        assert isinstance(spec, SymbolSpec)
        assert (spec.tick_size, spec.tick_value, spec.contract_size, spec.volume_min) == (0.00001, 1.0, 100_000, 0.01)
        assert spec.trade_allowed

    def test_the_only_gap_is_the_sessions_the_python_api_cannot_give(self) -> None:
        spec = build(terminal_reply())
        assert spec.missing == ("trading_sessions",)
        assert spec.trading_sessions is None
        assert spec.missing_for_trading == ()


class TestWhatTheTerminalDidNotSayIsNeverInvented:
    def test_a_missing_swap_is_unknown_not_zero(self) -> None:
        raw = terminal_reply()
        del raw["swap_long"], raw["swap_short"], raw["swap_mode"], raw["swap_rollover3days"]
        spec = build(raw)
        assert (spec.swap_long, spec.swap_short, spec.swap_mode, spec.swap_triple_day) == (None, None, None, None)
        assert {"swap_long", "swap_short", "swap_mode", "swap_triple_day"} <= set(spec.missing)

    def test_a_swap_of_zero_that_the_terminal_reported_is_a_value(self) -> None:
        spec = build(terminal_reply(swap_long=0.0, swap_short=0.0, swap_mode=0))
        assert (spec.swap_long, spec.swap_short, spec.swap_mode) == (0.0, 0.0, "DISABLED")
        assert "swap_long" not in spec.missing

    def test_what_an_order_needs_is_blocking_when_it_is_missing(self) -> None:
        raw = terminal_reply()
        del raw["filling_mode"], raw["trade_exemode"], raw["trade_stops_level"], raw["trade_freeze_level"]
        spec = build(raw)
        assert set(spec.missing_for_trading) == {"filling_mode", "execution_mode", "stops_level", "freeze_level"}
        assert spec.filling_modes == () and spec.execution_mode is None

    def test_a_symbol_that_allows_no_filling_flag_is_not_a_usable_reading(self) -> None:
        assert "filling_mode" in build(terminal_reply(filling_mode=0)).missing_for_trading

    def test_a_trade_mode_the_terminal_did_not_state_is_not_assumed_full(self) -> None:
        raw = terminal_reply()
        del raw["trade_mode"]
        spec = build(raw)
        assert spec.trade_mode is None and not spec.trade_allowed and "trade_mode" in spec.missing_for_trading

    def test_no_quote_is_none_not_zero(self) -> None:
        spec = build(terminal_reply(bid=0.0, ask=0.0))
        assert (spec.bid, spec.ask) == (None, None)
        assert {"bid", "ask"} <= set(spec.missing)
        assert spec.missing_for_trading == ()  # quotes are the data-quality gate's business, not the specification's

    def test_a_missing_loss_tick_value_is_listed_and_sizing_keeps_the_documented_fallback(self) -> None:
        spec = build(terminal_reply(trade_tick_value_loss=0.0))
        assert spec.tick_value_loss is None and "tick_value_loss" in spec.missing
        assert spec.loss_tick_value == spec.tick_value


class TestModes:
    def test_close_only_is_visible_and_not_tradable(self) -> None:
        spec = build(terminal_reply(trade_mode=3))
        assert spec.trade_mode == "CLOSE_ONLY" and not spec.trade_allowed

    def test_an_unknown_code_is_named_as_unknown_rather_than_mapped_to_something_else(self) -> None:
        spec = build(terminal_reply(trade_exemode=9, swap_mode=42))
        assert (spec.execution_mode, spec.swap_mode) == ("UNKNOWN(9)", "UNKNOWN(42)")

    def test_the_filling_flags_decode_each_bit(self) -> None:
        assert build(terminal_reply(filling_mode=1)).filling_modes == ("FOK",)
        assert build(terminal_reply(filling_mode=2)).filling_modes == ("IOC",)
        assert build(terminal_reply(filling_mode=3)).filling_modes == ("FOK", "IOC")


class TestAnUnusableReply:
    def test_a_symbol_without_what_sizing_needs_is_refused_not_guessed(self) -> None:
        for key in ("trade_contract_size", "volume_min", "volume_max", "volume_step"):
            raw = terminal_reply()
            raw[key] = 0
            assert specification_from_terminal("EURUSDm", raw, now=NOW) is None, key
        raw = terminal_reply(trade_tick_size=0.0, point=0.0, digits=0)
        assert specification_from_terminal("EURUSDm", raw, now=NOW) is None
